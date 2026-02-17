# SPDX-License-Identifier: GPL-2.0
"""Add and remove files using git format-patch style (generated patch)."""

import hashlib
import os

from verification import (
    verify_ko_exists,
    verify_elf_section,
    verify_diff_log_contains,
)

EXPECT_SUCCESS = True

# New-file content for index hashes (must match the patch body).
_KLP_HEADER1_CONTENT = '''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _KLP_TEST_HEADER1_H
#define _KLP_TEST_HEADER1_H

#define KLP_TEST_MARKER1 "klp-build-test: header1 included"
#endif
'''
_KLP_HEADER2_CONTENT = '''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _KLP_TEST_HEADER2_H
#define _KLP_TEST_HEADER2_H

#define KLP_TEST_MARKER2 "klp-build-test: header2 included"
#endif
'''


def _git_blob_abbrev(content):
    """Return 12-char hex abbreviation of git blob SHA-1 for the given bytes."""
    blob = b"blob %d\0" % len(content) + content
    return hashlib.sha1(blob).hexdigest()[:12]


def _find_line_containing(path, text, after_line=0):
    """Return 1-based line number of first line containing text after after_line."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i > after_line and text in line:
                return i
    raise RuntimeError(f"{path}: no line containing {text!r} after line {after_line}")


def _read_lines(path, start_1based, count):
    """Return list of lines (with newlines) for the given 1-based range."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start_0 = start_1based - 1
    return lines[start_0:start_0 + count]


def _meminfo_hunks(kernel_root):
    """Compute (start, old_len, new_len, context_lines, inserted) for both meminfo hunks."""
    path = os.path.join(kernel_root, "fs", "proc", "meminfo.c")
    if not os.path.isfile(path):
        raise RuntimeError("fs/proc/meminfo.c not found")
    # First hunk: include block. Find "#include <linux/zswap.h>"; 6 old lines, 8 new.
    start1 = _find_line_containing(path, "#include <linux/zswap.h>")
    # Read 2 leading context + 6 lines (zswap..blank) for the hunk body.
    ctx = _read_lines(path, start1 - 2, 8)
    inserted1 = ['#include "klp_test_header1.h"\n', '#include "klp_test_header2.h"\n']
    # Second hunk: after last auto var ("int lru;") in meminfo_proc_show.
    after = _find_line_containing(path, "static int meminfo_proc_show")
    start2 = _find_line_containing(path, "int lru;", after_line=after)
    m2_start = start2 - 3  # hunk starts 3 lines before int lru
    ctx2 = _read_lines(path, m2_start, 6)
    inserted2 = [
        '\tpr_info(KLP_TEST_MARKER1 "\\n");\n',
        '\tpr_info(KLP_TEST_MARKER2 "\\n");\n',
    ]
    return (
        (start1, 6, 8, ctx, inserted1),
        (m2_start, 6, 8, ctx2, inserted2),
    )


def _cmdline_hunk(kernel_root):
    """Compute (start_1based, old_len, new_len, context_lines, inserted) for cmdline hunk."""
    path = os.path.join(kernel_root, "fs", "proc", "cmdline.c")
    if not os.path.isfile(path):
        raise RuntimeError("fs/proc/cmdline.c not found")
    # Include the blank line before the function so @@ start matches (patch shows "\n\n" then body).
    start = _find_line_containing(path, "static int cmdline_proc_show") - 1
    ctx = _read_lines(path, start, 7)
    inserted = ['\tpr_info("klp-build-test: add-remove-file-git test\\n");\n']
    return (start, 7, 8, ctx, inserted)


def _patched_meminfo_content(kernel_root):
    """Return meminfo.c content with the two edits applied (for index new-hash)."""
    path = os.path.join(kernel_root, "fs", "proc", "meminfo.c")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    i = next(idx for idx, ln in enumerate(lines) if "#include <linux/zswap.h>" in ln)
    for line in ['#include "klp_test_header1.h"\n', '#include "klp_test_header2.h"\n']:
        lines.insert(i + 1, line)
        i += 1
    start = next(idx for idx, ln in enumerate(lines) if "static int meminfo_proc_show" in ln)
    j = next(idx for idx, ln in enumerate(lines[start:], start) if "int lru;" in ln)
    for line in ['\tpr_info(KLP_TEST_MARKER1 "\\n");\n', '\tpr_info(KLP_TEST_MARKER2 "\\n");\n']:
        lines.insert(j + 1, line)
        j += 1
    return "".join(lines)


def _patched_cmdline_content(kernel_root):
    """Return cmdline.c content with the pr_info line inserted (for index new-hash)."""
    path = os.path.join(kernel_root, "fs", "proc", "cmdline.c")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    i = _find_line_containing(path, "static int cmdline_proc_show") - 1
    for j in range(i, min(i + 5, len(lines))):
        if lines[j].strip() == "{":
            lines.insert(j + 1, '\tpr_info("klp-build-test: add-remove-file-git test\\n");\n')
            break
    return "".join(lines)


def _format_context(lines, prefix=" "):
    """Format lines as patch context (space prefix) or + lines."""
    out = []
    for line in lines:
        if not line.endswith("\n"):
            line += "\n"
        out.append(prefix + line)
    return "".join(out)


