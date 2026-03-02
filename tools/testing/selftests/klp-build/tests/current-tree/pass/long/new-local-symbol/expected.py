# SPDX-License-Identifier: GPL-2.0
"""Adds a new static function called from an existing function."""

from verification import (
    verify_ko_exists,
    verify_diff_log_contains,
    verify_klp_module_vmlinux,
    VerificationError,
)

EXPECT_SUCCESS = True


def verify_build(returncode, ko_path, results, **kwargs):
    import os

    if returncode != 0:
        raise VerificationError(f"klp-build failed with exit code {returncode}")
    results.append("klp-build exit code is 0")

    if not ko_path or not os.path.isfile(ko_path):
        raise VerificationError(f"Module not found: {ko_path}")
    results.append(f"Module exists: {os.path.basename(ko_path)}")

    tmp_dir = kwargs.get("tmp_dir")
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: show_stat",
                                 results=results)

    verify_klp_module_vmlinux(ko_path, results,
                              expected_funcs=["show_stat"],
                              tmp_dir=tmp_dir)


def verify_runtime(runtime):
    """
    Verify livepatch behavior at runtime.
    
    This test adds a new static function and calls it from show_stat.
    We trigger /proc/stat to verify the helper function is called.
    
    Args:
        runtime: RuntimeContext object
    """
    # Trigger the patched function - read /proc/stat
    stat = runtime.read_file("/proc/stat")
    if not stat.strip():
        raise AssertionError("Failed to read /proc/stat")
    
    # The helper function should print a message with a counter
    messages = runtime.dmesg.get_messages()
    
    stat_msg_found = any("klp-build-test: stat accessed" in msg and "times" in msg for msg in messages)
    
    if not stat_msg_found:
        raise AssertionError("stat accessed message not found in dmesg")
