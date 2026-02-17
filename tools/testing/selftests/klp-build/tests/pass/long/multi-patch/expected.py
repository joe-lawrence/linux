# SPDX-License-Identifier: GPL-2.0
"""Multiple independent patch files applied together."""

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
        verify_diff_log_contains(tmp_dir, "changed function: loadavg_proc_show", results=results)


def verify_runtime(runtime):
    """
    Verify livepatch behavior at runtime.
    
    This test applies two separate patches (to cmdline.c and loadavg.c),
    so we trigger both code paths to verify both patches are active.
    
    Args:
        runtime: RuntimeContext object
    """
    # Trigger first patch (cmdline.c)
    cmdline = runtime.read_file("/proc/cmdline")
    if not cmdline.strip():
        raise AssertionError("Failed to read /proc/cmdline")
    
    # Trigger second patch (loadavg.c)
    loadavg = runtime.read_file("/proc/loadavg")
    if not loadavg.strip():
        raise AssertionError("Failed to read /proc/loadavg")
    
    # Check dmesg for both patch messages
    messages = runtime.dmesg.get_messages()
    
    patch1_found = any("klp-build-test: cmdline patch 1" in msg for msg in messages)
    patch2_found = any("klp-build-test: loadavg patch 2" in msg for msg in messages)
    
    if not patch1_found:
        raise AssertionError("First patch debug message not found in dmesg")
    
    if not patch2_found:
        raise AssertionError("Second patch debug message not found in dmesg")
