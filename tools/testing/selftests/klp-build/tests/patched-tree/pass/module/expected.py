"""
Test module function patching.

This test verifies that klp-build can patch a function in a loadable kernel
module.

Workflow:
1. Base infrastructure provides klp_test_mod.c (kernel-module.patch)
2. Livepatch source patch (module.patch) modifies klp_test_mod_function()
3. Runtime verification loads module, applies livepatch, verifies changes
"""

def generate_patches(test_dir, kernel_root, out_path):
    """
    Return path to livepatch source patch (module.patch).

    Modifies klp_test_mod_function() to change return value (100->200) and
    pr_info message. This patch will be used by klp-build to generate the
    livepatch module.
    """
    from pathlib import Path

    # Return the static patch file directly (no need to copy)
    patch_file = Path(test_dir) / "module.patch"
    return str(patch_file.resolve())


def verify_build(returncode, ko_path, results, **kwargs):
    """Verify the livepatch module targets klp_test_mod_function in klp_test_mod."""
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

    mod_obj = [obj for obj in objs
               if obj.get("name", {}).get("resolved") == "klp_test_mod"]
    if not mod_obj:
        raise VerificationError(
            "No klp_object with name = 'klp_test_mod'"
        )
    results.append("VERIFIED: klp_object.name = 'klp_test_mod'")

    funcs = dump_struct_from_section(
        ko_path, ".init.klp_funcs", "klp_func", type_source=ts
    )
    if not funcs:
        raise VerificationError("No klp_func entries in .init.klp_funcs")

    for line in format_struct_dump(funcs, "klp_func", indent=4):
        results.append(line)

    match = [f for f in funcs
             if f.get("old_name", {}).get("resolved") == "klp_test_mod_function"]
    if not match:
        raise VerificationError(
            "No klp_func with old_name = 'klp_test_mod_function'"
        )
    results.append(
        "    VERIFIED: klp_func.old_name = 'klp_test_mod_function'"
    )

    new_func = match[0].get("new_func", {}).get("resolved")
    if new_func != "klp_test_mod_function":
        raise VerificationError(
            f"klp_func.new_func -> {new_func!r}, "
            f"expected 'klp_test_mod_function'"
        )
    results.append(
        "    VERIFIED: klp_func.new_func -> klp_test_mod_function"
    )


