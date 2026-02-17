#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Core library for klp-build test suite.

Provides common utilities, data structures, and helpers used across
the test framework.
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# Test suite paths
def get_test_dir() -> Path:
    """Get the root directory of the klp-build test suite."""
    return Path(__file__).parent.parent.resolve()


def get_kernel_src_dir() -> Path:
    """Get the kernel source directory (repo root)."""
    test_dir = get_test_dir()
    # tools/testing/selftests/klp-build -> repo root is 4 levels up
    return test_dir.parent.parent.parent.parent.resolve()


def get_tests_dir() -> Path:
    """Get the tests directory."""
    return get_test_dir() / "tests"


def get_artifacts_dir() -> Path:
    """Get the artifacts directory."""
    return get_test_dir() / "artifacts"


def get_klp_tmp_dir() -> Path:
    """Get the default klp-tmp directory."""
    return get_kernel_src_dir() / "klp-tmp"


# Common data structures
@dataclass
class KlpBuildResult:
    """
    Result of a klp-build execution.
    
    Attributes:
        test_name: Name of the test case
        ko_file: Path to the output .ko file (may not exist if build failed)
        tmp_dir: Path to the klp-tmp directory
        stdout: Captured stdout from klp-build
        stderr: Captured stderr from klp-build
        exit_code: Process exit code
        patches: List of patch files that were applied
    """
    test_name: str
    ko_file: Path
    tmp_dir: Path
    stdout: str
    stderr: str
    exit_code: int
    patches: list[Path]
    
    @property
    def success(self) -> bool:
        """True if klp-build exited successfully."""
        return self.exit_code == 0
    
    @property
    def diff_log(self) -> Optional[Path]:
        """Path to diff.log if it exists."""
        log_path = self.tmp_dir / "diff" / "diff.log"
        return log_path if log_path.exists() else None


# Exceptions
class KlpBuildTestError(Exception):
    """Base exception for klp-build test errors."""
    pass


class KlpBuildError(KlpBuildTestError):
    """klp-build execution failed unexpectedly."""
    pass


class VerificationError(KlpBuildTestError):
    """Test verification failed."""
    pass


class TestSetupError(KlpBuildTestError):
    """Test setup/configuration error."""
    pass


# Utilities
def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_test_cases(category: str, speed: Optional[str] = None) -> list[Path]:
    """
    Find all test case directories in a category (pass/fail).
    
    Args:
        category: "pass" or "fail"
        speed: Optional filter: "quick" or "long". If None, find all.
    
    Returns:
        List of test case directory paths, sorted by name
    """
    tests_dir = get_tests_dir()
    category_dir = tests_dir / category
    
    if not category_dir.exists():
        return []
    
    test_cases = []
    
    if speed:
        # Search in specific speed category
        speed_dir = category_dir / speed
        if speed_dir.exists():
            for item in speed_dir.iterdir():
                if item.is_dir() and (item / "expected.py").exists():
                    test_cases.append(item)
    else:
        # Search all speed categories (quick and long)
        for speed_cat in ["quick", "long"]:
            speed_dir = category_dir / speed_cat
            if speed_dir.exists():
                for item in speed_dir.iterdir():
                    if item.is_dir() and (item / "expected.py").exists():
                        test_cases.append(item)
    
    return sorted(test_cases)


def find_matching_tests(pattern: str) -> list[Path]:
    """
    Find tests matching a name pattern (substring match).
    
    Args:
        pattern: Test name or pattern to match (e.g., "add-file-diff" or "pass/long/add-file-diff")
    
    Returns:
        List of matching test case directory paths
    """
    # Get all tests from both categories
    all_tests = []
    all_tests.extend(find_test_cases("pass"))
    all_tests.extend(find_test_cases("fail"))
    
    matches = []
    for test_path in all_tests:
        test_name = get_test_name(test_path)  # e.g., "pass/long/add-file-diff"
        # Match if pattern is substring of full name or just the test directory name
        if pattern in test_name or pattern == test_path.name:
            matches.append(test_path)
    
    return matches


