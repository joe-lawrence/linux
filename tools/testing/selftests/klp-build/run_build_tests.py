#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Run klp-build tests for the current .config.
Discover tests under tests/, filter by profile requirements, run klp-build
and verify; report pass/skip/fail. Exit 77 when no tests run or all skip.
Use --profile to set toolchain from a profile; use --quick for quick tests only.
"""

import argparse
import filecmp
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Optional

# Allow importing from lib when script is run from repo root or selftest dir.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from lib.test_discovery import discover_tests, get_expected_attrs
from lib.requirements import test_belongs_to_profile, config_has_symbol
from lib.klp_build import run_klp_build
from lib.verification import load_expected, run_verify, VerificationError
from lib.build_log import write_build_log
from lib.state import ARTIFACTS_DIR
from lib.patched_tree import (
    apply_kernel_patches,
    revert_kernel_patches,
    load_and_generate_base_patches,
)


# Subdirs of klp-tmp that are rewritten by steps 2-4; clear before -S 2 to avoid residual logs.
_KLP_TMP_DOWNSTREAM = ("patched", "diff", "kmod")


class KernelState:
    """Track kernel source tree state (clean vs modified with patches)."""
    def __init__(self):
        self.is_modified = False
        self.applied_patches = []
        self.test_name = None

    def mark_modified(self, test_name: str, patches: list):
        """Mark kernel as modified with specified patches."""
        self.is_modified = True
        self.test_name = test_name
        self.applied_patches = list(patches)

    def mark_clean(self):
        """Mark kernel as clean (no patches applied)."""
        self.is_modified = False
        self.test_name = None
        self.applied_patches = []


# Patch application/reversion functions moved to lib/patched_tree.py
_apply_kernel_patches = apply_kernel_patches
_revert_kernel_patches = revert_kernel_patches


def _clear_klp_tmp_downstream(kernel_root: str) -> None:
    """Remove patched/diff/kmod under klp-tmp so the next -S 2 run has no residual logs."""
    tmp_dir = os.path.join(kernel_root, "klp-tmp")
    for name in _KLP_TMP_DOWNSTREAM:
        path = os.path.join(tmp_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _copy_patches_to_artifacts(patch_paths: list, artifact_dir: str) -> None:
    """Copy each (static or generated) .patch file into the test's artifacts dir."""
    os.makedirs(artifact_dir, exist_ok=True)
    for p in patch_paths:
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(artifact_dir, os.path.basename(p)))


def _build_and_save_kernel(kernel_root: str, artifacts_root: str,
                           profile_name: str, test_type: str) -> None:
    """Build vmlinux + bzImage and save kernel + modules for runtime testing.

    Called once per tree-type BEFORE any klp-build tests run, while the
    source tree is in the correct state (base patches applied for
    patched-tree, unmodified for current-tree).  Building the kernel
    first establishes the authoritative version string; klp-build then
    reuses this vmlinux and embeds the matching vermagic in its .ko
    output.  The saved kernel is used by run_runtime_tests.py so it
    never has to rebuild.
    """
    kernel_dir = os.path.join(artifacts_root, profile_name, test_type, "kernel")
    os.makedirs(kernel_dir, exist_ok=True)

    jobs = os.cpu_count() or 1

    # Restore setlocalversion to its pristine state before building so
    # that the reference kernel gets the canonical version string.
    slv = os.path.join(kernel_root, "scripts", "setlocalversion")
    subprocess.run(
        ["git", "checkout", slv],
        cwd=kernel_root, capture_output=True, timeout=10,
    )

    print(f"# Building reference kernel for {test_type}: vmlinux + bzImage + modules -j{jobs}",
          flush=True)
    result = subprocess.run(
        ["make", f"-j{jobs}"],
        cwd=kernel_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"# Warning: make failed (exit {result.returncode})",
              flush=True, file=sys.stderr)
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-5:]:
                print(f"#   {line}", flush=True, file=sys.stderr)
        return

    bzimage_src = os.path.join(kernel_root, "arch", "x86", "boot", "bzImage")
    if os.path.isfile(bzimage_src):
        shutil.copy2(bzimage_src, os.path.join(kernel_dir, "bzImage"))

    # Save kernel release string for version matching.
    rel = subprocess.run(
        ["make", "-s", "kernelrelease"],
        cwd=kernel_root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if rel.returncode == 0 and rel.stdout.strip():
        with open(os.path.join(kernel_dir, "kernel.release"), "w") as f:
            f.write(rel.stdout.strip() + "\n")

    # Install modules so runtime tests have a matching set.
    print(f"# Saving kernel for runtime: modules_install", flush=True)
    result = subprocess.run(
        ["make", "modules_install", f"INSTALL_MOD_PATH={kernel_dir}"],
        cwd=kernel_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"# Warning: make modules_install failed (exit {result.returncode})",
              flush=True, file=sys.stderr)
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-10:]:
                print(f"#   {line}", flush=True, file=sys.stderr)

    # Always remove build/source symlinks — they contain absolute paths
    # and shutil.copytree (symlinks=False) would follow them, trying to
    # copy the entire kernel tree.
    modules_base = os.path.join(kernel_dir, "lib", "modules")
    if os.path.isdir(modules_base):
        for ver_dir in os.listdir(modules_base):
            for link_name in ("build", "source"):
                link = os.path.join(modules_base, ver_dir, link_name)
                if os.path.islink(link):
                    os.unlink(link)

    if result.returncode != 0:
        return

    print(f"# Reference kernel saved to {kernel_dir}", flush=True)


