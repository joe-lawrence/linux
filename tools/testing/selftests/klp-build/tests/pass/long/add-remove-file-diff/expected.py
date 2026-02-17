# SPDX-License-Identifier: GPL-2.0
"""Add and remove files using diff -Nupr format (generated patch)."""

import os
import shutil
import subprocess
import tempfile

from verification import (
    verify_ko_exists,
    verify_elf_section,
    verify_diff_log_contains,
)

EXPECT_SUCCESS = True

# Header lines for the patch (same as add-remove-file-git).
_PATCH_HEADER = (
    "From: Test Author <test@example.com>\n"
    "Subject: [PATCH] Add/remove files and update proc (diff -Nupr)\n\n"
    "Same changes as add-remove-file-git in diff -Nupr format.\n\n"
)

# Content for the two new headers.
_KLP_HEADER1 = '''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _KLP_TEST_HEADER1_H
#define _KLP_TEST_HEADER1_H

#define KLP_TEST_MARKER1 "klp-build-test: header1 included"
#endif
'''

_KLP_HEADER2 = '''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _KLP_TEST_HEADER2_H
#define _KLP_TEST_HEADER2_H

#define KLP_TEST_MARKER2 "klp-build-test: header2 included"
#endif
'''


def _find_line_containing(path, text, after_line=0):
    """Return 1-based line number of first line containing text after after_line."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i > after_line and text in line:
                return i
    raise RuntimeError(f"{path}: no line containing {text!r} after line {after_line}")


def _apply_meminfo_edits(path):
    """Apply the two meminfo.c edits in place (includes + pr_info)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    # First edit: after "#include <linux/zswap.h>", add the two includes.
    i = next(idx for idx, ln in enumerate(lines) if "#include <linux/zswap.h>" in ln)
    for line in ['#include "klp_test_header1.h"\n', '#include "klp_test_header2.h"\n']:
        lines.insert(i + 1, line)
        i += 1
    # Second edit: after last auto var in meminfo_proc_show ("int lru;"), add the two pr_info lines.
    start = next(idx for idx, ln in enumerate(lines) if "static int meminfo_proc_show" in ln)
    j = next(idx for idx, ln in enumerate(lines[start:], start) if "int lru;" in ln)
    insert2 = ['\tpr_info(KLP_TEST_MARKER1 "\\n");\n', '\tpr_info(KLP_TEST_MARKER2 "\\n");\n']
    for line in reversed(insert2):
        lines.insert(j + 1, line)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _apply_cmdline_edit(path):
    """Add the pr_info line in cmdline_proc_show."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    i = _find_line_containing(path, "static int cmdline_proc_show") - 1
    # Find the opening brace and insert after it.
    for j in range(i, min(i + 5, len(lines))):
        if lines[j].strip() == "{":
            lines.insert(j + 1, '\tpr_info("klp-build-test: add-remove-file-diff test\\n");\n')
            break
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def generate_patches(test_dir, kernel_root, out_path):
    """
    Generate a patch by building orig/ and patched/ trees and running
    diff -Nupr.  The output is post-processed to strip "diff -Nupr ..."
    lines so the result is strict unified diff that patch applies correctly
    (all hunks, including multi-hunk files).
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

    with tempfile.TemporaryDirectory(prefix="klp-add-remove-diff-") as tmpdir:
        orig = os.path.join(tmpdir, "orig")
        patched = os.path.join(tmpdir, "patched")
        os.makedirs(orig, exist_ok=True)
        os.makedirs(patched, exist_ok=True)

        # Copy files that exist in the kernel into orig (and patched).
        # Doc file
        doc_orig = os.path.join(orig, doc_rel)
        doc_patched = os.path.join(patched, doc_rel)
        os.makedirs(os.path.dirname(doc_orig), exist_ok=True)
        shutil.copy2(doc_path, doc_orig)
        os.makedirs(os.path.dirname(doc_patched), exist_ok=True)
        shutil.copy2(doc_path, doc_patched)

        # meminfo.c and cmdline.c
        for name in ("fs/proc/meminfo.c", "fs/proc/cmdline.c"):
            src = os.path.join(kernel_root, name)
            if not os.path.isfile(src):
                raise RuntimeError(f"{name} not found")
            d_orig = os.path.join(orig, name)
            d_patched = os.path.join(patched, name)
            os.makedirs(os.path.dirname(d_orig), exist_ok=True)
            shutil.copy2(src, d_orig)
            os.makedirs(os.path.dirname(d_patched), exist_ok=True)
            shutil.copy2(src, d_patched)

        # Patched tree: remove doc, add headers, edit meminfo and cmdline.
        os.remove(doc_patched)
        for hname, content in (
            ("fs/proc/klp_test_header1.h", _KLP_HEADER1),
            ("fs/proc/klp_test_header2.h", _KLP_HEADER2),
        ):
            p = os.path.join(patched, hname)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        _apply_meminfo_edits(os.path.join(patched, "fs/proc/meminfo.c"))
        _apply_cmdline_edit(os.path.join(patched, "fs/proc/cmdline.c"))

        # Run diff -Nupr orig patched.
        result = subprocess.run(
            ["diff", "-Nupr", "orig", "patched"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        diff_out = result.stdout
        if result.returncode not in (0, 1):
            raise RuntimeError(f"diff -Nupr failed: {result.stderr!r}")
        if not diff_out and result.returncode == 0:
            raise RuntimeError("diff produced no output")

        # Strip "diff -Nupr ..." lines so patch applies all hunks (strict unified diff).
        lines = [ln for ln in diff_out.splitlines(keepends=True) if not ln.startswith("diff -Nupr ")]
        body = "".join(lines)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_PATCH_HEADER)
        f.write(body)
    return [out_path]


def verify(*, ko_path=None, tmp_dir=None, results=None, **kwargs):
    if ko_path:
        verify_ko_exists(ko_path, results=results)
        verify_elf_section(ko_path, ".klp.rela.vmlinux..text", results=results)
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: meminfo_proc_show", results=results)
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show", results=results)
