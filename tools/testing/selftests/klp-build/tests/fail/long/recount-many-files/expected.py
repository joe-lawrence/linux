# SPDX-License-Identifier: GPL-2.0
"""Patch many .c files with asm(\"nop\") that produces no object changes."""

import os
import subprocess

from verification import (
    verify_exit_code_nonzero,
    verify_stderr_matches,
)

EXPECT_SUCCESS = False
EXPECT_ERROR = r"no changes detected"


def generate_patches(test_dir, kernel_root, out_path):
    """
    Generate a patch that modifies many .c files but produces no object changes.
    Calls generate.sh to bulk-modify files and write the patch. Requires a
    clean working tree in kernel_root.
    """
    script = os.path.join(test_dir, "generate.sh")
    if not os.path.isfile(script):
        raise FileNotFoundError(f"generate.sh not found: {script}")
    os.chmod(script, 0o755)
    subprocess.run(
        [script, kernel_root, out_path],
        check=True,
        cwd=kernel_root,
    )
    return [out_path]


def verify(*, returncode=None, stderr=None, results=None, **kwargs):
    """Verify klp-build detects no changes and fails with expected message."""
    if returncode is not None:
        verify_exit_code_nonzero(returncode, results=results)
    if stderr is not None:
        verify_stderr_matches(stderr, EXPECT_ERROR, results=results)
