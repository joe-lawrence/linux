# SPDX-License-Identifier: GPL-2.0
"""Removes a documentation file while modifying code (generated patch)."""

import os

from verification import (
    verify_ko_exists,
    verify_elf_section,
    verify_diff_log_contains,
)

EXPECT_SUCCESS = True


def generate_patches(test_dir, kernel_root, out_path):
    """
    Generate a patch that removes a documentation file and modifies code.
    Requires Documentation/livepatch/*.rst to exist.
    """
    doc_dir = os.path.join(kernel_root, "Documentation", "livepatch")
    doc_files = [
        os.path.join(doc_dir, f)
        for f in sorted(os.listdir(doc_dir)) if f.endswith(".rst")
    ] if os.path.isdir(doc_dir) else []
    if not doc_files:
        raise RuntimeError("No documentation files found in Documentation/livepatch/")
    doc_path = doc_files[0]
    doc_rel = os.path.relpath(doc_path, kernel_root)
    with open(doc_path, "r", encoding="utf-8", errors="replace") as f:
        doc_lines = f.readlines()
    patch_content = (
        "From: Test Author <test@example.com>\n"
        "Subject: [PATCH] Remove unused doc and update proc\n\n"
        "Remove file livepatch test case.\n\n"
        f"diff --git a/{doc_rel} b/{doc_rel}\n"
        "deleted file mode 100644\n"
        f"--- a/{doc_rel}\n"
        "+++ /dev/null\n"
        f"@@ -1,{len(doc_lines)} +0,0 @@\n"
    )
    for line in doc_lines:
        patch_content += "-" + line
    patch_content += (
        "diff --git a/fs/proc/cmdline.c b/fs/proc/cmdline.c\n"
        "--- a/fs/proc/cmdline.c\n+++ b/fs/proc/cmdline.c\n"
        "@@ -8,6 +8,7 @@\n\n"
        " static int cmdline_proc_show(struct seq_file *m, void *v)\n"
        " {\n"
        '+\tpr_info("klp-build-test: remove-file test\\n");\n'
        "\tseq_puts(m, saved_command_line);\n"
        "\tseq_putc(m, '\\n');\n"
        "\treturn 0;\n"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(patch_content)
    return [out_path]


def verify(*, ko_path=None, tmp_dir=None, **kwargs):
    if ko_path:
        verify_ko_exists(ko_path)
        verify_elf_section(ko_path, ".klp.rela.vmlinux..text")
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show")
