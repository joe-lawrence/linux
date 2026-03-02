#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
klp-build test runner - runtime verification phase.

Loads built livepatch modules into a running kernel and verifies they work correctly.
Requires root privileges and a matching kernel.
"""

import sys
import os
import argparse
import subprocess
import signal
from pathlib import Path

# Force line-buffered stdout so output from the outer (host-side) process
# isn't reordered relative to inner VM output when piped through tee/etc.
sys.stdout.reconfigure(line_buffering=True)

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from lib import (
    get_test_dir,
    get_kernel_src_dir,
    get_artifacts_dir,
    find_test_cases,
    find_matching_tests,
    load_expected_module,
    get_test_name,
    colors,
)
from lib.livepatch import (
    LivepatchError,
    DmesgCapture,
    RuntimeContext,
    load_module,
    unload_module,
    enable_livepatch,
    disable_livepatch,
    wait_for_transition,
    get_livepatch_state,
    check_root,
    check_kernel_match,
    check_clean_environment,
    is_module_loaded,
)
from lib.state import TestStatus
from lib.patched_tree import (
    apply_kernel_patches,
    revert_kernel_patches,
    load_and_generate_base_patches,
)


_TREE_TYPES = ("current-tree", "patched-tree")


def _discover_profiles(artifacts_dir: Path) -> list[str]:
    """Return sorted profile names from artifacts/."""
    if not artifacts_dir.exists():
        return []
    return sorted(
        p.name for p in artifacts_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _find_test_artifact_dirs(artifacts_dir: Path, test_basename: str,
                             profile: str | None = None):
    """Yield (profile_dir, test_artifact_dir) for a test.

    If *profile* is given, only search that profile's directory.
    Otherwise search across all profiles (legacy behaviour).

    Handles both the new layout (profile/tree-type/test/) and the legacy
    flat layout (profile/test/) for backward compatibility.
    """
    if not artifacts_dir.exists():
        return
    if profile is not None:
        profile_dirs = [artifacts_dir / profile]
    else:
        profile_dirs = [p for p in artifacts_dir.iterdir() if p.is_dir()]
    for profile_dir in profile_dirs:
        if not profile_dir.is_dir():
            continue
        for tree_type in _TREE_TYPES:
            candidate = profile_dir / tree_type / test_basename
            if candidate.exists():
                yield profile_dir, candidate
        # Legacy flat layout fallback
        candidate = profile_dir / test_basename
        if candidate.exists() and candidate.is_dir():
            if not any((candidate / t).exists() for t in _TREE_TYPES):
                yield profile_dir, candidate


def _get_kernel_version(kernel_src: Path = None) -> str:
    """Return kernel version: from source tree (make kernelrelease) if kernel_src given, else uname -r."""
    try:
        if kernel_src is not None:
            r = subprocess.run(
                ["make", "-s", "kernelrelease"],
                cwd=str(kernel_src),
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            r = subprocess.run(
                ["uname", "-r"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        return r.stdout.strip() if r.returncode == 0 else "Unknown"
    except Exception:
        return "Unknown"


def _find_saved_kernel(artifacts_dir: Path, tree_type: str,
                       profile: str | None = None) -> Path | None:
    """Find saved kernel artifacts for a tree type.

    If *profile* is given, only look in that profile's directory.
    Otherwise search across all profiles (first match wins).

    Looks for artifacts/<profile>/<tree_type>/kernel/bzImage.
    Returns the kernel directory path, or None if not found.
    """
    if not artifacts_dir.exists():
        return None
    if profile is not None:
        kernel_dir = artifacts_dir / profile / tree_type / "kernel"
        return kernel_dir if (kernel_dir / "bzImage").exists() else None
    for profile_dir in artifacts_dir.iterdir():
        if not profile_dir.is_dir():
            continue
        kernel_dir = profile_dir / tree_type / "kernel"
        if (kernel_dir / "bzImage").exists():
            return kernel_dir
    return None


def _restore_kernel_to_source(kernel_root: Path, kernel_dir: Path) -> str:
    """Restore saved bzImage and modules to the kernel source tree.

    Copies the saved bzImage to arch/x86/boot/bzImage and the saved
    modules_install output to <kernel_root>/lib/modules/<version>/.

    Returns the kernel release string.
    """
    import shutil

    # Restore bzImage.
    saved_bzimage = kernel_dir / "bzImage"
    dest_bzimage = kernel_root / "arch" / "x86" / "boot" / "bzImage"
    dest_bzimage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(saved_bzimage), str(dest_bzimage))

    # Read saved kernel release.
    release_file = kernel_dir / "kernel.release"
    krelease = release_file.read_text().strip() if release_file.exists() else "unknown"

    # Restore modules.
    saved_modules = kernel_dir / "lib" / "modules"
    if saved_modules.exists():
        dest_modules = kernel_root / "lib" / "modules"
        dest_modules.mkdir(parents=True, exist_ok=True)
        for ver_dir in saved_modules.iterdir():
            if not ver_dir.is_dir():
                continue
            dest_ver = dest_modules / ver_dir.name
            if dest_ver.exists():
                shutil.rmtree(str(dest_ver))
            shutil.copytree(str(ver_dir), str(dest_ver), symlinks=True)
            # Ensure build/source symlinks point to current source tree.
            for link_name in ("build", "source"):
                link_path = dest_ver / link_name
                if link_path.is_symlink():
                    link_path.unlink()
                link_path.symlink_to(str(kernel_root))

    return krelease


def _write_runtime_log(
    path: Path,
    test_name: str,
    verdict: str,
    dmesg_content: str,
    extra_lines: list = None,
    verification_section: str = None,
) -> None:
    """Write runtime-test.log with banner format similar to build-test.log."""
    kernel = _get_kernel_version(get_kernel_src_dir())
    extra = (extra_lines or [])
    with open(path, "w") as log:
        log.write(f"{'='*70}\n")
        log.write(f"RUNTIME LOG: {test_name}\n")
        log.write(f"{'='*70}\n")
        log.write(f"Verdict:    {verdict}\n")
        log.write(f"Kernel:     {kernel}\n")
        for line in extra:
            log.write(f"{line}\n")
        if extra:
            log.write(f"\n")
        if verification_section:
            log.write("\n")
            log.write(f"{'='*70}\n")
            log.write("RUNTIME VERIFICATION\n")
            log.write(f"{'='*70}\n\n")
            log.write(verification_section)
            if verification_section and not verification_section.endswith("\n"):
                log.write("\n")
            log.write("\n")
        log.write(f"{'='*70}\n")
        log.write("DMESG LOG (captured during test)\n")
        log.write(f"{'='*70}\n")
        log.write(dmesg_content)
        if dmesg_content and not dmesg_content.endswith("\n"):
            log.write("\n")
        log.write("\n")


class TapReporter:
    """TAP (Test Anything Protocol) version 13 output."""
    
    def __init__(self):
        self.test_count = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
    
    def print_header(self, total_tests: int):
        """Print TAP header."""
        print("TAP version 13")
        print(f"1..{total_tests}")
    
    def print_test(self, name: str, status: TestStatus, comment: str = ""):
        """Print a test result."""
        self.test_count += 1
        
        if status == TestStatus.PASSED:
            self.passed += 1
            print(f"ok {self.test_count} {name}")
        elif status == TestStatus.FAILED:
            self.failed += 1
            comment_str = f" # {comment}" if comment else ""
            print(f"not ok {self.test_count} {name}{comment_str}")
            if comment:
                # Print comment lines prefixed with #
                for line in comment.split('\n'):
                    if line:
                        print(f"# {line}")
        elif status == TestStatus.SKIPPED:
            self.skipped += 1
            comment_str = f" # SKIP {comment}" if comment else " # SKIP"
            print(f"ok {self.test_count} {name}{comment_str}")
        elif status == TestStatus.ERROR:
            self.failed += 1
            print(f"not ok {self.test_count} {name} # ERROR")
            if comment:
                for line in comment.split('\n'):
                    if line:
                        print(f"# {line}")
    
    def print_summary(self):
        """Print summary of test results."""
        total = self.test_count
        print(f"# Totals: pass:{self.passed} fail:{self.failed} "
              f"skip:{self.skipped} total:{total}")


def run_runtime_tests(test_cases: list[Path], args,
                      profile: str | None = None) -> int:
    """
    Run runtime tests for each test case with a verify_runtime() function.

    If *profile* is given, only use .ko artifacts from that profile and
    write runtime logs into that profile's artifact directory.

    Args:
        test_cases: List of test case directories
        args: Command line arguments
        profile: Restrict artifact lookup to this profile

    Returns:
        Exit code (0 if all passed, 1 if any failed)
    """
    # Get timeout from environment or use default (5 minutes)
    transition_timeout = int(os.environ.get("KLP_TRANSITION_TIMEOUT", "300"))
    
    # TAP output
    tap = TapReporter()
    
    # Find tests that have runtime verification
    runtime_tests = []
    artifacts_dir = get_artifacts_dir()
    
    for test_case_dir in test_cases:
        try:
            expected = load_expected_module(test_case_dir)
            if hasattr(expected, "verify_runtime"):
                runtime_tests.append(test_case_dir)
        except Exception:
            pass
    
    tap.print_header(len(runtime_tests))
    
    if not runtime_tests:
        print(f"{colors.yellow}No tests with runtime verification found{colors.reset}")
        tap.print_summary()
        return 0
    
    print()
    print(f"{colors.cyan}Running runtime verification tests...{colors.reset}")
    print(f"Livepatch transition timeout: {transition_timeout}s")
    print()
    
    # Track test results
    failed_tests = []
    
    for i, test_case_dir in enumerate(runtime_tests):
        test_name = get_test_name(test_case_dir)
        test_basename = test_case_dir.name
        
        # Find artifact directory (scoped to profile if given)
        artifact_dir = None
        ko_file = None
        
        for _, tdir in _find_test_artifact_dirs(artifacts_dir, test_basename,
                                                profile=profile):
            ko_files = list(tdir.glob("*.ko"))
            if ko_files:
                artifact_dir = tdir
                ko_file = ko_files[0]
                break
        
        if not artifact_dir:
            if profile:
                artifact_dir = artifacts_dir / profile / test_name
            else:
                artifact_dir = artifacts_dir / test_name
        
        artifact_dir.mkdir(parents=True, exist_ok=True)
        runtime_log = artifact_dir / "runtime-test.log"
        
        print(f"[{i+1}/{len(runtime_tests)}] {colors.cyan}{test_name}:{colors.reset} ", end="", flush=True)
        
        # Verify we found the .ko file
        if not ko_file:
            error_msg = "no .ko file in artifacts"
            print(f"{colors.red}ERROR: {error_msg}{colors.reset}")
            tap.print_test(test_name, TestStatus.ERROR, error_msg)
            failed_tests.append(test_name)
            
            _write_runtime_log(runtime_log, test_name, "FAIL", "", extra_lines=[f"Error: {error_msg}"])
            continue
        
        try:
            # Load expected module
            expected = load_expected_module(test_case_dir)
            
            # Load the module and capture dmesg through verification
            print(f"{colors.yellow}loading...{colors.reset} ", end="", flush=True)
            
            with DmesgCapture() as dmesg:
                mod_name = load_module(ko_file)
                
                # For livepatch modules, wait for auto-enable transition
                # (livepatch modules automatically enable on insmod)
                if Path(f"/sys/kernel/livepatch/{mod_name}").exists():
                    print(f"{colors.yellow}waiting for transition...{colors.reset} ", end="", flush=True)
                    try:
                        wait_for_transition(mod_name, timeout=transition_timeout)
                    except LivepatchError as e:
                        # Transition timeout is a failure - don't cleanup
                        print(f"{colors.red}TIMEOUT{colors.reset}")
                        
                        error_details = (
                            f"Livepatch transition timed out after {transition_timeout}s\n"
                            f"Module: {mod_name}\n"
                            f"This typically indicates tasks stuck in kernel space.\n"
                            f"Check: cat /sys/kernel/livepatch/{mod_name}/transition\n"
                            f"Check: cat /proc/*/stack for stuck tasks"
                        )
                        
                        tap.print_test(test_name, TestStatus.FAILED, error_details)
                        failed_tests.append(test_name)
                        
                        _write_runtime_log(
                            runtime_log, test_name, "FAIL", dmesg.get_full_log(),
                            extra_lines=[error_details],
                            verification_section=runtime.get_verification_log(),
                        )
                        print(f"{colors.yellow}Module still loaded - check system state{colors.reset}")
                        print(f"Log: {runtime_log}")
                        continue
                
                # Create runtime context and run verification while still capturing dmesg
                runtime = RuntimeContext(ko_file, mod_name, dmesg)
                
                print(f"{colors.yellow}verifying...{colors.reset} ", end="", flush=True)
                expected.verify_runtime(runtime)
            
            # DmesgCapture context has now exited - all messages captured
            # Check for issues in the captured dmesg
            issues = []
            
            if dmesg.did_overflow():
                issues.append("DMESG OVERFLOW - messages were lost!")
            
            if dmesg.has_call_trace():
                issues.append("Kernel call trace detected in dmesg")
            
            verdict = "pass" if not issues else "FAIL"
            extra = [f"Issues: {', '.join(issues)}"] if issues else None
            _write_runtime_log(
                runtime_log, test_name, verdict, dmesg.get_full_log(),
                extra_lines=extra,
                verification_section=runtime.get_verification_log(),
            )

            # If there were issues, fail the test
            if issues:
                print(f"{colors.red}FAIL: {', '.join(issues)}{colors.reset}")
                error_msg = '\n'.join(issues)
                tap.print_test(test_name, TestStatus.FAILED, error_msg)
                failed_tests.append(test_name)
                print(f"Log: {runtime_log}")
                continue
            
            # Verification passed - cleanup
            print(f"{colors.yellow}cleaning up...{colors.reset} ", end="", flush=True)
            
            # Disable livepatch if it's still enabled (waits for sysfs to disappear)
            if Path(f"/sys/kernel/livepatch/{mod_name}").exists():
                disable_livepatch(mod_name)
            
            # Unload module (waits for refcnt=0 and /sys/module to disappear)
            if is_module_loaded(mod_name):
                unload_module(mod_name)
            
            print(f"{colors.green}PASS{colors.reset}")
            tap.print_test(test_name, TestStatus.PASSED)

        except LivepatchError as e:
            print(f"{colors.red}FAIL: {e}{colors.reset}")
            tap.print_test(test_name, TestStatus.FAILED, str(e))
            failed_tests.append(test_name)
            
            try:
                dmesg_log = dmesg.get_full_log()
            except NameError:
                dmesg_log = ""
            try:
                verification_section = runtime.get_verification_log()
            except NameError:
                verification_section = ""
            _write_runtime_log(
                runtime_log, test_name, "FAIL", dmesg_log,
                extra_lines=[f"Error: {e}"],
                verification_section=verification_section,
            )

            print(f"{colors.yellow}Module may still be loaded - manual cleanup required{colors.reset}")
            print(f"Check: lsmod | grep {mod_name if 'mod_name' in locals() else 'livepatch'}")
            print(f"Log: {runtime_log}")
            continue
            
        except Exception as e:
            print(f"{colors.red}ERROR: {e}{colors.reset}")
            tap.print_test(test_name, TestStatus.ERROR, str(e))
            failed_tests.append(test_name)
            
            try:
                dmesg_log = dmesg.get_full_log()
            except NameError:
                dmesg_log = ""
            try:
                verification_section = runtime.get_verification_log()
            except NameError:
                verification_section = ""
            _write_runtime_log(
                runtime_log, test_name, "FAIL", dmesg_log,
                extra_lines=[f"Error: {e}"],
                verification_section=verification_section,
            )

            print(f"Log: {runtime_log}")
            continue

    # Print summary
    print()
    tap.print_summary()
    
    if failed_tests:
        print()
        print(f"{colors.red}Failed tests ({len(failed_tests)}):{colors.reset}")
        for test_name in failed_tests:
            print(f"  - {test_name}")
        return 1
    
    return 0 if tap.failed == 0 else 1


def launch_virtme_ng_single(test_name: str = None, debug: bool = False,
                            timeout: int = 600, profile: str | None = None):
    """
    Launch virtme-ng to run a single runtime test (or all tests if test_name is None).

    Args:
        test_name: Single test name to run (None = all tests, for debug mode)
        debug: If True, launch interactive shell without running tests
        timeout: Timeout in seconds for VM execution (default: 600 = 10 minutes)
        profile: Restrict artifact lookup to this profile inside the VM

    Returns:
        Exit code from VM execution
    """
    import subprocess
    import shutil

    # Check for virtme-ng
    if not shutil.which("virtme-ng"):
        print(f"{colors.red}Error: virtme-ng not found{colors.reset}")
        print("Install with: pip install virtme-ng")
        return 1

    kernel_root = get_kernel_src_dir()
    test_dir = get_test_dir()

    # Build base virtme-ng command
    vng_cmd = [
        "virtme-ng", "--run", str(kernel_root),
        "--rw", "--user", "root",
        "--network", "user",
        "--cwd", str(test_dir),
        "--disable-microvm"
    ]

    profile_flag = f" --profile {profile}" if profile else ""

    if debug:
        # Debug mode: just give user a shell
        print(f"{colors.cyan}Launching virtme-ng debug shell...{colors.reset}")
        print()
        print("To run tests manually inside VM:")
        print(f"  cd {test_dir}")
        print("  pip3 install --user pyelftools")
        if test_name:
            print(f"  ./run_runtime_tests.py --force{profile_flag} {test_name}")
        else:
            print(f"  ./run_runtime_tests.py --force{profile_flag}")
        print()
        print("Useful debugging commands:")
        print("  lsmod | grep livepatch")
        print("  dmesg | grep klp")
        print("  ls /sys/kernel/livepatch/")
        print()
        print("Exit shell when done: exit")
        print("=" * 70)
        print()

        # Launch interactive shell (no --exec, no timeout)
        return subprocess.run(vng_cmd).returncode

    else:
        # Normal mode: run single test and exit
        test_arg = test_name if test_name else ""
        exec_cmd = (f"pip3 install --user -q pyelftools 2>/dev/null || true && "
                    f"cd {test_dir} && "
                    f"./run_runtime_tests.py --force{profile_flag} {test_arg}")

        vng_cmd.extend(["--exec", exec_cmd])

        try:
            result = subprocess.run(vng_cmd, timeout=timeout)
            return result.returncode
        except subprocess.TimeoutExpired:
            print(f"{colors.red}ERROR: VM execution timed out after {timeout}s{colors.reset}")
            return 124  # Standard timeout exit code


def detect_vng_profile() -> bool:
    """
    Detect if the current build used a virtme-ng profile.
    
    Checks artifacts/ directory for profile hints that suggest virtme-ng
    was used for configuration.
    
    Returns:
        True if virtme-ng profile detected
    """
    artifacts_dir = get_artifacts_dir()
    if not artifacts_dir.exists():
        return False
    
    # Check for profile markers
    for profile_dir in artifacts_dir.iterdir():
        if not profile_dir.is_dir():
            continue
        
        profile_file = profile_dir / "profile"
        if profile_file.exists():
            try:
                profile_name = profile_file.read_text().strip()
                # Check for virtme-ng in profile name
                if "virtme-ng" in profile_name.lower():
                    return True
            except Exception:
                pass
    
    return False


def _discover_test_cases(args) -> list:
    """Discover test cases based on command-line arguments.

    Returns list of test case Path objects, or calls sys.exit on error.
    """
    test_cases = []
    if args.tests:
        for test_pattern in args.tests:
            matches = find_matching_tests(test_pattern)

            if not matches:
                print(f"{colors.red}Error: No test found matching '{test_pattern}'{colors.reset}")
                all_tests = find_test_cases("pass")
                similar = [t for t in all_tests if test_pattern.lower() in get_test_name(t).lower()]
                if similar:
                    print(f"Did you mean one of:")
                    for t in similar[:5]:
                        print(f"  {get_test_name(t)}")
                sys.exit(1)
            elif len(matches) > 1:
                print(f"{colors.red}Error: Multiple tests match '{test_pattern}':{colors.reset}")
                for m in matches:
                    print(f"  {get_test_name(m)}")
                print(f"Please use full path: pass/long/test-name")
                sys.exit(1)
            else:
                if "pass" in str(matches[0]):
                    test_cases.append(matches[0])
                else:
                    print(f"{colors.yellow}Skipping {get_test_name(matches[0])}: fail/ tests don't have runtime verification{colors.reset}")
    else:
        test_cases = find_test_cases("pass")

    return test_cases


def _filter_runtime_tests(test_cases: list, artifacts_dir: Path,
                          profile: str | None = None,
                          quiet: bool = False) -> tuple[list, int]:
    """Filter test cases to those with .ko artifacts and runtime verification.

    If *profile* is given, only consider .ko files from that profile.
    If *quiet*, suppress per-test skip messages (caller prints summary).

    Returns (filtered_tests, skipped_count).
    """
    from lib import should_skip_test, should_run_runtime_test

    filtered = []
    skipped = 0

    for test_case in test_cases:
        test_name = get_test_name(test_case)
        test_basename = test_case.name

        ko_files = []
        for _, tdir in _find_test_artifact_dirs(artifacts_dir, test_basename,
                                                profile=profile):
            ko_files.extend(tdir.glob("*.ko"))

        if not ko_files:
            if not quiet:
                print(f"{colors.dim}Skipping {test_name}: no .ko artifact (not built){colors.reset}")
            skipped += 1
            continue

        should_skip, reason = should_skip_test(test_case)
        if should_skip:
            if not quiet:
                print(f"{colors.dim}Skipping {test_name}: {reason}{colors.reset}")
            skipped += 1
            continue

        needs_runtime, warning = should_run_runtime_test(test_case)
        if warning and not quiet:
            print(f"{colors.yellow}Warning:{colors.reset} {test_name}: {warning}")

        if needs_runtime:
            filtered.append(test_case)
        else:
            if not quiet:
                print(f"{colors.dim}Skipping {test_name}: no runtime verification{colors.reset}")
            skipped += 1

    return filtered, skipped


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run klp-build runtime verification tests (requires root)"
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Ignored (kept for backward compatibility)"
    )
    parser.add_argument(
        "--vng",
        action="store_true",
        help="Run tests in virtme-ng VM (automatically boots matching kernel)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Launch VM shell without running tests (for manual debugging)"
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="Restrict runtime tests to this profile's artifacts"
    )
    parser.add_argument(
        "tests",
        nargs="*",
        help="Specific test names to run (e.g., 'add-file-diff pass/long/multi-file')"
    )
    
    args = parser.parse_args()

    kernel_src = get_kernel_src_dir()
    artifacts_dir = get_artifacts_dir()
    selftest_root = str(get_test_dir())

    # Discover and filter tests (common to all modes)
    test_cases = _discover_test_cases(args)
    if not test_cases:
        print(f"{colors.cyan}No test cases found{colors.reset}")
        return 0

    print(f"{colors.cyan}Found {len(test_cases)} test case(s){colors.reset}")
    print()

    if args.vng:
        return _run_vng_mode(args, test_cases, kernel_src, artifacts_dir, selftest_root)
    else:
        return _run_local_mode(args, test_cases, kernel_src, artifacts_dir)


def _run_vng_mode(args, test_cases, kernel_src, artifacts_dir, selftest_root):
    """Host-side --vng mode: restore saved kernel, boot VM(s), run tests.

    Iterates over each profile discovered in artifacts/.  For each
    profile the matching saved kernel is restored and only that
    profile's .ko artifacts are used, preventing version-magic
    mismatches between profiles built with different compilers.
    """

    if args.debug:
        return launch_virtme_ng_single(test_name=None, debug=True)

    if getattr(args, "profile", None):
        profiles = [args.profile]
        if not (artifacts_dir / args.profile).is_dir():
            print(f"{colors.red}Profile '{args.profile}' not found under artifacts/{colors.reset}")
            return 1
    else:
        profiles = _discover_profiles(artifacts_dir)
    if not profiles:
        print(f"{colors.red}No profiles found under artifacts/{colors.reset}")
        print("Run 'make build_tests TREE=clean' (or TREE=patched) first.")
        return 1

    base_patches = []

    def cleanup_base_patches():
        if base_patches:
            print(f"\n{colors.cyan}Reverting base patches...{colors.reset}")
            try:
                revert_kernel_patches(str(kernel_src), base_patches)
                print(f"{colors.green}Base patches reverted{colors.reset}")
            except Exception as e:
                print(f"{colors.red}Warning: Failed to revert base patches: {e}{colors.reset}",
                      file=sys.stderr)

    def signal_handler(signum, frame):
        print(f"\n{colors.yellow}Signal {signum} received{colors.reset}", file=sys.stderr)
        cleanup_base_patches()
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    total_passed = 0
    total_failed = 0
    total_run = 0

    try:
        for pi, profile in enumerate(profiles):
            # Filter tests to those with .ko artifacts in THIS profile.
            filtered_tests, skipped_count = _filter_runtime_tests(
                test_cases, artifacts_dir, profile=profile, quiet=True,
            )
            if not filtered_tests:
                continue

            if pi > 0:
                print()
            print(f"{colors.cyan}{'=' * 70}{colors.reset}")
            print(f"{colors.cyan}Profile: {profile}{colors.reset}")
            print(f"{colors.cyan}{'=' * 70}{colors.reset}")
            if skipped_count > 0:
                print(f"{skipped_count} test(s) skipped for this profile")
            print()

            # Verify saved kernels exist for all needed tree types.
            tree_types_needed = set()
            for test_path in filtered_tests:
                parts = str(test_path).split(os.sep)
                if "patched-tree" in parts:
                    tree_types_needed.add("patched-tree")
                else:
                    tree_types_needed.add("current-tree")

            missing_kernel = False
            for tree_type in tree_types_needed:
                kernel_dir = _find_saved_kernel(artifacts_dir, tree_type,
                                                profile=profile)
                if kernel_dir is None:
                    print(f"{colors.red}No saved kernel for {profile}/{tree_type}.{colors.reset}")
                    tree_arg = "current" if tree_type == "current-tree" else "patched"
                    print(f"Run 'make build_tests TREE={tree_arg} PROFILE={profile}' first.")
                    missing_kernel = True
            if missing_kernel:
                total_failed += len(filtered_tests)
                total_run += len(filtered_tests)
                continue

            # Sort tests: current-tree first, then patched-tree.
            def _tree_sort_key(p):
                return 0 if "patched-tree" not in str(p).split(os.sep) else 1
            filtered_tests = sorted(filtered_tests, key=_tree_sort_key)

            print(f"Running {len(filtered_tests)} test(s) in separate VM sessions")
            print(f"VM timeout per test: 600s (10 minutes)")
            print()

            passed = 0
            failed = 0
            restored_tree_type = None

            for idx, test_path in enumerate(filtered_tests):
                test_name = get_test_name(test_path)

                parts = str(test_path).split(os.sep)
                needed_type = "patched-tree" if "patched-tree" in parts else "current-tree"

                # Switch kernel + patches when tree type changes.
                if needed_type != restored_tree_type:
                    if base_patches:
                        print(f"{colors.cyan}Reverting base patches...{colors.reset}")
                        revert_kernel_patches(str(kernel_src), base_patches)
                        base_patches = []

                    kernel_dir = _find_saved_kernel(artifacts_dir, needed_type,
                                                    profile=profile)
                    krelease = _restore_kernel_to_source(kernel_src, kernel_dir)
                    print(f"{colors.green}Restored {needed_type} kernel ({krelease}) from artifacts{colors.reset}",
                          flush=True)
                    restored_tree_type = needed_type

                    if needed_type == "patched-tree":
                        print(f"{colors.cyan}Applying base patches for patched-tree tests...{colors.reset}")
                        base_patches = load_and_generate_base_patches(
                            selftest_root, str(kernel_src),
                        )
                        if base_patches:
                            newly_applied = apply_kernel_patches(
                                str(kernel_src), base_patches,
                            )
                            if newly_applied:
                                print(f"{colors.green}Applied {len(base_patches)} base patch(es){colors.reset}")
                            else:
                                print(f"{colors.green}Base patches already applied{colors.reset}")
                    print()

                print(f"{colors.cyan}[{idx + 1}/{len(filtered_tests)}] "
                      f"{profile} :: {test_name}{colors.reset}", flush=True)

                result = launch_virtme_ng_single(test_name=test_name,
                                                 debug=False, timeout=600,
                                                 profile=profile)

                if result == 0:
                    passed += 1
                    print(f"{colors.green}PASS: {test_name}{colors.reset}")
                elif result == 124:
                    failed += 1
                    print(f"{colors.red}FAIL: {test_name} timed out{colors.reset}")
                else:
                    failed += 1
                    print(f"{colors.red}FAIL: {test_name} (exit code {result}){colors.reset}")
                print()

            # Revert base patches before switching profiles.
            if base_patches:
                print(f"{colors.cyan}Reverting base patches...{colors.reset}")
                revert_kernel_patches(str(kernel_src), base_patches)
                base_patches = []
                print(f"{colors.green}Base patches reverted{colors.reset}")

            restored_tree_type = None
            total_passed += passed
            total_failed += failed
            total_run += passed + failed

            print(f"  {profile}: {passed}/{passed + failed} passed")

        print()
        print("=" * 70)
        print(f"{colors.cyan}VM Test Summary{colors.reset}")
        print(f"  Passed: {total_passed}/{total_run}")
        print(f"  Failed: {total_failed}/{total_run}")
        print()

        return 0 if total_failed == 0 else 1

    finally:
        cleanup_base_patches()


def _run_local_mode(args, test_cases, kernel_src, artifacts_dir):
    """Local mode: run tests directly on the current (possibly VM) kernel."""

    print(f"{colors.cyan}Runtime Test Prerequisites{colors.reset}")
    print("=" * 70)

    try:
        check_root()
        print(f"{colors.green}ok{colors.reset} - Root privileges")
    except LivepatchError as e:
        print(f"{colors.red}not ok{colors.reset} - Root privileges: {e}")
        return 1

    is_clean, clean_msg = check_clean_environment()
    if is_clean:
        print(f"{colors.green}ok{colors.reset} - Environment: {clean_msg}")
    else:
        print(f"{colors.red}not ok{colors.reset} - Environment check failed:")
        for line in clean_msg.split('\n'):
            print(f"  {line}")
        print()
        print(f"{colors.yellow}Please unload existing test modules before running tests{colors.reset}")
        print(f"Example: sudo rmmod <module_name>")
        return 1

    matches, msg = check_kernel_match(kernel_src)
    if matches:
        print(f"{colors.green}ok{colors.reset} - {msg}")
    else:
        print(f"{colors.yellow}WARN{colors.reset} - {msg}")
        print(f"{colors.yellow}Warning:{colors.reset} Module loading may fail due to version mismatch")

        if detect_vng_profile():
            print()
            print(f"{colors.cyan}Hint:{colors.reset} Detected virtme-ng profile. Consider using:")
            print(f"  make runtime_tests_vng")
            print(f"  or: ./run_runtime_tests.py --vng")
            print(f"This will automatically boot the built kernel in a VM.")

    print()

    profile = getattr(args, "profile", None)
    filtered_tests, skipped_count = _filter_runtime_tests(
        test_cases, artifacts_dir, profile=profile,
    )
    if skipped_count > 0:
        print(f"{skipped_count} test(s) skipped")
    if not filtered_tests:
        print(f"{colors.cyan}No tests with runtime verification found{colors.reset}")
        return 0

    print(f"{colors.cyan}Running {len(filtered_tests)} runtime test(s){colors.reset}")
    print()

    return run_runtime_tests(filtered_tests, args, profile=profile)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"{colors.red}Fatal error: {e}{colors.reset}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
