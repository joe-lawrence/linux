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
import sys
import time
from typing import Optional

# Allow importing from lib when script is run from repo root or selftest dir.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_SCRIPT_DIR, "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from test_discovery import discover_tests, get_expected_attrs
from requirements import test_belongs_to_profile, config_has_symbol
from klp_build import run_klp_build
from verification import load_expected, run_verify, VerificationError
from build_log import write_build_log
from state import ARTIFACTS_DIR


# Subdirs of klp-tmp that are rewritten by steps 2-4; clear before -S 2 to avoid residual logs.
_KLP_TMP_DOWNSTREAM = ("patched", "diff", "kmod")


def _clear_klp_tmp_downstream(kernel_root: str) -> None:
    """Remove patched/diff/kmod under klp-tmp so the next -S 2 run has no residual logs."""
    tmp_dir = os.path.join(kernel_root, "klp-tmp")
    for name in _KLP_TMP_DOWNSTREAM:
        path = os.path.join(tmp_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


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


def main():
    parser = argparse.ArgumentParser(description="Run klp-build tests for current .config")
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="Profile or chain (e.g. full-default+overlay-thin-lto); sets toolchain to match",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only quick tests (pass/quick and fail/quick)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include klp-tmp logs (diff.log, orig/patched/kmod build.log) in build-test.log",
    )
    args = parser.parse_args()

    selftest_root = _SCRIPT_DIR
    kernel_root = os.path.abspath(os.path.join(selftest_root, "..", "..", "..", ".."))
    config_path = os.path.join(kernel_root, ".config")
    artifacts_root = os.path.join(selftest_root, ARTIFACTS_DIR)

    profile_name = _resolve_profile(artifacts_root, config_path, args.profile)
    _ensure_profile_artifact_dir(artifacts_root, profile_name, config_path)

    if args.profile:
        from profile import apply_toolchain_for_profile
        apply_toolchain_for_profile(args.profile)
        profile_compiler = None  # use current env (we just set it)
    else:
        # Match build toolchain to .config so make does not prompt (e.g. LLVM=1).
        set_toolchain_env_from_config(config_path)
        profile_compiler = None

    tests = discover_tests(selftest_root)
    if args.quick:
        tests = [(tid, tdir, patches, exp) for tid, tdir, patches, exp in tests if tid.split("/")[1] == "quick"]
    if not tests:
        print("TAP version 13", flush=True)
        print("1..0 # no tests found", flush=True)
        return 77

    print("TAP version 13", flush=True)
    print(f"1..{len(tests)}", flush=True)

    passed = 0
    skipped = 0
    failed = 0
    first_build = True
    test_num = 1
    desc_prefix = f"{profile_name} :: "

    for test_id, test_dir, patch_paths, expect_success in tests:
        attrs = get_expected_attrs(test_dir)
        if not test_belongs_to_profile(attrs, profile_name, config_path, profile_compiler):
            print(f"ok {test_num} - {desc_prefix}{test_id} # SKIP", flush=True)
            test_num += 1
            skipped += 1
            continue

        if not patch_paths:
            test_name = test_id.split("/")[-1]
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

        print(f"# Starting build: {desc_prefix}{test_id}", flush=True)
        test_name = test_id.split("/")[-1]
        artifact_dir = os.path.join(artifacts_root, profile_name, test_name)
        try:
            t0 = time.monotonic()
            if first_build:
                out = run_klp_build(kernel_root, patch_paths, keep_tmp=True)
                first_build = False
            else:
                _clear_klp_tmp_downstream(kernel_root)
                out = run_klp_build(kernel_root, patch_paths, keep_tmp=True, short_circuit=2)
            elapsed = time.monotonic() - t0
            run_comment = f" # klp-build exit {out.returncode} in {elapsed:.1f}s"

            write_build_log(out, test_id, artifact_dir, kernel_root, patch_paths, verbose=args.verbose)

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
                )
                print(f"ok {test_num} - {desc_prefix}{test_id}{run_comment}", flush=True)
                test_num += 1
                passed += 1
            else:
                # Fail test: expect non-zero exit; optional expected.verify()
                run_verify(
                    test_dir,
                    returncode=out.returncode,
                    tmp_dir=out.tmp_dir,
                    ko_path=dest_ko or out.ko_path,
                    stdout=out.stdout,
                    stderr=out.stderr,
                )
                if out.returncode == 0:
                    print(f"not ok {test_num} - {desc_prefix}{test_id} (expected non-zero exit){run_comment}", flush=True)
                    test_num += 1
                    failed += 1
                else:
                    print(f"ok {test_num} - {desc_prefix}{test_id}{run_comment}", flush=True)
                    test_num += 1
                    passed += 1
        except VerificationError as e:
            print(f"not ok {test_num} - {desc_prefix}{test_id} ({e})", flush=True)
            test_num += 1
            failed += 1
        except Exception as e:
            print(f"not ok {test_num} - {desc_prefix}{test_id} ({e})", flush=True)
            test_num += 1
            failed += 1

    print(f"# Totals: pass:{passed} fail:{failed} skip:{skipped}", flush=True)
    if passed + failed == 0:
        return 77
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
