# SPDX-License-Identifier: GPL-2.0
"""Discover tests under tests/ and get requirement attributes from expected.py."""

import glob
import os

from .verification import load_expected, get_expect_success
from .requirements import (
    CONFIG_PROFILES,
    REQUIRED_CONFIG,
    SUPPORTED_COMPILERS,
    SUPPORTED_ARCHES,
)


def discover_tests(selftest_root: str) -> list:
    """
    Return list of (test_type, test_id, test_dir, patch_paths, expect_success).
    test_type is current-tree or patched-tree.
    test_id is outcome/speed/name (e.g. pass/quick/cmdline-string).
    patch_paths is all *.patch in test_dir in alphanumeric order, or [] if
    the test has generate_patches in expected.py (caller must resolve before run).
    """
    tests_dir = os.path.join(selftest_root, "tests")
    tests = []
    for test_type in ("current-tree", "patched-tree"):
        type_dir = os.path.join(tests_dir, test_type)
        if not os.path.isdir(type_dir):
            continue
        for outcome in ("pass", "fail"):
            outcome_dir = os.path.join(type_dir, outcome)
            if not os.path.isdir(outcome_dir):
                continue
            # For current-tree, look in quick/long subdirs
            # For patched-tree, tests are directly under pass/fail
            if test_type == "current-tree":
                speed_dirs = [("quick", os.path.join(outcome_dir, "quick")),
                              ("long", os.path.join(outcome_dir, "long"))]
            else:
                speed_dirs = [("", outcome_dir)]

            for speed_label, speed_dir in speed_dirs:
                if not os.path.isdir(speed_dir):
                    continue
                for name in sorted(os.listdir(speed_dir)):
                    # Skip base/ directory (patched-tree infrastructure, not a test)
                    if test_type == "patched-tree" and name == "base":
                        continue
                    test_dir = os.path.join(speed_dir, name)
                    if not os.path.isdir(test_dir):
                        continue
                    pattern = os.path.join(test_dir, "*.patch")
                    patch_files = sorted(glob.glob(pattern))
                    has_expected = os.path.isfile(os.path.join(test_dir, "expected.py"))
                    if has_expected:
                        mod = load_expected(test_dir)
                        if getattr(mod, "generate_patches", None):
                            patch_files = []  # always (re)generate; caller resolves
                        elif not patch_files:
                            continue
                    else:
                        if not patch_files:
                            continue
                    # Build test_id with speed if current-tree
                    if speed_label:
                        test_id = f"{outcome}/{speed_label}/{name}"
                    else:
                        test_id = f"{outcome}/{name}"
                    expect_ok = get_expect_success(test_dir)
                    tests.append((test_type, test_id, test_dir, patch_files, expect_ok))
    return tests


def get_expected_attrs(test_dir: str) -> dict:
    """Dict of CONFIG_PROFILES, REQUIRED_CONFIG, etc. from expected.py."""
    mod = load_expected(test_dir)
    if mod is None:
        return {}
    return {
        CONFIG_PROFILES: getattr(mod, CONFIG_PROFILES, None),
        REQUIRED_CONFIG: getattr(mod, REQUIRED_CONFIG, None),
        SUPPORTED_COMPILERS: getattr(mod, SUPPORTED_COMPILERS, None),
        SUPPORTED_ARCHES: getattr(mod, SUPPORTED_ARCHES, None),
    }
