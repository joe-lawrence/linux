# SPDX-License-Identifier: GPL-2.0
"""Patch with incorrect context lines should fail."""

import re

from verification import (
    VerificationError,
    verify_exit_code_nonzero,
)

EXPECT_SUCCESS = False


def verify(*, returncode=None, stderr=None, **kwargs):
    if returncode is not None:
        verify_exit_code_nonzero(returncode)
    if stderr and not re.search(r"did not apply", stderr, re.IGNORECASE):
        raise VerificationError(
            f"Expected patch application error, but got:\n{stderr}"
        )