def generate_patches(test_dir, kernel_root, out_path):
    """
    Generate a patch that removes a documentation file, adds two header files,
    and modifies meminfo.c and cmdline.c. Line numbers and context are read from
    the current tree so the patch applies without drift.
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

    ((m1_start, m1_old, m1_new, m1_ctx, m1_ins), (m2_start, m2_old, m2_new, m2_ctx, m2_ins)) = _meminfo_hunks(kernel_root)

    (c_start, c_old, c_new, c_ctx, c_ins) = _cmdline_hunk(kernel_root)

    # First hunk: we show 2 lines before zswap (cma, endif) then zswap, +2, then 3 after.
    # So @@ start is (start1 - 2), old count 6, new count 8. Use only 3 trailing context lines.
    m1_start_display = m1_start - 2
    m1_body = (
        _format_context(m1_ctx[:3]) +
        "".join("+" + ln for ln in m1_ins) +
        _format_context(m1_ctx[3:6])
    )
    # Build meminfo second hunk: 4 context (3 before + int lru), 2 inserted, 2 context after
    m2_body = (
        _format_context(m2_ctx[:4]) +
        "".join("+" + ln for ln in m2_ins) +
        _format_context(m2_ctx[4:])
    )
    # Build cmdline hunk: blank line, " static...", " {\n", 1 inserted, rest context
    c_body = (
        _format_context(c_ctx[:3]) +
        "".join("+" + ln for ln in c_ins) +
        _format_context(c_ctx[3:])
    )

    # Git-style index hashes for each file (like git diff).
    doc_bytes = "".join(doc_lines).encode("utf-8")
    doc_old_hash = _git_blob_abbrev(doc_bytes)
    h1_hash = _git_blob_abbrev(_KLP_HEADER1_CONTENT.encode("utf-8"))
    h2_hash = _git_blob_abbrev(_KLP_HEADER2_CONTENT.encode("utf-8"))
    meminfo_path = os.path.join(kernel_root, "fs", "proc", "meminfo.c")
    with open(meminfo_path, "rb") as f:
        meminfo_old_hash = _git_blob_abbrev(f.read())
    meminfo_new_hash = _git_blob_abbrev(_patched_meminfo_content(kernel_root).encode("utf-8"))
    cmdline_path = os.path.join(kernel_root, "fs", "proc", "cmdline.c")
    with open(cmdline_path, "rb") as f:
        cmdline_old_hash = _git_blob_abbrev(f.read())
    cmdline_new_hash = _git_blob_abbrev(_patched_cmdline_content(kernel_root).encode("utf-8"))

    patch_content = (
        "From: Test Author <test@example.com>\n"
        "Subject: [PATCH] Add/remove files and update proc (git format)\n\n"
        "Add new headers and meminfo change; remove one doc and update cmdline.\n\n"
        f"diff --git a/{doc_rel} b/{doc_rel}\n"
        "deleted file mode 100644\n"
        f"index {doc_old_hash}..000000000000\n"
        f"--- a/{doc_rel}\n"
        "+++ /dev/null\n"
        f"@@ -1,{len(doc_lines)} +0,0 @@\n"
    )
    for line in doc_lines:
        patch_content += "-" + line
    patch_content += (
        "diff --git a/fs/proc/klp_test_header1.h b/fs/proc/klp_test_header1.h\n"
        "new file mode 100644\n"
        f"index 000000000000..{h1_hash}\n"
        "--- /dev/null\n"
        "+++ b/fs/proc/klp_test_header1.h\n"
        "@@ -0,0 +1,6 @@\n"
        "+/* SPDX-License-Identifier: GPL-2.0 */\n"
        "+#ifndef _KLP_TEST_HEADER1_H\n"
        "+#define _KLP_TEST_HEADER1_H\n"
        "+\n"
        '+#define KLP_TEST_MARKER1 "klp-build-test: header1 included"\n'
        "+#endif\n"
        "diff --git a/fs/proc/klp_test_header2.h b/fs/proc/klp_test_header2.h\n"
        "new file mode 100644\n"
        f"index 000000000000..{h2_hash}\n"
        "--- /dev/null\n"
        "+++ b/fs/proc/klp_test_header2.h\n"
        "@@ -0,0 +1,6 @@\n"
        "+/* SPDX-License-Identifier: GPL-2.0 */\n"
        "+#ifndef _KLP_TEST_HEADER2_H\n"
        "+#define _KLP_TEST_HEADER2_H\n"
        "+\n"
        '+#define KLP_TEST_MARKER2 "klp-build-test: header2 included"\n'
        "+#endif\n"
        "diff --git a/fs/proc/meminfo.c b/fs/proc/meminfo.c\n"
        f"index {meminfo_old_hash}..{meminfo_new_hash} 100644\n"
        "--- a/fs/proc/meminfo.c\n+++ b/fs/proc/meminfo.c\n"
        f"@@ -{m1_start_display},{m1_old} +{m1_start_display},{m1_new} @@\n"
        + m1_body
        + f"@@ -{m2_start},{m2_old} +{m2_start + 2},{m2_new} @@ static int meminfo_proc_show(struct seq_file *m, void *v)\n"
        + m2_body
        + "\n"
        "diff --git a/fs/proc/cmdline.c b/fs/proc/cmdline.c\n"
        f"index {cmdline_old_hash}..{cmdline_new_hash} 100644\n"
        "--- a/fs/proc/cmdline.c\n+++ b/fs/proc/cmdline.c\n"
        f"@@ -{c_start},{c_old} +{c_start},{c_new} @@\n\n"
        + c_body
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(patch_content)
    return [out_path]


def verify(*, ko_path=None, tmp_dir=None, results=None, **kwargs):
    if ko_path:
        verify_ko_exists(ko_path, results=results)
        verify_elf_section(ko_path, ".klp.rela.vmlinux..text", results=results)
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: meminfo_proc_show", results=results)
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show", results=results)
