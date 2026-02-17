# SPDX-License-Identifier: GPL-2.0
"""Changes spanning multiple files."""

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
        verify_diff_log_contains(tmp_dir, "changed function: version_proc_show", results=results)


def verify_runtime(runtime):
    """
    Verify livepatch behavior at runtime.
    
    This test patches two different files (cmdline.c and version.c),
    so we trigger both code paths.
    
    Args:
        runtime: RuntimeContext object
    """
    # Trigger first patched function
    cmdline = runtime.read_file("/proc/cmdline")
    if not cmdline.strip():
        raise AssertionError("Failed to read /proc/cmdline")
    
    # Trigger second patched function
    version = runtime.read_file("/proc/version")
    if not version.strip():
        raise AssertionError("Failed to read /proc/version")
    
    # Check dmesg for both debug messages
    messages = runtime.dmesg.get_messages()
    
    cmdline_found = any("klp-build-test: cmdline_proc_show called" in msg for msg in messages)
    version_found = any("klp-build-test: version_proc_show called" in msg for msg in messages)
    
    if not cmdline_found:
        raise AssertionError("cmdline_proc_show debug message not found in dmesg")
    
    if not version_found:
        raise AssertionError("version_proc_show debug message not found in dmesg")
