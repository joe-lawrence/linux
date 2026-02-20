# SPDX-License-Identifier: GPL-2.0
"""LTO thin: expect klp-build no changes detected and objtool correlate warnings."""

from verification import (
    verify_exit_code_nonzero,
    verify_stderr_matches,
)

EXPECT_SUCCESS = False
REQUIRED_CONFIG = ["CONFIG_LTO_CLANG_THIN"]


def verify(*, returncode=None, stderr=None, results=None, **kwargs):
    if returncode is not None:
        verify_exit_code_nonzero(returncode, results=results)
    if stderr is not None:
        verify_stderr_matches(stderr, r"klp-build: no changes detected", results=results)
        verify_stderr_matches(stderr, r"warning:\s*objtool:\s*correlate", results=results)
