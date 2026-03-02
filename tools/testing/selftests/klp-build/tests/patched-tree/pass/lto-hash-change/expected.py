"""
Test ThinLTO hash collision and suffix handling.

Two files (klp_test_hash1.c, klp_test_hash2.c) are linked as a multi-object
(klp_test_hash-y := klp_test_hash1.o klp_test_hash2.o). Both define
static __helper() with different bodies. Under ThinLTO, both get promoted
to globals with .llvm.<hash> suffixes to avoid collision.

The livepatch modifies __helper() in hash2, which changes its hash suffix.
klp-build must correlate the old and new symbols despite the hash change.

Inspired by Song Liu's klp-build test series (patch 5/8: objtool suffix
stripping, patch 8/8: test infrastructure).
"""

REQUIRED_CONFIG = ["CONFIG_LTO_CLANG_THIN"]
SUPPORTED_COMPILERS = ["clang"]

def generate_patches(test_dir, kernel_root, out_path):
    from pathlib import Path
    patch_file = Path(test_dir) / "lto-hash-change.patch"
    return str(patch_file.resolve())


def verify_build(returncode, ko_path, results, tmp_dir=None, **kwargs):
    from lib.verification import VerificationError
    from elf_inspect import (
        dump_struct_from_section, format_struct_dump,
        find_type_source, is_thinlto_config, find_llvm_suffixed,
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
    expect = ["__helper", "klp_test_hash2_proc_show"]
    for name in expect:
        if not any(name in n for n in old_names):
            raise VerificationError(
                f"No klp_func.old_name contains '{name}'"
            )
        results.append(f"    VERIFIED: klp_func target contains '{name}'")

    if not tmp_dir:
        return

    kernel_root = os.path.dirname(tmp_dir)
    config_path = os.path.join(kernel_root, ".config")
    vmlinux_path = os.path.join(kernel_root, "vmlinux")

    if not is_thinlto_config(config_path):
        results.append("ThinLTO: CONFIG_LTO_CLANG_THIN not set")
        return

    results.append("ThinLTO: CONFIG_LTO_CLANG_THIN=y")

    if not os.path.isfile(vmlinux_path):
        raise VerificationError("vmlinux not found for symbol inspection")

    suffixed = find_llvm_suffixed(vmlinux_path, "__helper")
    results.append(f"ThinLTO: {len(suffixed)} __helper.llvm.* symbols in vmlinux")
    if len(suffixed) >= 2:
        hashes = set()
        for name, _ in suffixed:
            parts = name.split(".llvm.")
            if len(parts) == 2:
                hashes.add(parts[1])
        results.append(f"ThinLTO: {len(hashes)} unique hash suffixes")


def verify_runtime(runtime):
    """
    Verify hash collision handling: hash2 output changes from
    "unpatched" to "patched", while hash1 remains "unpatched".
    """
    import os
    from lib.livepatch import is_module_loaded, unload_module

    mod_name = runtime.mod_name
    sysfs_path = f"/sys/kernel/livepatch/{mod_name}"

    runtime.log("ThinLTO hash collision runtime test")
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
        hash1_out = runtime.read_sysfs("/proc/klp_test_hash1")
        runtime.log(f"hash1 output: {hash1_out.strip()}")
        if "unpatched" not in hash1_out:
            raise RuntimeError(f"hash1 should still show 'unpatched': {hash1_out.strip()}")
        runtime.log("  OK: hash1 unchanged (not targeted by livepatch)")
        runtime.log("")

        hash2_out = runtime.read_sysfs("/proc/klp_test_hash2")
        runtime.log(f"hash2 output: {hash2_out.strip()}")
        if "patched" not in hash2_out or "unpatched" in hash2_out:
            raise RuntimeError(f"hash2 should show 'patched': {hash2_out.strip()}")
        runtime.log("  OK: hash2 patched (klp-build correlated symbols despite hash change)")

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
    runtime.log("SUCCESS: ThinLTO hash collision test passed")
