#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
klp-build test runner - runtime verification phase.

Loads built livepatch modules into a running kernel and verifies they work correctly.
Requires root privileges and a matching kernel.
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path

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


def _write_runtime_log(
    path: Path,
    test_name: str,
    result_str: str,
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
        log.write(f"Result:     {result_str}\n")
        log.write(f"\n")
        log.write(f"Kernel:     {kernel}\n")
        log.write(f"\n")
        for line in extra:
            log.write(f"{line}\n")
        if extra:
            log.write(f"\n")
        if verification_section:
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


def run_runtime_tests(test_cases: list[Path], args) -> int:
    """
    Run runtime tests for each test case with a verify_runtime() function.

    Args:
        test_cases: List of test case directories
        args: Command line arguments

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
        test_name = get_test_name(test_case_dir)
        
        # Find the .ko file from build artifacts (search across profile directories)
        test_basename = test_case_dir.name
        ko_file = None
        if artifacts_dir.exists():
            for profile_dir in artifacts_dir.iterdir():
                if profile_dir.is_dir():
                    test_artifact_dir = profile_dir / test_basename
                    if test_artifact_dir.exists():
                        ko_files = list(test_artifact_dir.glob("*.ko"))
                        if ko_files:
                            ko_file = ko_files[0]
                            break
        
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
        
        # Find artifact directory across profiles
        artifact_dir = None
        ko_file = None
        artifacts_dir = get_artifacts_dir()
        
        if artifacts_dir.exists():
            for profile_dir in artifacts_dir.iterdir():
                if profile_dir.is_dir():
                    test_artifact_dir = profile_dir / test_basename
                    if test_artifact_dir.exists():
                        ko_files = list(test_artifact_dir.glob("*.ko"))
                        if ko_files:
                            artifact_dir = test_artifact_dir
                            ko_file = ko_files[0]
                            break
        
        if not artifact_dir:
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
            
            _write_runtime_log(runtime_log, test_name, "FAILURE", "", extra_lines=[f"Error: {error_msg}"])
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
                            runtime_log, test_name, "FAILURE", dmesg.get_full_log(),
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
            
            result_str = "SUCCESS" if not issues else "FAILURE"
            extra = [f"Issues: {', '.join(issues)}"] if issues else None
            _write_runtime_log(
                runtime_log, test_name, result_str, dmesg.get_full_log(),
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
                runtime_log, test_name, "FAILURE", dmesg_log,
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
                runtime_log, test_name, "FAILURE", dmesg_log,
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


def launch_virtme_ng(test_names: list[str], debug: bool = False):
    """
    Launch virtme-ng to run runtime tests.
    
    Args:
        test_names: List of test names to run (empty = all tests)
        debug: If True, launch interactive shell without running tests
    
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
    
    if debug:
        # Debug mode: just give user a shell
        print(f"{colors.cyan}Launching virtme-ng debug shell...{colors.reset}")
        print()
        print("To run tests manually inside VM:")
        print(f"  cd {test_dir}")
        print("  pip3 install --user pyelftools")
        if test_names:
            print(f"  ./run_runtime_tests.py --force {' '.join(test_names)}")
        else:
            print("  ./run_runtime_tests.py --force")
        print()
        print("Useful debugging commands:")
        print("  lsmod | grep livepatch")
        print("  dmesg | grep klp")
        print("  ls /sys/kernel/livepatch/")
        print()
        print("Exit shell when done: exit")
        print("=" * 70)
        print()
        
        # Launch interactive shell (no --exec)
        return subprocess.run(vng_cmd).returncode
    
    else:
        # Normal mode: run test and exit
        test_args = " ".join(test_names) if test_names else ""
        exec_cmd = f"pip3 install --user -q pyelftools 2>/dev/null || true && cd {test_dir} && ./run_runtime_tests.py --force {test_args}"
        
        print(f"{colors.cyan}Launching virtme-ng with built kernel...{colors.reset}")
        vng_cmd.extend(["--exec", exec_cmd])
        return subprocess.run(vng_cmd).returncode


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
        "tests",
        nargs="*",
        help="Specific test names to run (e.g., 'add-file-diff pass/long/multi-file')"
    )
    
    args = parser.parse_args()
    
    # Handle VM mode first
    if args.vng:
        # Launch virtme-ng
        return launch_virtme_ng(args.tests, args.debug)
    
    # Local mode - check prerequisites
    print(f"{colors.cyan}Runtime Test Prerequisites{colors.reset}")
    print("=" * 70)
    
    try:
        check_root()
        print(f"{colors.green}ok{colors.reset} - Root privileges")
    except LivepatchError as e:
        print(f"{colors.red}not ok{colors.reset} - Root privileges: {e}")
        return 1
    
    # Check for clean environment
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
    
    # Check kernel version match
    kernel_src = get_kernel_src_dir()
    matches, msg = check_kernel_match(kernel_src)
    if matches:
        print(f"{colors.green}ok{colors.reset} - {msg}")
    else:
        print(f"{colors.yellow}WARN{colors.reset} - {msg}")
        print(f"{colors.yellow}Warning:{colors.reset} Module loading may fail due to version mismatch")
        
        # Suggest virtme-ng if kernel mismatch and vng profile detected
        if detect_vng_profile():
            print()
            print(f"{colors.cyan}Hint:{colors.reset} Detected virtme-ng profile. Consider using:")
            print(f"  make runtime_tests_vng")
            print(f"  or: ./run_runtime_tests.py --vng")
            print(f"This will automatically boot the built kernel in a VM.")
    
    print()
    
    # Find test cases - only from pass/ (fail/ tests never have runtime verification)
    test_cases = []
    if args.tests:
        # Specific tests requested
        for test_pattern in args.tests:
            matches = find_matching_tests(test_pattern)
            
            if not matches:
                print(f"{colors.red}Error: No test found matching '{test_pattern}'{colors.reset}")
                # Try to suggest similar tests
                all_tests = find_test_cases("pass")
                similar = [t for t in all_tests if test_pattern.lower() in get_test_name(t).lower()]
                if similar:
                    print(f"Did you mean one of:")
                    for t in similar[:5]:
                        print(f"  {get_test_name(t)}")
                return 1
            elif len(matches) > 1:
                print(f"{colors.red}Error: Multiple tests match '{test_pattern}':{colors.reset}")
                for m in matches:
                    print(f"  {get_test_name(m)}")
                print(f"Please use full path: pass/long/test-name")
                return 1
            else:
                # Only include pass/ tests (runtime tests don't make sense for fail/)
                if "pass" in str(matches[0]):
                    test_cases.append(matches[0])
                else:
                    print(f"{colors.yellow}Skipping {get_test_name(matches[0])}: fail/ tests don't have runtime verification{colors.reset}")
    else:
        # All pass/ tests (fail/ completely ignored)
        test_cases = find_test_cases("pass")
    
    if not test_cases:
        print(f"{colors.cyan}No test cases found{colors.reset}")
        return 0  # Success (not error)
    
    print(f"{colors.cyan}Found {len(test_cases)} test case(s){colors.reset}")
    
    # Filter based on environment (arch/compiler) and runtime requirements
    from lib import should_skip_test, should_run_runtime_test
    filtered_tests = []
    skipped_count = 0
    
    artifacts_dir = get_artifacts_dir()
    
    for test_case in test_cases:
        test_name = get_test_name(test_case)
        
        # Check if .ko artifact exists (search across all profile directories)
        # Artifacts are organized as: artifacts/<profile>/<test_name>/*.ko
        ko_files = []
        if artifacts_dir.exists():
            # Extract just the test name without pass/quick/ prefix for artifact lookup
            test_basename = test_case.name
            for profile_dir in artifacts_dir.iterdir():
                if profile_dir.is_dir():
                    test_artifact_dir = profile_dir / test_basename
                    if test_artifact_dir.exists():
                        ko_files.extend(test_artifact_dir.glob("*.ko"))
        
        if not ko_files:
            print(f"{colors.dim}Skipping {test_name}: no .ko artifact (not built){colors.reset}")
            skipped_count += 1
            continue
        
        # Check environment restrictions
        should_skip, reason = should_skip_test(test_case)
        if should_skip:
            print(f"{colors.dim}Skipping {test_name}: {reason}{colors.reset}")
            skipped_count += 1
            continue
        
        # Check if runtime test is needed
        needs_runtime, warning = should_run_runtime_test(test_case)
        if warning:
            print(f"{colors.yellow}Warning:{colors.reset} {test_name}: {warning}")
        
        if needs_runtime:
            filtered_tests.append(test_case)
        else:
            print(f"{colors.dim}Skipping {test_name}: no runtime verification{colors.reset}")
            skipped_count += 1
    
    if skipped_count > 0:
        print(f"{skipped_count} test(s) skipped")
    
    if not filtered_tests:
        print(f"{colors.cyan}No tests with runtime verification found{colors.reset}")
        return 0  # Success per TAP convention
    
    print(f"{colors.cyan}Running {len(filtered_tests)} runtime test(s){colors.reset}")
    print()
    
    return run_runtime_tests(filtered_tests, args)


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
