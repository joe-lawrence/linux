# SPDX-License-Identifier: GPL-2.0
"""Multiple independent patch files applied together."""

from verification import (
    verify_ko_exists,
    verify_elf_section,
    verify_diff_log_contains,
)

EXPECT_SUCCESS = True


def verify(*, ko_path=None, tmp_dir=None, **kwargs):
    if ko_path:
        verify_ko_exists(ko_path)
        verify_elf_section(ko_path, ".klp.rela.vmlinux..text")
    if tmp_dir:
        verify_diff_log_contains(tmp_dir, "changed function: cmdline_proc_show")
        verify_diff_log_contains(tmp_dir, "changed function: loadavg_proc_show")
