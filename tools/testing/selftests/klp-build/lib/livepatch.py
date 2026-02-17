#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Runtime livepatch operations for testing."""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional


class LivepatchError(Exception):
    """Base exception for livepatch operations."""
    pass


class DmesgCapture:
    """
    Context manager for capturing kernel messages during test execution.
    
    Usage:
        with DmesgCapture() as dmesg:
            # Do something that generates kernel messages
            messages = dmesg.get_messages()  # Can be called while still in context
    """
    
    def __init__(self):
        self.start_marker = None
        self.messages = []
        self.overflowed = False
    
    def __enter__(self):
        """Mark the current dmesg position."""
        # Get current dmesg (with timestamps) to filter later
        result = subprocess.run(
            ["dmesg", "-T"],
            capture_output=True,
            text=True,
            check=True
        )
        # Count lines to know where we start
        self.start_marker = len(result.stdout.splitlines())
        return self
    
    def _capture_current(self):
        """Capture messages from start_marker to now (with human-readable timestamps)."""
        try:
            result = subprocess.run(
                ["dmesg", "-T"],
                capture_output=True,
                text=True,
                check=True
            )
            all_lines = result.stdout.splitlines()
            
            # Check if dmesg overflowed (messages were lost)
            # This can happen if start_marker is now beyond current buffer size
            if self.start_marker is not None and self.start_marker > len(all_lines):
                self.overflowed = True
                self.messages = []
            elif self.start_marker is not None and self.start_marker < len(all_lines):
                self.messages = all_lines[self.start_marker:]
            else:
                self.messages = []
        except Exception:
            self.messages = []
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Capture messages since entry."""
        self._capture_current()
        return False
    
    def get_messages(self, filters: Optional[list[str]] = None) -> list[str]:
        """
        Get captured kernel messages, optionally filtered.
        
        This method captures current dmesg state on each call, so it can
        be called multiple times during the context to get updated messages.
        
        Args:
            filters: Optional list of strings - only return lines containing any filter
            
        Returns:
            List of message lines
        """
        # Refresh messages on each call
        self._capture_current()
        
        if not filters:
            return self.messages
        
        filtered = []
        for msg in self.messages:
            if any(f in msg for f in filters):
                filtered.append(msg)
        return filtered
    
    def has_call_trace(self) -> bool:
        """
        Check if any captured messages contain a kernel call trace.
        
        Returns:
            True if "Call Trace:" is found in messages
        """
        self._capture_current()
        return any("Call Trace:" in msg for msg in self.messages)
    
    def get_full_log(self) -> str:
        """
        Get all captured messages as a single string.
        
        Returns:
            All messages joined with newlines
        """
        self._capture_current()
        return "\n".join(self.messages)
    
    def did_overflow(self) -> bool:
        """
        Check if dmesg buffer overflowed during capture.
        
        Returns:
            True if overflow was detected
        """
        self._capture_current()
        return self.overflowed


class RuntimeContext:
    """
    Context object passed to verify_runtime() functions.
    
    Provides access to:
    - ko_file: Path to the loaded .ko file
    - mod_name: Loaded module name
    - dmesg: DmesgCapture for message verification
    - Helper methods for triggering and reading kernel state
    """
    
    def __init__(self, ko_file: Path, mod_name: str, dmesg: DmesgCapture):
        self.ko_file = ko_file
        self.mod_name = mod_name
        self.dmesg = dmesg
    
    def read_sysfs(self, path: str) -> str:
        """
        Read a sysfs/procfs file.
        
        Args:
            path: Filesystem path to read
            
        Returns:
            File contents as string
        """
        return Path(path).read_text()
    
    def write_sysfs(self, path: str, content: str) -> None:
        """
        Write to a sysfs/procfs file.
        
        Args:
            path: Filesystem path to write
            content: Content to write
        """
        Path(path).write_text(content)
    
    def read_file(self, path: str) -> str:
        """Read a file (alias for read_sysfs for clarity)."""
        return self.read_sysfs(path)
    
    def write_file(self, path: str, content: str) -> None:
        """Write a file (alias for write_sysfs for clarity)."""
        self.write_sysfs(path, content)
    
    def run_command(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """
        Run a command and return the result.
        
        Args:
            cmd: Command and arguments as list
            
        Returns:
            CompletedProcess object
        """
        return subprocess.run(cmd, capture_output=True, text=True, check=True)


def load_module(ko_file: Path) -> str:
    """
    Load a kernel module using insmod.
    
    Args:
        ko_file: Path to the .ko file
        
    Returns:
        Module name (kernel format with underscores, not filename format)
        
    Raises:
        LivepatchError: If module loading fails
    """
    if not ko_file.exists():
        raise LivepatchError(f"Module not found: {ko_file}")
    
    # Module name is the filename without .ko extension
    # Kernel converts dashes to underscores in module names
    mod_name = ko_file.stem.replace('-', '_')
    
    try:
        subprocess.run(
            ["insmod", str(ko_file)],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        raise LivepatchError(
            f"Failed to load module {mod_name}: {e.stderr}"
        ) from e
    
    return mod_name


def unload_module(mod_name: str) -> None:
    """
    Unload a kernel module using rmmod.
    
    Args:
        mod_name: Module name to unload
        
    Raises:
        LivepatchError: If module unloading fails
    """
    # Wait for module reference count to reach 0
    refcnt_path = Path(f"/sys/module/{mod_name}/refcnt")
    if refcnt_path.exists():
        start_time = time.time()
        while time.time() - start_time < 10:  # 10 second timeout
            try:
                refcnt = int(refcnt_path.read_text().strip())
                if refcnt == 0:
                    break
            except Exception:
                pass
            time.sleep(0.1)
    
    try:
        subprocess.run(
            ["rmmod", mod_name],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        raise LivepatchError(
            f"Failed to unload module {mod_name}: {e.stderr}"
        ) from e
    
    # Wait for /sys/module entry to disappear
    module_path = Path(f"/sys/module/{mod_name}")
    start_time = time.time()
    while time.time() - start_time < 10:  # 10 second timeout
        if not module_path.exists():
            return
        time.sleep(0.1)
    
    raise LivepatchError(
        f"Module {mod_name} sysfs entry still exists after rmmod"
    )


def is_module_loaded(mod_name: str) -> bool:
    """
    Check if a module is currently loaded.
    
    Args:
        mod_name: Module name to check
        
    Returns:
        True if module is loaded
    """
    try:
        result = subprocess.run(
            ["lsmod"],
            capture_output=True,
            text=True,
            check=True
        )
        return mod_name in result.stdout
    except Exception:
        return False


def enable_livepatch(mod_name: str) -> None:
    """
    Enable a livepatch module.
    
    Args:
        mod_name: Module name to enable
        
    Raises:
        LivepatchError: If enabling fails
    """
    enable_path = f"/sys/kernel/livepatch/{mod_name}/enabled"
    
    if not Path(enable_path).exists():
        raise LivepatchError(f"Livepatch sysfs not found: {enable_path}")
    
    try:
        Path(enable_path).write_text("1\n")
    except Exception as e:
        raise LivepatchError(f"Failed to enable livepatch {mod_name}: {e}") from e


def disable_livepatch(mod_name: str) -> None:
    """
    Disable a livepatch module.
    
    Args:
        mod_name: Module name to disable
        
    Raises:
        LivepatchError: If disabling fails
    """
    enable_path = f"/sys/kernel/livepatch/{mod_name}/enabled"
    
    if not Path(enable_path).exists():
        raise LivepatchError(f"Livepatch sysfs not found: {enable_path}")
    
    try:
        Path(enable_path).write_text("0\n")
    except Exception as e:
        raise LivepatchError(f"Failed to disable livepatch {mod_name}: {e}") from e
    
    # Wait for the sysfs entry to disappear (transition completes automatically)
    sysfs_path = Path(f"/sys/kernel/livepatch/{mod_name}")
    start_time = time.time()
    while time.time() - start_time < 60:  # 60 second timeout
        if not sysfs_path.exists():
            return
        time.sleep(0.1)
    
    raise LivepatchError(
        f"Livepatch disable timed out for {mod_name} (sysfs entry still exists)"
    )


def wait_for_transition(mod_name: str, timeout: int = 300) -> None:
    """
    Wait for livepatch transition to complete.
    
    Args:
        mod_name: Module name to wait for
        timeout: Maximum time to wait in seconds (default: 300 = 5 minutes)
        
    Raises:
        LivepatchError: If transition doesn't complete within timeout
    """
    transition_path = f"/sys/kernel/livepatch/{mod_name}/transition"
    
    if not Path(transition_path).exists():
        raise LivepatchError(f"Livepatch sysfs not found: {transition_path}")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            status = Path(transition_path).read_text().strip()
            if status == "0":
                return  # Transition complete
        except Exception:
            pass
        time.sleep(0.1)
    
    raise LivepatchError(
        f"Livepatch transition timed out after {timeout}s for {mod_name}"
    )


def get_livepatch_state(mod_name: str) -> dict:
    """
    Get the current state of a livepatch module.
    
    Args:
        mod_name: Module name to query
        
    Returns:
        Dictionary with state information:
        - enabled: bool
        - transition: bool (True if transitioning)
        
    Raises:
        LivepatchError: If module is not a livepatch or sysfs not accessible
    """
    base_path = Path(f"/sys/kernel/livepatch/{mod_name}")
    
    if not base_path.exists():
        raise LivepatchError(f"Livepatch sysfs not found: {base_path}")
    
    try:
        enabled = (base_path / "enabled").read_text().strip() == "1"
        transition = (base_path / "transition").read_text().strip() == "1"
        
        return {
            "enabled": enabled,
            "transition": transition,
        }
    except Exception as e:
        raise LivepatchError(f"Failed to read livepatch state: {e}") from e


def check_root() -> None:
    """
    Check if running as root.
    
    Raises:
        LivepatchError: If not running as root
    """
    if os.geteuid() != 0:
        raise LivepatchError("Runtime tests require root privileges")


def check_kernel_match(kernel_src: Path) -> tuple[bool, str]:
    """
    Check if the running kernel matches the source tree.
    
    Args:
        kernel_src: Path to kernel source directory
        
    Returns:
        Tuple of (matches: bool, message: str)
    """
    try:
        # Get running kernel version
        with open("/proc/version", "r") as f:
            running_version = f.read().strip()
        
        # Get built kernel version from source tree
        result = subprocess.run(
            ["make", "-s", "kernelrelease"],
            cwd=kernel_src,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return False, "Failed to determine built kernel version"
        
        built_version = result.stdout.strip()
        
        # Simple check: running version should contain built version
        if built_version in running_version:
            return True, f"Kernel version matches: {built_version}"
        else:
            return False, (
                f"Kernel mismatch:\n"
                f"  Running: {running_version}\n"
                f"  Built:   {built_version}"
            )
    except Exception as e:
        return False, f"Failed to check kernel version: {e}"


def check_clean_environment() -> tuple[bool, str]:
    """
    Check for a clean test environment (no test livepatches or modules loaded).
    
    Returns:
        Tuple of (is_clean: bool, message: str)
    """
    issues = []
    
    try:
        # Check for loaded livepatch modules
        livepatch_path = Path("/sys/kernel/livepatch")
        if livepatch_path.exists():
            livepatches = [d.name for d in livepatch_path.iterdir() if d.is_dir()]
            if livepatches:
                issues.append(f"Livepatches already loaded: {', '.join(livepatches)}")
        
        # Check for test-related modules
        result = subprocess.run(
            ["lsmod"],
            capture_output=True,
            text=True,
            check=True
        )
        
        test_modules = []
        for line in result.stdout.splitlines():
            # Look for livepatch-* or klp-* modules
            if "livepatch-" in line or "klp-" in line or "klp_" in line:
                mod_name = line.split()[0]
                test_modules.append(mod_name)
        
        if test_modules:
            issues.append(f"Test modules already loaded: {', '.join(test_modules)}")
        
        if issues:
            return False, "\n".join(issues)
        else:
            return True, "Environment is clean"
            
    except Exception as e:
        return False, f"Failed to check environment: {e}"
