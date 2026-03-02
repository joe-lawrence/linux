# SPDX-License-Identifier: GPL-2.0
"""Multiple independent patch files applied together."""

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
        verify_diff_log_contains(tmp_dir, "changed function: loadavg_proc_show",
                                 results=results)

    verify_klp_module_vmlinux(ko_path, results,
                              expected_funcs=["cmdline_proc_show",
                                              "loadavg_proc_show"],
                              tmp_dir=tmp_dir)


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
