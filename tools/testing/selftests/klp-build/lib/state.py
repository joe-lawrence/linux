#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Test state persistence for klp-build tests.

Tracks which tests have passed/failed to enable incremental re-runs.
Previously passed tests are skipped by default; failed tests always re-run.
"""

import json
from pathlib import Path
from typing import Optional
from enum import Enum

from . import get_test_dir

# Constants for build tests compatibility
ARTIFACTS_DIR = "artifacts"
STATE_FILENAME = ".test_state.json"


class TestStatus(Enum):
    """Test execution status."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class TestState:
    """
    Manages test execution state persistence.
    
    Stores test results in a JSON file to enable incremental testing.
    """
    
    def __init__(self, state_file: Optional[Path] = None):
        """
        Initialize test state manager.
        
        Args:
            state_file: Path to state file (default: artifacts/.test_state.json)
        """
        if state_file is None:
            state_file = get_test_dir() / "artifacts" / ".test_state.json"
        
        self.state_file = state_file
        self.state = self._load()
    
    def _load(self) -> dict:
        """Load state from file."""
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # Corrupted or unreadable state file
            return {}
    
    def _save(self) -> None:
        """Save state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def get_status(self, test_name: str) -> Optional[TestStatus]:
        """
        Get the status of a test.
        
        Args:
            test_name: Name of the test
        
        Returns:
            TestStatus if test has been run, None otherwise
        """
        if test_name not in self.state:
            return None
        
        status_str = self.state[test_name].get("status")
        if status_str is None:
            return None
        
        try:
            return TestStatus(status_str)
        except ValueError:
            return None
    
    def set_status(self, test_name: str, status: TestStatus, details: Optional[str] = None) -> None:
        """
        Set the status of a test.
        
        Args:
            test_name: Name of the test
            status: Test status
            details: Optional details (e.g., error message)
        """
        if test_name not in self.state:
            self.state[test_name] = {}
        
        self.state[test_name]["status"] = status.value
        
        if details:
            self.state[test_name]["details"] = details
        
        self._save()
    
    def mark_passed(self, test_name: str) -> None:
        """Mark a test as passed."""
        self.set_status(test_name, TestStatus.PASSED)
    
    def mark_failed(self, test_name: str, error: Optional[str] = None) -> None:
        """Mark a test as failed."""
        self.set_status(test_name, TestStatus.FAILED, error)
    
    def mark_skipped(self, test_name: str, reason: Optional[str] = None) -> None:
        """Mark a test as skipped."""
        self.set_status(test_name, TestStatus.SKIPPED, reason)
    
    def mark_error(self, test_name: str, error: Optional[str] = None) -> None:
        """Mark a test as errored (setup/infrastructure failure)."""
        self.set_status(test_name, TestStatus.ERROR, error)
    
    def record_dependencies(self, test_name: str, test_case_dir: Path) -> None:
        """
        Record dependency mtimes for a test.
        
        Args:
            test_name: Name of the test
            test_case_dir: Path to test case directory
        """
        if test_name not in self.state:
            self.state[test_name] = {}
        
        deps = {}
        
        # Check for test source files
        for filename in ["patch.patch", "generate.sh", "expected.py"]:
            filepath = test_case_dir / filename
            if filepath.exists():
                deps[filename] = filepath.stat().st_mtime
        
        self.state[test_name]["dependencies"] = deps
        self._save()
    
    def have_dependencies_changed(self, test_name: str, test_case_dir: Path) -> bool:
        """
        Check if test dependencies have changed since last run.
        
        Args:
            test_name: Name of the test
            test_case_dir: Path to test case directory
        
        Returns:
            True if dependencies changed or no dependency info stored
        """
        if test_name not in self.state:
            return True
        
        stored_deps = self.state[test_name].get("dependencies")
        if not stored_deps:
            # No dependency info - treat as changed
            return True
        
        # Check each stored dependency
        for filename, stored_mtime in stored_deps.items():
            filepath = test_case_dir / filename
            
            # File was deleted
            if not filepath.exists():
                return True
            
            # File was modified
            current_mtime = filepath.stat().st_mtime
            if current_mtime != stored_mtime:
                return True
        
        # Check if new files were added
        for filename in ["patch.patch", "generate.sh", "expected.py"]:
            filepath = test_case_dir / filename
            if filepath.exists() and filename not in stored_deps:
                return True
        
        return False
    
    def should_run(self, test_name: str, force: bool = False, test_case_dir: Path = None) -> bool:
        """
        Determine if a test should be run.
        
        Args:
            test_name: Name of the test
            force: If True, run even if previously passed
            test_case_dir: Path to test case directory (for dependency checking)
        
        Returns:
            True if test should be run
        """
        if force:
            return True
        
        status = self.get_status(test_name)
        
        # Always re-run failed and errored tests
        if status in [TestStatus.FAILED, TestStatus.ERROR, None]:
            return True
        
        # Check if dependencies changed
        if test_case_dir and self.have_dependencies_changed(test_name, test_case_dir):
            return True
        
        # Skip previously passed tests
        return False
    
    def clear(self, test_name: Optional[str] = None) -> None:
        """
        Clear test state.
        
        Args:
            test_name: Name of specific test to clear, or None to clear all
        """
        if test_name is None:
            self.state = {}
        else:
            self.state.pop(test_name, None)
        
        self._save()
    
    def get_summary(self) -> dict[str, int]:
        """
        Get a summary of test results.
        
        Returns:
            Dictionary with counts for each status
        """
        summary = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
        }
        
        for test_data in self.state.values():
            status = test_data.get("status")
            if status in summary:
                summary[status] += 1
        
        return summary
    
    def get_failed_tests(self) -> list[str]:
        """
        Get list of failed test names.
        
        Returns:
            List of test names that failed
        """
        failed = []
        for test_name, test_data in self.state.items():
            if test_data.get("status") == TestStatus.FAILED.value:
                failed.append(test_name)
        
        return sorted(failed)
    
    # Runtime test state methods
    def get_runtime_status(self, test_name: str) -> Optional[TestStatus]:
        """Get runtime test status (stored in 'runtime_status' field)."""
        if test_name not in self.state:
            return None
        
        status_str = self.state[test_name].get("runtime_status")
        if status_str is None:
            return None
        
        try:
            return TestStatus(status_str)
        except ValueError:
            return None
    
    def set_runtime_status(self, test_name: str, status: TestStatus, details: Optional[str] = None) -> None:
        """Set runtime test status (separate from build status)."""
        if test_name not in self.state:
            self.state[test_name] = {}
        
        self.state[test_name]["runtime_status"] = status.value
        
        if details:
            self.state[test_name]["runtime_details"] = details
        
        self._save()
    
    def mark_runtime_passed(self, test_name: str) -> None:
        """Mark a runtime test as passed."""
        self.set_runtime_status(test_name, TestStatus.PASSED)
    
    def mark_runtime_failed(self, test_name: str, error: Optional[str] = None) -> None:
        """Mark a runtime test as failed."""
        self.set_runtime_status(test_name, TestStatus.FAILED, error)
    
    def mark_runtime_error(self, test_name: str, error: Optional[str] = None) -> None:
        """Mark a runtime test as errored."""
        self.set_runtime_status(test_name, TestStatus.ERROR, error)
    
    def record_runtime_dependencies(self, test_name: str, test_case_dir: Path, ko_file: Path) -> None:
        """
        Record runtime dependency mtimes for a test.
        
        Args:
            test_name: Name of the test
            test_case_dir: Path to test case directory
            ko_file: Path to .ko artifact
        """
        if test_name not in self.state:
            self.state[test_name] = {}
        
        deps = {}
        
        # Record expected.py (for verify_runtime function)
        expected_py = test_case_dir / "expected.py"
        if expected_py.exists():
            deps["expected.py"] = expected_py.stat().st_mtime
        
        # Record .ko artifact
        if ko_file.exists():
            deps[ko_file.name] = ko_file.stat().st_mtime
        
        self.state[test_name]["runtime_dependencies"] = deps
        self._save()
    
    def have_runtime_dependencies_changed(self, test_name: str, test_case_dir: Path, ko_file: Path) -> bool:
        """
        Check if runtime test dependencies have changed since last run.
        
        Args:
            test_name: Name of the test
            test_case_dir: Path to test case directory
            ko_file: Path to .ko artifact
        
        Returns:
            True if dependencies changed or no dependency info stored
        """
        if test_name not in self.state:
            return True
        
        stored_deps = self.state[test_name].get("runtime_dependencies")
        if not stored_deps:
            # No dependency info - treat as changed
            return True
        
        # Check expected.py
        expected_py = test_case_dir / "expected.py"
        if expected_py.exists():
            stored_mtime = stored_deps.get("expected.py")
            if not stored_mtime or expected_py.stat().st_mtime != stored_mtime:
                return True
        
        # Check .ko artifact
        if ko_file.exists():
            stored_mtime = stored_deps.get(ko_file.name)
            if not stored_mtime or ko_file.stat().st_mtime != stored_mtime:
                return True
        else:
            # .ko was deleted
            return True
        
        return False
    
    def should_run_runtime(self, test_name: str, force: bool = False, test_case_dir: Path = None, ko_file: Path = None) -> bool:
        """
        Determine if a runtime test should be run.
        
        Args:
            test_name: Name of the test
            force: If True, run even if previously passed
            test_case_dir: Path to test case directory (for dependency checking)
            ko_file: Path to .ko artifact (for dependency checking)
        
        Returns:
            True if test should be run
        """
        if force:
            return True
        
        status = self.get_runtime_status(test_name)
        
        # Always re-run failed and errored tests
        if status in [TestStatus.FAILED, TestStatus.ERROR, None]:
            return True
        
        # Check if runtime dependencies changed
        if test_case_dir and ko_file and self.have_runtime_dependencies_changed(test_name, test_case_dir, ko_file):
            return True
        
        # Skip previously passed tests
        return False
    
    def clear_runtime(self) -> None:
        """Clear all runtime test state."""
        for test_name in list(self.state.keys()):
            if test_name in self.state:
                self.state[test_name].pop("runtime_status", None)
                self.state[test_name].pop("runtime_details", None)
                # Remove entry if empty
                if not self.state[test_name]:
                    self.state.pop(test_name)
        
        self._save()


class RuntimeTestState(TestState):
    """
    Manages runtime test state (separate from build test state).
    
    Runtime tests can fail independently of build tests, so we track
    them separately.
    """
    
    def __init__(self, state_file: Optional[Path] = None):
        """
        Initialize runtime test state manager.
        
        Args:
            state_file: Path to state file (default: artifacts/.runtime_state.json)
        """
        if state_file is None:
            state_file = get_test_dir() / "artifacts" / ".runtime_state.json"
        
        super().__init__(state_file)
