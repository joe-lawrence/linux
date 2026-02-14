# SPDX-License-Identifier: GPL-2.0
"""Load expected.py and verify test outcome."""

import importlib.util
import os
import sys

# Test expects build to succeed (pass) or fail (fail).
EXPECT_SUCCESS = "expect_success"


def load_expected(test_dir: str):
    """Load expected.py from test directory. Returns module or None."""
    path = os.path.join(test_dir, "expected.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("expected", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["expected"] = mod
    spec.loader.exec_module(mod)
    return mod


def get_expect_success(test_dir: str) -> bool:
    """True if test expects build to succeed (pass test)."""
    mod = load_expected(test_dir)
    if mod is None:
        return True
    return getattr(mod, EXPECT_SUCCESS, getattr(mod, "EXPECT_SUCCESS", True))
