"""
Test vmlinux function patching.

This test verifies that klp-build can patch a simple built-in vmlinux function
and change its output message.

Patches klp_test_function() to change the pr_info message.
"""

def generate_patches(test_dir, kernel_root, out_path):
    """
    Return path to livepatch source patch (vmlinux.patch).

    Modifies klp_test_function() to change the pr_info message.
    This patch will be used by klp-build to generate the livepatch module.
    """
    from pathlib import Path

    # Return the static patch file directly (no need to copy)
    patch_file = Path(test_dir) / "vmlinux.patch"
    return str(patch_file.resolve())


def verify_build(returncode, ko_path, results, **kwargs):
    """Verify the livepatch module was built successfully.

    Beyond basic exit-code and file-existence checks, inspects the
    klp_func and klp_object data structures embedded in the .ko to
    confirm the module targets the expected function in vmlinux.
    """
    from lib.verification import VerificationError
    from elf_inspect import (
        dump_struct_from_section, format_struct_dump,
        find_type_source,
    )
    import os

    if returncode != 0:
        raise VerificationError(f"klp-build failed with exit code {returncode}")
    results.append("klp-build exit code is 0")

    if not ko_path or not os.path.isfile(ko_path):
        raise VerificationError(f"Module not found: {ko_path}")
    results.append(f"Module exists: {os.path.basename(ko_path)}")

    tmp_dir = kwargs.get("tmp_dir")
    kernel_root = os.path.dirname(tmp_dir) if tmp_dir else None
    ts = find_type_source(ko_path, "klp_object", kernel_root)

    objs = dump_struct_from_section(
        ko_path, ".init.klp_objects", "klp_object", type_source=ts
    )
    if objs is None:
        raise VerificationError(
            "ELF Analysis: pahole struct info unavailable"
        )
    if not objs:
        raise VerificationError("No klp_object entries in .init.klp_objects")

    results.append("")
    results.append("ELF Analysis:")

    for line in format_struct_dump(objs, "klp_object",
                                   skip_fields={"funcs"},
                                   skip_byte_counts=True):
        results.append(line)

    vmlinux_obj = None
    for obj in objs:
        name = obj.get("name", {})
        if (name.get("is_pointer") and name.get("value") == 0
                and name.get("reloc") is None):
            vmlinux_obj = obj
            break
    if vmlinux_obj is None:
        raise VerificationError(
            "No klp_object with name = NULL (vmlinux target)"
        )
    results.append("VERIFIED: klp_object.name = NULL (vmlinux)")

    funcs = dump_struct_from_section(
        ko_path, ".init.klp_funcs", "klp_func", type_source=ts
    )
    if not funcs:
        raise VerificationError("No klp_func entries in .init.klp_funcs")

    for line in format_struct_dump(funcs, "klp_func", indent=4):
        results.append(line)

    match = [f for f in funcs
             if f.get("old_name", {}).get("resolved") == "klp_test_function"]
    if not match:
        raise VerificationError(
            "No klp_func with old_name = 'klp_test_function'"
        )
    results.append("    VERIFIED: klp_func.old_name = 'klp_test_function'")

    new_func = match[0].get("new_func", {}).get("resolved")
    if new_func != "klp_test_function":
        raise VerificationError(
            f"klp_func.new_func -> {new_func!r}, "
            f"expected 'klp_test_function'"
        )
    results.append("    VERIFIED: klp_func.new_func -> klp_test_function")


def verify_runtime(runtime):
    """
    Verify the livepatch loads and modifies the function behavior.

    Checks:
    1. Livepatch loaded and enabled
    2. Function still returns 42
    3. Dmesg shows new message "vmlinux PATCHED"
    """
    import os
    import subprocess
    from lib.livepatch import is_module_loaded, unload_module

    mod_name = runtime.mod_name
    sysfs_path = f"/sys/kernel/livepatch/{mod_name}"

    runtime.log("Vmlinux patching test")
    runtime.log("")
    runtime.log("Step 1: Verifying livepatch is loaded and enabled")
    runtime.log(f"  Module name: {mod_name}")

    if not os.path.exists(sysfs_path):
        raise RuntimeError(f"Livepatch sysfs not found: {sysfs_path}")
    runtime.log(f"  Livepatch sysfs exists: {sysfs_path}")
    runtime.log("")

    enabled = runtime.read_sysfs(f"{sysfs_path}/enabled")
    if enabled.strip() != "1":
        raise RuntimeError(f"Livepatch not enabled (got '{enabled.strip()}')")

    cleanup_error = None
    try:
        runtime.log("")
        runtime.log("Step 2: Verifying patched function behavior")
        runtime.log("")
        runtime.log("Step 2a: Checking function return value (should still be 42)")
        runtime.log("")

        result = runtime.read_sysfs("/proc/klp_test")
        if result.strip() != "42":
            raise RuntimeError(f"Expected return value 42, got {result.strip()}")

        runtime.log("  SUCCESS: Function returns original value (42)")
        runtime.log("")
        runtime.log("Step 2b: Verifying patched pr_info() in dmesg")
        runtime.log("")

        result = subprocess.run(
            ["sh", "-c", "dmesg | grep 'klp_test: vmlinux PATCHED'"],
            capture_output=True,
            text=True
        )

        runtime.log("$ dmesg | grep 'klp_test: vmlinux PATCHED'")
        if result.returncode == 0 and result.stdout.strip():
            runtime.log(result.stdout.rstrip())
            runtime.log("  SUCCESS: Patched pr_info() message found in dmesg")
        else:
            raise RuntimeError("Expected 'klp_test: vmlinux PATCHED' in dmesg, not found")

    finally:
        runtime.log("")
        runtime.log("Step 3: Disabling livepatch")
        try:
            if os.path.exists(sysfs_path):
                runtime.disable()
                runtime.log(f"  Livepatch {mod_name} disabled")
            else:
                runtime.log(f"  Livepatch already disabled")
        except Exception as e:
            runtime.log(f"  ERROR: Failed to disable livepatch: {e}")
            cleanup_error = cleanup_error or e

        runtime.log("")
        runtime.log("Step 4: Unloading livepatch module")
        try:
            if is_module_loaded(mod_name):
                unload_module(mod_name)
                runtime.log(f"  Module {mod_name} unloaded")
            else:
                runtime.log(f"  Module already unloaded")
        except Exception as e:
            runtime.log(f"  ERROR: Failed to unload module: {e}")
            cleanup_error = cleanup_error or e

    if cleanup_error:
        raise RuntimeError(f"Cleanup failed: {cleanup_error}")

    runtime.log("")
    runtime.log("SUCCESS: Vmlinux patch test passed")
