# SPDX-License-Identifier: GPL-2.0
"""Patch to .S file should fail at validation."""

from verification import (
    verify_exit_code_nonzero,
    verify_stderr_matches,
)

EXPECT_SUCCESS = False

_UNSUPPORTED_ASM_PATCH = """From: Test Author <test@example.com>
Subject: [PATCH] x86/entry: add test comment

Unsupported assembly file patch test case.

This patch modifies a .S file and should fail during validation.

diff --git a/arch/x86/entry/entry_32.S b/arch/x86/entry/entry_32.S
--- a/arch/x86/entry/entry_32.S
+++ b/arch/x86/entry/entry_32.S
@@ -1,6 +1,7 @@
+\t/* klp-build-test: should fail */
 /* SPDX-License-Identifier: GPL-2.0 */
 /*
  *  Copyright (C) 1991,1992  Linus Torvalds
"""


def generate_patches(test_dir, kernel_root, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_UNSUPPORTED_ASM_PATCH)
    return [out_path]


def verify(*, returncode=None, stderr=None, **kwargs):
    if returncode is not None:
        verify_exit_code_nonzero(returncode)
    if stderr is not None:
        verify_stderr_matches(stderr, r"unsupported patch to.*\.S")