def _copy_klp_tmp_to_artifacts(kernel_root: str, artifact_dir: str) -> None:
    """
    Copy kernel_root/klp-tmp to artifact_dir/klp-tmp for later inspection.
    Preserves per-test klp-tmp (orig, patched, diff, kmod) when KLP_BUILD_KEEP_TMP is set.
    """
    if not os.environ.get("KLP_BUILD_KEEP_TMP"):
        return
    klp_tmp_src = os.path.join(kernel_root, "klp-tmp")
    klp_tmp_dst = os.path.join(artifact_dir, "klp-tmp")
    if not os.path.isdir(klp_tmp_src):
        return
    os.makedirs(artifact_dir, exist_ok=True)
    if os.path.isdir(klp_tmp_dst):
        shutil.rmtree(klp_tmp_dst)
    shutil.copytree(klp_tmp_src, klp_tmp_dst)


def set_toolchain_env_from_config(config_path: str) -> None:
    """
    Set CC and LLVM in os.environ to match the current .config so that
    builds (e.g. klp-build) use the same toolchain as olddefconfig did.
    E.g. CONFIG_CC_IS_CLANG=y -> LLVM=1, CC=clang.
    """
    if not os.path.isfile(config_path):
        return
    if config_has_symbol(config_path, "CONFIG_CC_IS_CLANG"):
        os.environ["LLVM"] = "1"
        os.environ["CC"] = "clang"


def _resolve_profile(
    artifacts_root: str,
    config_path: str,
    explicit_profile: Optional[str],
) -> str:
    """Return profile name: --profile if set, else match .config to artifacts/*/config, else 'current-profile'."""
    if explicit_profile:
        return explicit_profile
    if not os.path.isfile(config_path):
        return "current-profile"
    if not os.path.isdir(artifacts_root):
        return "current-profile"
    for name in sorted(os.listdir(artifacts_root)):
        dir_path = os.path.join(artifacts_root, name)
        if not os.path.isdir(dir_path):
            continue
        artifact_config = os.path.join(dir_path, "config")
        if os.path.isfile(artifact_config) and filecmp.cmp(config_path, artifact_config, shallow=False):
            return name
    return "current-profile"


def _ensure_profile_artifact_dir(artifacts_root: str, profile_name: str, config_path: str) -> None:
    """Ensure artifacts/<profile>/ exists with config and profile file."""
    profile_dir = os.path.join(artifacts_root, profile_name)
    os.makedirs(profile_dir, exist_ok=True)
    profile_file = os.path.join(profile_dir, "profile")
    if not os.path.isfile(profile_file):
        with open(profile_file, "w", encoding="utf-8") as f:
            f.write(profile_name + "\n")
    if os.path.isfile(config_path):
        dest_config = os.path.join(profile_dir, "config")
        if not os.path.isfile(dest_config) or not filecmp.cmp(config_path, dest_config, shallow=False):
            shutil.copy2(config_path, dest_config)


def _load_and_apply_base_patches(selftest_root: str, kernel_root: str) -> list:
    """
    Load and apply base patches for patched-tree tests.

    Returns list of applied patch paths.
    Raises exception if base patches cannot be loaded or applied.
    """
    base_patches = load_and_generate_base_patches(selftest_root, kernel_root)

    if not base_patches:
        return []

    # Apply base patches
    print(f"# Applying base patches for patched-tree tests", flush=True)
    _apply_kernel_patches(kernel_root, base_patches)
    print(f"# Applied {len(base_patches)} base patch(es)", flush=True)

    return base_patches


