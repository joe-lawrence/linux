# SPDX-License-Identifier: GPL-2.0
"""Changes spanning multiple files."""

from verification import (
    verify_ko_exists,
    verify_elf_section,
    verify_diff_log_contains,
)

EXPECT_SUCCESS = True


def verify(*, ko_path=None, tmp_dir=None, results=None, **kwargs):
    if ko_path:
        verify_ko_exists(ko_path, results=results)
        verify_elf_section(ko_path, ".klp.rela.vmlinux..text", results=results)
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show", results=results)
        verify_diff_log_contains(tmp_dir, "changed function: version_proc_show", results=results)
