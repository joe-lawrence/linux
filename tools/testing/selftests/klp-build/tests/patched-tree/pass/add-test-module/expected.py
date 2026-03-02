"""
Patched-tree test: Livepatch klp_test_function() provided by base infrastructure.

This test demonstrates the patched-tree workflow using the common base
infrastructure (klp_test.c added by tests/patched-tree/base/).

Workflow:
1. Base infrastructure adds klp_test.c to kernel (applied once for all tests)
2. This test generates livepatch that modifies klp_test_function()
3. klp-build generates livepatch module
4. Runtime verification loads the livepatch and verifies it applies

Benefits of using base infrastructure:
- No need to modify kernel code in individual tests
- Tests remain simple and focused on livepatch generation
- Base infrastructure is shared across all patched-tree tests
- Adding new tests doesn't require touching base
"""

def generate_patches(test_dir, kernel_root, out_path):
    """
    Return path to livepatch source patch (add-test-module.patch).

    Changes klp_test_function() to return a different value and print
    a different message.
    """
    from pathlib import Path

    # Return the static patch file directly (no need to copy)
    patch_file = Path(test_dir) / "add-test-module.patch"
    return str(patch_file.resolve())


def verify_build(returncode, ko_path, results, **kwargs):
    """Verify the livepatch module targets klp_test_function in vmlinux."""
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
    Verify the livepatch module loads and applies successfully.

    This test verifies:
    1. Livepatch loaded and enabled (already done by runtime_tests.py)
    2. After livepatch applies, function returns 99
    3. Dmesg shows patched message
    4. Cleanup: disable + unload (following upstream functions.sh pattern)
    """
    import os
    import subprocess
    from lib.livepatch import is_module_loaded, unload_module

    mod_name = runtime.mod_name
    sysfs_path = f"/sys/kernel/livepatch/{mod_name}"

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
        runtime.log("Step 2a: Checking function return value")
        runtime.log("")

        result = runtime.read_sysfs("/proc/klp_test")
        if result.strip() != "99":
            raise RuntimeError(f"Expected patched return value 99, got {result.strip()}")

        runtime.log("  SUCCESS: Function returns patched value (99)")
        runtime.log("")
        runtime.log("Step 2b: Verifying patched pr_info() in dmesg")
        runtime.log("")

        result = subprocess.run(
            ["sh", "-c", "dmesg | grep 'klp_test: PATCHED function'"],
            capture_output=True,
            text=True
        )

        runtime.log("$ dmesg | grep 'klp_test: PATCHED function'")
        if result.returncode == 0 and result.stdout.strip():
            runtime.log(result.stdout.rstrip())
            runtime.log("  SUCCESS: Patched pr_info() message found in dmesg")
        else:
            raise RuntimeError("Expected 'klp_test: PATCHED function' in dmesg, not found")

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
    runtime.log("SUCCESS: Full livepatch lifecycle verified")