def _cleanup_handler(signum, frame, kernel_state, base_patches, kernel_root):
    """Signal handler to revert kernel patches on Ctrl-C or other interrupts."""
    if kernel_state.is_modified:
        print(f"\n# Signal {signum} received, reverting test patches from {kernel_state.test_name}", flush=True, file=sys.stderr)
        try:
            _revert_kernel_patches(kernel_root, kernel_state.applied_patches)
        except Exception as e:
            print(f"# Warning: failed to revert test patches during interrupt: {e}", flush=True, file=sys.stderr)
    if base_patches:
        print(f"# Reverting base patches", flush=True, file=sys.stderr)
        try:
            _revert_kernel_patches(kernel_root, base_patches)
        except Exception as e:
            print(f"# Warning: failed to revert base patches during interrupt: {e}", flush=True, file=sys.stderr)
    sys.exit(128 + signum)


def main():
    parser = argparse.ArgumentParser(
        description="Run klp-build tests for current .config",
        epilog="""
test types:
  current-tree: Patch current kernel (standard livepatch testing)
                Located in tests/current-tree/{pass,fail}/{quick,long}/
  patched-tree: Modify kernel first, then patch (custom test scenarios)
                Located in tests/patched-tree/{pass,fail}/

WARNING: Do not mix test types in the same run!
  Patched-tree tests modify the kernel baseline, which will corrupt artifacts
  and cause runtime testing to fail. Always run current-tree and patched-tree
  tests separately.

recommended usage (via Makefile):
  make build_tests TREE=current      # Run current-tree tests
  make build_tests TREE=patched      # Run patched-tree tests

advanced usage (direct script invocation):
  %(prog)s --test-type current-tree  # Run all current-tree tests
  %(prog)s --test-type patched-tree  # Run all patched-tree tests
  %(prog)s --quick                   # Run only current-tree quick tests
  %(prog)s --test helper-function    # Run specific test by name
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="Profile or chain (e.g. full-default+overlay-thin-lto); sets toolchain to match",
    )
    parser.add_argument(
        "--test-type",
        metavar="TYPE",
        choices=["current-tree", "patched-tree"],
        help="Run only tests of this type (current-tree or patched-tree)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only quick current-tree tests (current-tree/*/quick/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include klp-tmp logs (diff.log, orig/patched/kmod build.log) in build-test.log",
    )
    parser.add_argument(
        "--test",
        metavar="NAME",
        help="Run only the test with this exact name (e.g. helper-function)",
    )
    parser.add_argument(
        "--keep-klp-tmp",
        action="store_true",
        help="Copy klp-tmp to artifacts after each build (same as KLP_BUILD_KEEP_TMP=1)",
    )
    parser.add_argument(
        "--copy-klp-tmp-to",
        metavar="TEST_ID",
        help="Copy current kernel klp-tmp to artifacts for this test and exit (e.g. fail/long/recount-many-files)",
    )
    args = parser.parse_args()

    selftest_root = _SCRIPT_DIR
    kernel_root = os.path.abspath(os.path.join(selftest_root, "..", "..", "..", ".."))
    config_path = os.path.join(kernel_root, ".config")
    artifacts_root = os.path.join(selftest_root, ARTIFACTS_DIR)

    profile_name = _resolve_profile(artifacts_root, config_path, args.profile)
    _ensure_profile_artifact_dir(artifacts_root, profile_name, config_path)

    # Direct copy of klp-tmp for a single test (reproduce / inspect after manual run)
    if args.copy_klp_tmp_to is not None:
        kernel_root = os.path.abspath(os.path.join(selftest_root, "..", "..", "..", ".."))
        test_id = args.copy_klp_tmp_to.strip()
        test_name = test_id.split("/")[-1] if "/" in test_id else test_id
        # Determine tree type from test discovery or --test-type
        tree_type = args.test_type
        if not tree_type:
            all_tests = discover_tests(selftest_root)
            for ttype, tid, *_ in all_tests:
                if tid.split("/")[-1] == test_name:
                    tree_type = ttype
                    break
        if not tree_type:
            tree_type = "unknown"
        artifact_dir = os.path.join(artifacts_root, profile_name, tree_type, test_name)
        klp_tmp_src = os.path.join(kernel_root, "klp-tmp")
        if not os.path.isdir(klp_tmp_src):
            print(f"error: no klp-tmp at {klp_tmp_src}", file=sys.stderr)
            return 1
        os.makedirs(artifact_dir, exist_ok=True)
        klp_tmp_dst = os.path.join(artifact_dir, "klp-tmp")
        if os.path.isdir(klp_tmp_dst):
            shutil.rmtree(klp_tmp_dst)
        shutil.copytree(klp_tmp_src, klp_tmp_dst)
        print(f"Copied klp-tmp to {artifact_dir}/klp-tmp", flush=True)
        return 0

    if args.keep_klp_tmp:
        os.environ["KLP_BUILD_KEEP_TMP"] = "1"

    if args.profile:
        from lib.profile import apply_toolchain_for_profile
        apply_toolchain_for_profile(args.profile)
        profile_compiler = None  # use current env (we just set it)
    else:
        # Match build toolchain to .config so make does not prompt (e.g. LLVM=1).
        set_toolchain_env_from_config(config_path)
        profile_compiler = None

    tests = discover_tests(selftest_root)
    if args.test_type:
        tests = [(ttype, tid, tdir, patches, exp) for ttype, tid, tdir, patches, exp in tests
                 if ttype == args.test_type]
    if args.quick:
        tests = [(ttype, tid, tdir, patches, exp) for ttype, tid, tdir, patches, exp in tests
                 if ttype == "current-tree" and tid.split("/")[0] == "pass" and tid.split("/")[1] == "quick"]
    if args.test:
        name = args.test
        tests = [(ttype, tid, tdir, patches, exp) for ttype, tid, tdir, patches, exp in tests
                 if tid.split("/")[-1] == name]
    if not tests:
        print("TAP version 13", flush=True)
        print("1..0 # no tests found", flush=True)
        return 77

    print("TAP version 13", flush=True)
    print(f"1..{len(tests)}", flush=True)

    passed = 0
    xfailed = 0
    skipped = 0
    failed = 0
    xpassed = 0
    first_build = True
    kernel_built_for = set()  # tree types whose reference kernel has been built
    kernel_state = KernelState()
    test_num = 1
    desc_prefix = f"{profile_name} :: "
    base_patches = []

    # Install signal handler to revert patches on Ctrl-C
    def signal_handler(signum, frame):
        _cleanup_handler(signum, frame, kernel_state, base_patches, kernel_root)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    for test_type, test_id, test_dir, patch_paths, expect_success in tests:
        attrs = get_expected_attrs(test_dir)
        if not test_belongs_to_profile(attrs, profile_name, config_path, profile_compiler):
            print(f"ok {test_num} - {desc_prefix}{test_id} # SKIP", flush=True)
            test_num += 1
            skipped += 1
            continue

        # On first encounter of each tree type, prepare the tree and
        # build + save the reference kernel BEFORE any klp-build tests.
        if test_type not in kernel_built_for:
            if test_type == "patched-tree" and not base_patches:
                try:
                    base_patches = _load_and_apply_base_patches(selftest_root, kernel_root)
                    if base_patches:
                        kernel_state.mark_modified("base", base_patches)
                except Exception as e:
                    print(f"# ERROR: Failed to apply base patches: {e}",
                          flush=True, file=sys.stderr)
                    return 1

            try:
                _build_and_save_kernel(
                    kernel_root, artifacts_root, profile_name, test_type,
                )
            except Exception as e:
                print(f"# Warning: failed to build/save reference kernel: {e}",
                      flush=True, file=sys.stderr)

            kernel_built_for.add(test_type)
            first_build = True

        test_name = test_id.split("/")[-1]
        artifact_dir = os.path.join(artifacts_root, profile_name, test_type, test_name)

        test_kernel_patches = []
        if test_type == "patched-tree":
            mod = load_expected(test_dir)
            gen_kernel = getattr(mod, "generate_kernel_patches", None) if mod else None
            if callable(gen_kernel):
                try:
                    out_path = os.path.join(test_dir, f"{test_name}-kernel.patch")
                    resolved = gen_kernel(test_dir, kernel_root, out_path)
                    test_kernel_patches = resolved if isinstance(resolved, list) else [resolved]
                    print(f"# Generated {len(test_kernel_patches)} test-specific kernel patch(es) for {test_id}", flush=True)
                except Exception as e:
                    print(f"not ok {test_num} - {desc_prefix}{test_id} (generate_kernel_patches: {e})", flush=True)
                    test_num += 1
                    failed += 1
                    continue

                # Copy test-specific kernel patches to artifacts
                _copy_patches_to_artifacts(test_kernel_patches, artifact_dir)

                # Apply test-specific kernel patches on top of base
                print(f"# Applying test-specific kernel patches", flush=True)
                _apply_kernel_patches(kernel_root, test_kernel_patches)
                # Track only test-specific patches (base patches stay applied)
                all_patches = base_patches + test_kernel_patches
                kernel_state.mark_modified(test_name, all_patches)

        # Wrap entire test execution in try/finally to ensure cleanup
        # For patched-tree: ALWAYS revert kernel patches in finally block
        # For current-tree: revert if needed before next test
        print(f"# Starting build: {desc_prefix}{test_id}", flush=True)
        verification_results = []
        try:
            # Generate livepatch patches (for current-tree: before build; for patched-tree: after kernel mods)
            if not patch_paths:
                out_path = os.path.join(test_dir, f"{test_name}-generated.patch")
                mod = load_expected(test_dir)
                gen = getattr(mod, "generate_patches", None) if mod else None
                if callable(gen):
                    try:
                        resolved = gen(test_dir, kernel_root, out_path)
                        patch_paths = resolved if isinstance(resolved, list) else [resolved]
                    except Exception as e:
                        print(f"not ok {test_num} - {desc_prefix}{test_id} (generate_patches: {e})", flush=True)
                        test_num += 1
                        failed += 1
                        continue
                if not patch_paths:
                    print(f"ok {test_num} - {desc_prefix}{test_id} # SKIP (no patch files)", flush=True)
                    test_num += 1
                    skipped += 1
                    continue

            _copy_patches_to_artifacts(patch_paths, artifact_dir)
            # For current-tree: ensure kernel is in clean state
            if test_type == "current-tree" and kernel_state.is_modified:
                print(f"# Reverting kernel patches from {kernel_state.test_name}", flush=True)
                _revert_kernel_patches(kernel_root, kernel_state.applied_patches)
                kernel_state.mark_clean()
                # Must do full rebuild after reverting kernel patches
                first_build = True

            # For patched-tree: All tests share the same base kernel (no test-specific kernel patches)
            # First test does full build, subsequent tests reuse klp-tmp/orig/ with -S 2
            # This optimization works because all patched-tree tests now have their kernel
            # infrastructure in base/kernel-*.patch files, creating a shared golden kernel

            t0 = time.monotonic()
            if first_build:
                out = run_klp_build(kernel_root, patch_paths, keep_tmp=True)
                first_build = False
            else:
                _clear_klp_tmp_downstream(kernel_root)
                out = run_klp_build(kernel_root, patch_paths, keep_tmp=True, short_circuit=2)
            elapsed = time.monotonic() - t0
            run_comment = f" # klp-build exit {out.returncode} in {elapsed:.1f}s"

            dest_ko = None
            if out.ko_path and os.path.isfile(out.ko_path):
                os.makedirs(artifact_dir, exist_ok=True)
                dest_ko = os.path.join(artifact_dir, os.path.basename(out.ko_path))
                shutil.copy2(out.ko_path, dest_ko)
                try:
                    os.unlink(out.ko_path)
                except OSError:
                    pass

            if expect_success:
                if out.returncode != 0:
                    write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose, verification_results=verification_results, expect_success=expect_success)
                    _copy_klp_tmp_to_artifacts(kernel_root, artifact_dir)
                    print(f"not ok {test_num} - {desc_prefix}{test_id} (exit {out.returncode}){run_comment}", flush=True)
                    test_num += 1
                    failed += 1
                    continue
                run_verify(
                    test_dir,
                    returncode=out.returncode,
                    tmp_dir=out.tmp_dir,
                    ko_path=dest_ko or out.ko_path,
                    stdout=out.stdout,
                    stderr=out.stderr,
                    results=verification_results,
                )
                write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose, verification_results=verification_results, expect_success=expect_success)
                _copy_klp_tmp_to_artifacts(kernel_root, artifact_dir)
                print(f"ok {test_num} - {desc_prefix}{test_id}{run_comment}", flush=True)
                test_num += 1
                passed += 1
            else:
                # Fail test: write log before verify so it exists even when verify raises
                write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose, verification_results=verification_results, expect_success=expect_success)
                _copy_klp_tmp_to_artifacts(kernel_root, artifact_dir)
                run_verify(
                    test_dir,
                    returncode=out.returncode,
                    tmp_dir=out.tmp_dir,
                    ko_path=dest_ko or out.ko_path,
                    stdout=out.stdout,
                    stderr=out.stderr,
                    results=verification_results,
                )
                write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose, verification_results=verification_results, expect_success=expect_success)
                _copy_klp_tmp_to_artifacts(kernel_root, artifact_dir)
                verification_failed = any(
                    str(v).startswith("FAILED:") for v in verification_results
                )
                if out.returncode == 0:
                    print(f"not ok {test_num} - {desc_prefix}{test_id} # TODO unexpected pass{run_comment}", flush=True)
                    test_num += 1
                    xpassed += 1
                elif verification_failed:
                    fail_detail = next(
                        (str(v) for v in verification_results if str(v).startswith("FAILED:")),
                        "verification",
                    )
                    print(f"not ok {test_num} - {desc_prefix}{test_id} ({fail_detail}){run_comment}", flush=True)
                    test_num += 1
                    failed += 1
                else:
                    print(f"ok {test_num} - {desc_prefix}{test_id} # TODO expected failure{run_comment}", flush=True)
                    test_num += 1
                    xfailed += 1
        except VerificationError as e:
            verification_results.append(f"FAILED: {e}")
            write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose, verification_results=verification_results, expect_success=expect_success)
            _copy_klp_tmp_to_artifacts(kernel_root, artifact_dir)
            print(f"not ok {test_num} - {desc_prefix}{test_id} ({e})", flush=True)
            test_num += 1
            failed += 1
        except Exception as e:
            try:
                loc = locals()
                vr = loc.get("verification_results")
                if vr is not None:
                    vr.append(f"FAILED: {e}")
                if "out" in loc and "artifact_dir" in loc and "test_id" in loc:
                    write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose, verification_results=vr, expect_success=expect_success)
                    _copy_klp_tmp_to_artifacts(kernel_root, artifact_dir)
            except Exception:
                pass
            print(f"not ok {test_num} - {desc_prefix}{test_id} ({e})", flush=True)
            test_num += 1
            failed += 1
        finally:
            # CRITICAL: Always revert test-specific kernel patches for patched-tree tests
            # This runs even if Ctrl-C, exception, or success
            # Note: Base patches stay applied - they're reverted only at the very end
            if test_type == "patched-tree" and test_kernel_patches:
                if kernel_state.is_modified and kernel_state.test_name == test_name:
                    print(f"# Reverting test-specific kernel patches", flush=True)
                    try:
                        _revert_kernel_patches(kernel_root, test_kernel_patches)
                        # Restore kernel state to base-only (base patches stay applied)
                        if base_patches:
                            kernel_state.mark_modified("base", base_patches)
                        else:
                            kernel_state.mark_clean()
                        # Next test will need full rebuild
                        first_build = True
                    except Exception as e:
                        print(f"# ERROR: failed to revert test-specific kernel patches: {e}", flush=True, file=sys.stderr)
                        # Re-raise to prevent further tests from running with corrupted tree
                        raise RuntimeError(f"Failed to revert kernel patches for {test_name}: {e}")

    print(f"# Totals: pass:{passed} xfail:{xfailed} FAIL:{failed} XPASS:{xpassed} skip:{skipped}", flush=True)

    # Cleanup: revert any remaining test-specific patches and base patches
    if kernel_state.is_modified:
        # If kernel is still modified, we have patches applied (either test-specific or base)
        if kernel_state.test_name != "base":
            # Revert test-specific patches first
            print(f"# Cleanup: reverting test patches from {kernel_state.test_name}", flush=True)
            try:
                _revert_kernel_patches(kernel_root, kernel_state.applied_patches)
                kernel_state.mark_clean()
            except Exception as e:
                print(f"# Warning: failed to revert test patches during cleanup: {e}", flush=True)

    # Always revert base patches if they were applied
    if base_patches:
        print(f"# Cleanup: reverting base patches", flush=True)
        try:
            _revert_kernel_patches(kernel_root, base_patches)
        except Exception as e:
            print(f"# Warning: failed to revert base patches during cleanup: {e}", flush=True)

    # klp-build injects "echo <version>; exit 0" into setlocalversion on
    # each run (-T mode stashes the already-modified file, so repeated runs
    # accumulate extra lines).  Restore the original.
    slv = os.path.join(kernel_root, "scripts", "setlocalversion")
    try:
        subprocess.run(
            ["git", "checkout", slv],
            cwd=kernel_root, capture_output=True, timeout=10,
        )
    except Exception:
        pass

    if passed + xfailed + failed + xpassed == 0:
        return 77
    return 0 if (failed + xpassed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
