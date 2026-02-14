# SPDX-License-Identifier: GPL-2.0
"""Patch to lib/ file should fail at validation."""

import os

from verification import (
    verify_exit_code_nonzero,
    verify_stderr_matches,
)

EXPECT_SUCCESS = False

_RELPATH = "lib/ashldi3.c"
_INSERT = "\t/* klp-build-test: should fail */\n"


def generate_patches(test_dir, kernel_root, out_path):
    src = os.path.join(kernel_root, _RELPATH)
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if "__ashldi3(" in line and i + 1 < len(lines):
            start = max(0, i)
            end = min(len(lines), i + 4)
            old_slice = lines[start:end]
            hunk_len = len(old_slice)
            hunk = (
                f"@@ -{start + 1},{hunk_len} +{start + 1},{hunk_len + 1} @@\n"
                + " " + old_slice[0]
                + "+" + _INSERT
                + "".join(" " + ln for ln in old_slice[1:])
            )
            patch = (
                "From: Test Author <test@example.com>\n"
                "Subject: [PATCH] lib: add test comment\n\n"
                "Unsupported lib/ file patch test case.\n\n"
                f"diff --git a/{_RELPATH} b/{_RELPATH}\n"
                f"--- a/{_RELPATH}\n+++ b/{_RELPATH}\n"
                + hunk
            )
            break
    else:
        patch = (
            "diff --git a/lib/ashldi3.c b/lib/ashldi3.c\n"
            "--- a/lib/ashldi3.c\n+++ b/lib/ashldi3.c\n"
            "@@ -9,6 +9,7 @@\n"
            " long long notrace __ashldi3(long long u, word_type b)\n"
            "+	/* klp-build-test: should fail */\n"
            " {\n"
            " \tDWunion uu, w;\n"
            " \tword_type bm;\n"
        )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(patch)
    return [out_path]


def verify(*, returncode=None, stderr=None, **kwargs):
    if returncode is not None:
        verify_exit_code_nonzero(returncode)
    if stderr is not None:
        verify_stderr_matches(stderr, r"unsupported patch to lib/")