def verify_runtime(runtime):
    """
    Verify the livepatch patches a module loaded after the livepatch.

    The runtime framework loads the livepatch .ko first. When we then load
    klp_test_mod, the livepatch intercepts the module load and patches it
    immediately. This tests livepatch's "patch on module load" capability.

    Checks:
    1. Livepatch is already loaded and enabled
    2. Load test module (klp_test_mod) - livepatch patches it on load
    3. Verify function returns patched value (200, not original 100)
    4. Verify dmesg shows patched message
    5. Cleanup: disable livepatch, unload livepatch, then unload test module
    """

    import subprocess
    import os
    import sys
    from pathlib import Path

    test_dir = Path(__file__).parent.parent.parent.parent
    sys.path.insert(0, str(test_dir / "lib"))
    from lib import get_kernel_src_dir

    mod_name = runtime.mod_name
    sysfs_path = f"/sys/kernel/livepatch/{mod_name}"

    runtime.log("Module patching test (patch-on-load scenario)")
    runtime.log("")
    runtime.log("Step 1: Verifying livepatch is loaded and enabled")
    runtime.log(f"  Module name: {mod_name}")

    if not os.path.exists(sysfs_path):
        raise RuntimeError(f"Livepatch sysfs not found: {sysfs_path}")
    runtime.log(f"  Livepatch sysfs exists: {sysfs_path}")

    enabled = runtime.read_sysfs(f"{sysfs_path}/enabled")
    if enabled.strip() != "1":
        raise RuntimeError(f"Livepatch not enabled (got '{enabled.strip()}')")
    runtime.log("")

    runtime.log("Step 2: Loading test module (klp_test_mod)")
    runtime.log("  Livepatch is already active - module will be patched on load")

    kernel_root = get_kernel_src_dir()

    # Look for klp_test_mod.ko: first the in-tree build path, then the
    # saved modules_install directory (used when kernel was saved by
    # build_tests and restored for runtime).
    mod_path = kernel_root / "kernel" / "livepatch" / "klp_test_mod.ko"
    if not mod_path.exists():
        import glob
        pattern = str(kernel_root / "lib" / "modules" / "*" / "kernel" /
                       "livepatch" / "klp_test_mod.ko")
        matches = glob.glob(pattern)
        if matches:
            mod_path = Path(matches[0])

    if not mod_path.exists():
        raise RuntimeError(
            f"Test module not found at {kernel_root}/kernel/livepatch/klp_test_mod.ko "
            f"or {kernel_root}/lib/modules/*/kernel/livepatch/klp_test_mod.ko"
        )

    runtime.log(f"  Loading {mod_path}")

    result = subprocess.run(
        ["insmod", str(mod_path)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to load klp_test_mod: {result.stderr}")

    runtime.log("  klp_test_mod loaded")
    runtime.log("")

    from lib.livepatch import is_module_loaded, unload_module

    cleanup_error = None
    try:
        runtime.log("Step 3: Verifying patched function behavior")
        runtime.log("  Original value: 100 (never observable - livepatch applied on load)")
        runtime.log("  Expected value: 200 (patched)")
        runtime.log("")

        result = runtime.read_sysfs("/proc/klp_test_mod")
        if result.strip() != "200":
            raise RuntimeError(f"Expected patched return value 200, got {result.strip()}")

        runtime.log("  SUCCESS: Function returns patched value (200)")
        runtime.log("")
        runtime.log("Step 4: Verifying patched pr_info() in dmesg")
        runtime.log("")

        result = subprocess.run(
            ["sh", "-c", "dmesg | grep 'klp_test_mod: PATCHED module function'"],
            capture_output=True,
            text=True
        )

        runtime.log("$ dmesg | grep 'klp_test_mod: PATCHED module function'")
        if result.returncode == 0 and result.stdout.strip():
            runtime.log(result.stdout.rstrip())
            runtime.log("  SUCCESS: Patched pr_info() message found in dmesg")
        else:
            raise RuntimeError("Expected 'klp_test_mod: PATCHED module function' in dmesg, not found")

    finally:
        # Cleanup sequence follows upstream functions.sh:
        # 1. disable_lp: write 0 -> enabled, wait for sysfs entry to vanish
        # 2. unload_lp: wait for refcnt=0, rmmod, wait for /sys/module gone
        # 3. unload test module: same refcnt + rmmod + sysfs wait
        runtime.log("")
        runtime.log("Step 5: Disabling livepatch")
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
        runtime.log("Step 6: Unloading livepatch module")
        try:
            if is_module_loaded(mod_name):
                unload_module(mod_name)
                runtime.log(f"  Livepatch module {mod_name} unloaded")
            else:
                runtime.log(f"  Livepatch module already unloaded")
        except Exception as e:
            runtime.log(f"  ERROR: Failed to unload livepatch: {e}")
            cleanup_error = cleanup_error or e

        runtime.log("")
        runtime.log("Step 7: Unloading test module (klp_test_mod)")
        try:
            if is_module_loaded("klp_test_mod"):
                unload_module("klp_test_mod")
                runtime.log("  klp_test_mod unloaded")
            else:
                runtime.log("  klp_test_mod already unloaded")
        except Exception as e:
            runtime.log(f"  ERROR: Failed to unload klp_test_mod: {e}")
            cleanup_error = cleanup_error or e

    if cleanup_error:
        raise RuntimeError(f"Cleanup failed: {cleanup_error}")

    runtime.log("")
    runtime.log("SUCCESS: Module patch test passed")
