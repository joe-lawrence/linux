# SPDX-License-Identifier: GPL-2.0
"""Single-function livepatch on fs/proc/cmdline.c."""

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

    verify_klp_module_vmlinux(ko_path, results,
                              expected_funcs=["cmdline_proc_show"],
                              tmp_dir=tmp_dir)


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