def get_current_compiler() -> str:
    """
    Detect which compiler is being used.
    
    Returns:
        "gcc", "clang", or "unknown"
    """
    import subprocess
    
    # Check environment variables (kernel build conventions)
    if os.environ.get("LLVM") == "1":
        return "clang"
    
    cc = os.environ.get("CC", "gcc")
    if "clang" in cc.lower():
        return "clang"
    elif "gcc" in cc.lower() or cc == "cc":
        return "gcc"
    
    # Fallback: check what CC actually is
    try:
        result = subprocess.run(
            [cc, "--version"],
            capture_output=True,
            text=True,
            timeout=2
        )
        output = result.stdout.lower()
        if "clang" in output:
            return "clang"
        elif "gcc" in output or "gnu" in output:
            return "gcc"
    except:
        pass
    
    return "unknown"


def should_skip_test(test_case_dir: Path) -> tuple[bool, str]:
    """
    Check if test should be skipped based on current environment.
    
    If SUPPORTED_ARCHES or SUPPORTED_COMPILERS are not defined in expected.py,
    the test runs without restriction.
    
    Returns:
        (should_skip, reason_if_skipped)
    """
    import platform
    
    expected = load_expected_module(test_case_dir)
    
    # Check architecture restriction
    if hasattr(expected, "SUPPORTED_ARCHES"):
        current_arch = platform.machine()
        if current_arch not in expected.SUPPORTED_ARCHES:
            return (True, f"arch {current_arch} not supported")
    
    # Check compiler restriction  
    if hasattr(expected, "SUPPORTED_COMPILERS"):
        current_compiler = get_current_compiler()
        if current_compiler not in expected.SUPPORTED_COMPILERS:
            return (True, f"compiler {current_compiler} not supported")
    
    return (False, "")


def should_run_runtime_test(test_case_dir: Path) -> tuple[bool, str]:
    """
    Check if test requires runtime verification.
    
    Returns:
        (should_run, warning_message_if_any)
    """
    expected = load_expected_module(test_case_dir)
    
    has_verify_runtime = hasattr(expected, "verify_runtime")
    runtime_required = getattr(expected, "RUNTIME_REQUIRED", has_verify_runtime)
    
    # Warn if verify_runtime() exists but RUNTIME_REQUIRED = False
    if has_verify_runtime and hasattr(expected, "RUNTIME_REQUIRED") and not runtime_required:
        return (False, "verify_runtime() defined but RUNTIME_REQUIRED = False")
    
    return (runtime_required and has_verify_runtime, "")


def load_expected_module(test_case_dir: Path):
    """
    Load the expected.py module for a test case.
    
    Args:
        test_case_dir: Path to the test case directory
    
    Returns:
        The loaded module object
    
    Raises:
        TestSetupError: If expected.py cannot be loaded
    """
    expected_file = test_case_dir / "expected.py"
    if not expected_file.exists():
        raise TestSetupError(f"Test case missing expected.py: {test_case_dir.name}")
    
    # Load the module
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"expected_{test_case_dir.name}",
        expected_file
    )
    if spec is None or spec.loader is None:
        raise TestSetupError(f"Failed to load expected.py: {expected_file}")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    return module


def get_test_name(test_case_dir: Path) -> str:
    """
    Get the canonical test name from a test case directory.
    
    The test name includes speed category: "pass/quick/cmdline-string"
    """
    tests_dir = get_tests_dir()
    try:
        relative = test_case_dir.relative_to(tests_dir)
        return str(relative)
    except ValueError:
        # Not relative to tests dir, just use the basename
        return test_case_dir.name


# Color output helpers
def supports_color() -> bool:
    """Check if terminal supports color output."""
    if not hasattr(sys.stdout, 'isatty'):
        return False
    if not sys.stdout.isatty():
        return False
    if os.environ.get('TERM') == 'dumb':
        return False
    return True


class Colors:
    """ANSI color codes for terminal output."""
    
    def __init__(self):
        self.enabled = supports_color()
    
    def __getattr__(self, name: str) -> str:
        """Return empty string if colors disabled."""
        if not self.enabled:
            return ""
        
        colors = {
            'reset': '\033[0m',
            'bold': '\033[1m',
            'red': '\033[31m',
            'green': '\033[32m',
            'yellow': '\033[33m',
            'blue': '\033[34m',
            'cyan': '\033[36m',
        }
        return colors.get(name, "")


# Global color instance
colors = Colors()
