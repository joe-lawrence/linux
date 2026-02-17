# SPDX-License-Identifier: GPL-2.0
"""Single-function livepatch on fs/proc/cmdline.c."""

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
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show", results=results)


def verify_runtime(runtime):
    """
    Verify livepatch behavior at runtime.
    
    Triggers the patched cmdline_proc_show() function and verifies
    livepatch activation.
    
    Args:
        runtime: RuntimeContext object
    """
    # Read /proc/cmdline to trigger the patched function
    cmdline = runtime.read_file("/proc/cmdline")
    
    # Verify we got something
    if not cmdline.strip():
        raise AssertionError("Failed to read /proc/cmdline")
    
    # Check dmesg for livepatch activation message
    messages = runtime.dmesg.get_messages(filters=["livepatch"])
    if not messages:
        raise AssertionError("No livepatch messages found in dmesg")
    
    # Look for successful patching message
    enabled_msg = any("enabling patch" in msg.lower() for msg in messages)
    if not enabled_msg:
        raise AssertionError(f"Livepatch not enabled. Messages: {messages}")
