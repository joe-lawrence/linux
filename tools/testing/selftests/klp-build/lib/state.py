#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Shared constants and types for klp-build tests.
"""

from enum import Enum

# Used by run_build_tests.py and apply_profile.py for artifacts path
ARTIFACTS_DIR = "artifacts"


class TestStatus(Enum):
    """Test execution status (e.g. for TAP output)."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
