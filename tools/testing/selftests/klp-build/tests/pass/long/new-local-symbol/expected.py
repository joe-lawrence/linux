# SPDX-License-Identifier: GPL-2.0
"""Adds a new static function called from an existing function."""

from verification import (
    verify_ko_exists,
    verify_elf_section,
    verify_diff_log_contains,
)

EXPECT_SUCCESS = True


def verify(*, ko_path=None, tmp_dir=None, results=None, **kwargs):
    if ko_path:
        verify_ko_exists(ko_path, results=results)
        verify_elf_section(ko_path, ".klp.rela.vmlinux..text", results=results)
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: show_stat", results=results)


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
