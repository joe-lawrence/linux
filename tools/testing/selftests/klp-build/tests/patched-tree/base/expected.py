"""
Patched-tree base infrastructure.

This module provides the common kernel patches that establish the baseline
for ALL patched-tree tests. Each test's kernel infrastructure is provided
as a separate kernel-<test>.patch file in this directory.

Design:
- All kernel-*.patch files are applied ONCE at the start of patched-tree test runs
- They stay applied throughout all tests (creating a golden base kernel)
- All tests share the same original kernel (performance optimization)
- Only reverted at the very end
- Individual tests only apply their livepatch source patches (no kernel mods)

Benefits:
- Each test's kernel code in a focused, reviewable patch file
- All tests share same base kernel -- can reuse klp-tmp/orig/ with -S 0
- Adding new tests: just add kernel-<test>.patch to base/
- Clear organization: base/ has all kernel infrastructure
"""

def generate_kernel_patches(test_dir, kernel_root, out_path):
    """
    Return all base kernel patches for patched-tree tests.

    Reads all kernel-*.patch files from the base directory and returns them
    as a list. All patches are applied together to create the golden base
    kernel that all patched-tree tests share.

    This allows:
    - Each test's kernel infrastructure in a separate, focused patch file
    - All tests sharing the same original kernel (performance optimization)
    - Easy addition of new test infrastructure (just add kernel-<test>.patch)
    """
    from pathlib import Path

    # Find all kernel-*.patch files in base directory
    base_dir = Path(test_dir)
    patches = sorted(base_dir.glob("kernel-*.patch"))

    # Return list of absolute paths
    return [str(p.resolve()) for p in patches]
