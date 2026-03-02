# SPDX-License-Identifier: GPL-2.0
"""Changes spanning multiple files."""

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
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show",
                                 results=results)
        verify_diff_log_contains(tmp_dir, "changed function: version_proc_show",
                                 results=results)

    verify_klp_module_vmlinux(ko_path, results,
                              expected_funcs=["cmdline_proc_show",
                                              "version_proc_show"],
                              tmp_dir=tmp_dir)


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
