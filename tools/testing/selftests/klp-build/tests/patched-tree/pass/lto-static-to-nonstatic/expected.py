"""
Test symbol visibility change: static (LOCAL) to non-static (GLOBAL).

klp_test_stn_func() starts as a static (file-local) function. The
livepatch changes it to non-static. This tests objtool's ability to
correlate a LOCAL original symbol with a GLOBAL patched symbol - the
kind of binding change ThinLTO can introduce.

Inspired by Song Liu's klp-build test series (patch 7/8: objtool
local-to-global correlation, patch 8/8: test infrastructure).
"""

REQUIRED_CONFIG = ["CONFIG_LTO_CLANG_THIN"]
SUPPORTED_COMPILERS = ["clang"]

def generate_patches(test_dir, kernel_root, out_path):
    from pathlib import Path
    patch_file = Path(test_dir) / "lto-static-to-nonstatic.patch"
    return str(patch_file.resolve())


def verify_build(returncode, ko_path, results, tmp_dir=None, **kwargs):
    from lib.verification import VerificationError
    from elf_inspect import (
        dump_struct_from_section, format_struct_dump,
        find_type_source, is_thinlto_config, get_symbol_nm_type,
        find_llvm_suffixed,
    )
    import os

    if returncode != 0:
        raise VerificationError(f"klp-build failed with exit code {returncode}")
    results.append("klp-build exit code is 0")

    if not ko_path or not os.path.isfile(ko_path):
        raise VerificationError(f"Module not found: {ko_path}")
    results.append(f"Module exists: {os.path.basename(ko_path)}")

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

    old_names = [f.get("old_name", {}).get("resolved", "") for f in funcs]
    if not any("klp_test_static_proc_show" in n for n in old_names):
        raise VerificationError(
            "No klp_func.old_name contains 'klp_test_static_proc_show'"
        )
    results.append(
        "    VERIFIED: klp_func target contains 'klp_test_static_proc_show'"
    )

    if not tmp_dir:
        return

    kernel_root = os.path.dirname(tmp_dir)
    config_path = os.path.join(kernel_root, ".config")
    vmlinux_path = os.path.join(kernel_root, "vmlinux")

    if not os.path.isfile(vmlinux_path):
        raise VerificationError("vmlinux not found for binding inspection")

    if is_thinlto_config(config_path):
        results.append("ThinLTO: CONFIG_LTO_CLANG_THIN=y")
        suffixed = find_llvm_suffixed(vmlinux_path, "klp_test_stn_func")
        if suffixed:
            results.append(
                f"ThinLTO: original symbol promoted: {suffixed[0][0]}"
            )
        else:
            nm_type = get_symbol_nm_type(vmlinux_path, "klp_test_stn_func")
            if nm_type:
                results.append(
                    f"Original binding: {nm_type} (expected 't' = LOCAL)"
                )
    else:
        nm_type = get_symbol_nm_type(vmlinux_path, "klp_test_stn_func")
        if nm_type:
            results.append(
                f"Original binding: nm type '{nm_type}' (expected 't' = LOCAL)"
            )


def verify_runtime(runtime):
    """
    Verify that the livepatch applies despite the LOCAL->GLOBAL
    visibility change. Output should change from "unpatched" to "patched".
    """
    import os
    from lib.livepatch import is_module_loaded, unload_module

    mod_name = runtime.mod_name
    sysfs_path = f"/sys/kernel/livepatch/{mod_name}"

    runtime.log("Static to non-static visibility runtime test")
    runtime.log("")

    if not os.path.exists(sysfs_path):
        raise RuntimeError(f"Livepatch sysfs not found: {sysfs_path}")

    enabled = runtime.read_sysfs(f"{sysfs_path}/enabled")
    if enabled.strip() != "1":
        raise RuntimeError(f"Livepatch not enabled (got '{enabled.strip()}')")
    runtime.log("Livepatch loaded and enabled")
    runtime.log("")

    cleanup_error = None
    try:
        result = runtime.read_sysfs("/proc/klp_test_static")
        runtime.log(f"output: {result.strip()}")
        if "patched" not in result or "unpatched" in result:
            raise RuntimeError(f"Expected 'patched' in output: {result.strip()}")
        runtime.log("  OK: function patched (LOCAL->GLOBAL correlation worked)")

    finally:
        runtime.log("")
        try:
            if os.path.exists(sysfs_path):
                runtime.disable()
            if is_module_loaded(mod_name):
                unload_module(mod_name)
            runtime.log(f"Livepatch {mod_name} disabled and unloaded")
        except Exception as e:
            runtime.log(f"ERROR: Cleanup failed: {e}")
            cleanup_error = cleanup_error or e

    if cleanup_error:
        raise RuntimeError(f"Cleanup failed: {cleanup_error}")

    runtime.log("")
    runtime.log("SUCCESS: Static to non-static visibility test passed")
