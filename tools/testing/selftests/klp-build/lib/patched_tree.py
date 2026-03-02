# SPDX-License-Identifier: GPL-2.0
"""Shared utilities for patched-tree test infrastructure."""

import os
import re
import subprocess
import sys


def _files_created_by_patch(patch_path: str) -> list:
    """Return list of files created by a unified diff patch.

    Detects new files by either:
    - ``--- /dev/null`` (git-style)
    - ``@@ -0,0 +1,N @@`` hunk header (diff -Na style, absent file treated as empty)
    """
    created = []
    with open(patch_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("+++ "):
            new_path = lines[i].split()[1] if len(lines[i].split()) > 1 else ""
            new_path = re.sub(r'^[ab]/', '', new_path)
            is_new = False
            if i > 0 and "/dev/null" in lines[i - 1]:
                is_new = True
            elif i + 1 < len(lines) and lines[i + 1].startswith("@@ -0,0 "):
                is_new = True
            if is_new and new_path and new_path != "/dev/null":
                created.append(new_path)
        i += 1
    return created


def apply_kernel_patches(kernel_root: str, patch_paths: list) -> bool:
    """Apply patches to kernel source tree (not livepatch, but kernel modifications).

    Returns True if patches were newly applied, False if already applied.
    Raises RuntimeError if a patch genuinely fails.
    """
    any_applied = False
    for patch in patch_paths:
        if not os.path.isfile(patch):
            raise RuntimeError(f"Kernel patch not found: {patch}")
        result = subprocess.run(
            ["patch", "-d", kernel_root, "-p1", "--forward",
             "--no-backup-if-mismatch"],
            stdin=open(patch, "r"),
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            any_applied = True
        else:
            combined = result.stdout + result.stderr
            if "Reversed (or previously applied)" in combined:
                continue
            raise RuntimeError(f"Failed to apply kernel patch {patch}: {result.stderr}")
    return any_applied


def revert_kernel_patches(kernel_root: str, patch_paths: list) -> None:
    """Revert patches from kernel source tree, including deleting created files."""
    for patch in reversed(patch_paths):
        if not os.path.isfile(patch):
            continue
        # Collect files this patch created (from /dev/null) before reverting
        created_files = _files_created_by_patch(patch)

        result = subprocess.run(
            ["patch", "-d", kernel_root, "-p1", "-R",
             "--silent", "--no-backup-if-mismatch"],
            stdin=open(patch, "r"),
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"# Warning: failed to revert kernel patch {patch}",
                  flush=True, file=sys.stderr)

        # Delete files that were created from /dev/null (patch -R leaves empties)
        for rel_path in created_files:
            full_path = os.path.join(kernel_root, rel_path)
            try:
                if os.path.isfile(full_path):
                    os.unlink(full_path)
            except OSError:
                pass


def load_and_generate_base_patches(selftest_root: str, kernel_root: str) -> list:
    """
    Load and generate base patches for patched-tree tests.

    Returns list of generated patch paths.
    Raises exception if base patches cannot be loaded or generated.
    """
    base_dir = os.path.join(selftest_root, "tests", "patched-tree", "base")
    if not os.path.isdir(base_dir):
        return []

    expected_py = os.path.join(base_dir, "expected.py")
    if not os.path.isfile(expected_py):
        return []

    # Load base module
    sys.path.insert(0, os.path.join(selftest_root, "lib"))
    from verification import load_expected

    mod = load_expected(base_dir)
    gen_base = getattr(mod, "generate_kernel_patches", None) if mod else None

    if not callable(gen_base):
        return []

    # Generate base patches
    out_path = os.path.join(base_dir, "base-kernel.patch")
    try:
        resolved = gen_base(base_dir, kernel_root, out_path)
        base_patches = resolved if isinstance(resolved, list) else [resolved]
    except Exception as e:
        raise RuntimeError(f"Failed to generate base patches: {e}")

    return base_patches


def has_patched_tree_artifacts(artifacts_root: str, selftest_root: str) -> bool:
    """
    Check if any built artifacts come from patched-tree tests.

    Returns True if we need to build a patched kernel for runtime testing.
    """
    if not os.path.isdir(artifacts_root):
        return False

    patched_tree_pass = os.path.join(selftest_root, "tests", "patched-tree", "pass")
    if not os.path.isdir(patched_tree_pass):
        return False

    # Get list of patched-tree test names
    patched_tests = set()
    for item in os.listdir(patched_tree_pass):
        item_path = os.path.join(patched_tree_pass, item)
        if os.path.isdir(item_path) and item != "base":
            patched_tests.add(item)

    if not patched_tests:
        return False

    # Check if any artifacts match patched-tree tests.
    # Handles both the new layout (profile/patched-tree/test/) and legacy
    # flat layout (profile/test/).
    for profile_dir in os.listdir(artifacts_root):
        profile_path = os.path.join(artifacts_root, profile_dir)
        if not os.path.isdir(profile_path):
            continue

        for entry in os.listdir(profile_path):
            entry_path = os.path.join(profile_path, entry)
            if not os.path.isdir(entry_path):
                continue

            if entry == "patched-tree":
                # New layout: profile/patched-tree/test/
                for test_dir in os.listdir(entry_path):
                    test_path = os.path.join(entry_path, test_dir)
                    if os.path.isdir(test_path):
                        for f in os.listdir(test_path):
                            if f.endswith('.ko'):
                                return True
            elif entry in patched_tests:
                # Legacy flat layout: profile/test/
                for f in os.listdir(entry_path):
                    if f.endswith('.ko'):
                        return True

    return False
