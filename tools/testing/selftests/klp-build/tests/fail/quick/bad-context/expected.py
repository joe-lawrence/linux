# SPDX-License-Identifier: GPL-2.0
"""Patch with incorrect context lines should fail."""

from verification import (
    verify_exit_code_nonzero,
    verify_stderr_matches,
)

EXPECT_SUCCESS = False


def verify(*, returncode=None, stderr=None, **kwargs):
    if returncode is not None:
        verify_exit_code_nonzero(returncode)
    if stderr is not None:
        verify_stderr_matches(stderr, r"did not apply")
