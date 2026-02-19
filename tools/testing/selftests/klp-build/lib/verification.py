# SPDX-License-Identifier: GPL-2.0
"""Load expected.py and verify test outcome."""

import importlib.util
import os
import re
import subprocess
import sys

# Test expects build to succeed (pass) or fail (fail).
EXPECT_SUCCESS = "expect_success"


class VerificationError(Exception):
    """Raised when verify() finds an unexpected result."""


def load_expected(test_dir: str):
    """Load expected.py from test directory. Returns module or None."""
    path = os.path.join(test_dir, "expected.py")
    if not os.path.isfile(path):
        return None
    # expected.py files use "from verification import ..."; ensure lib/ is on path
    _lib_dir = os.path.dirname(os.path.abspath(__file__))
    path_inserted = _lib_dir not in sys.path
    if path_inserted:
        sys.path.insert(0, _lib_dir)
    try:
        spec = importlib.util.spec_from_file_location("expected", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["expected"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if path_inserted and sys.path and sys.path[0] == _lib_dir:
            sys.path.pop(0)


def get_expect_success(test_dir: str) -> bool:
    """True if test expects build to succeed (pass test)."""
    mod = load_expected(test_dir)
    if mod is None:
        return True
    return getattr(mod, EXPECT_SUCCESS, getattr(mod, "EXPECT_SUCCESS", True))


def verify_ko_exists(ko_path, *, results=None) -> None:
    """Verify that the .ko file was created. Raises VerificationError if not."""
    path = str(ko_path)
    if not path or not os.path.isfile(path):
        if results is not None:
            results.append(("verify_ko_exists", False))
        raise VerificationError(f"Expected .ko file not found: {ko_path}")
    if results is not None:
        results.append(("verify_ko_exists", True))


def verify_elf_section(ko_path, section_name: str, *, results=None) -> None:
    """Verify that an ELF section exists in the .ko file."""
    path = str(ko_path) if not isinstance(ko_path, str) else ko_path
    desc = f"verify_elf_section({section_name})"
    if not os.path.isfile(path):
        if results is not None:
            results.append((desc, False))
        raise VerificationError(f"ELF file not found: {path}")
    try:
        from elftools.elf.elffile import ELFFile
        with open(path, "rb") as f:
            elf = ELFFile(f)
            sections = [s.name for s in elf.iter_sections()]
    except ImportError:
        result = subprocess.run(
            ["readelf", "-S", "-W", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            if results is not None:
                results.append((desc, False))
            raise VerificationError(f"readelf failed: {path}")
        sections = []
        for line in result.stdout.splitlines():
            m = re.match(r"\s*\[\s*\d+\]\s+(\S+)", line)
            if m:
                name = m.group(1)
                if name and name != "NULL":
                    sections.append(name)
    except Exception as e:
        if results is not None:
            results.append((desc, False))
        raise VerificationError(f"Failed to parse ELF {path}: {e}")
    if section_name not in sections:
        if results is not None:
            results.append((desc, False))
        raise VerificationError(
            f"Section '{section_name}' not found in {os.path.basename(path)}; "
            f"available: {', '.join(sections[:20])}{'...' if len(sections) > 20 else ''}"
        )
    if results is not None:
        results.append((desc, True))


def verify_diff_log_contains(tmp_dir, pattern: str, *, results=None) -> None:
    """Verify that klp-tmp/diff/diff.log contains the given pattern."""
    base = str(tmp_dir)
    diff_log = os.path.join(base, "diff", "diff.log")
    desc = f"verify_diff_log_contains({pattern!r})"
    if not os.path.isfile(diff_log):
        if results is not None:
            results.append((desc, False))
        raise VerificationError(f"diff.log not found: {diff_log}")
    with open(diff_log, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if pattern not in content:
        if results is not None:
            results.append((desc, False))
        raise VerificationError(
            f"Pattern {pattern!r} not found in diff.log\nContent (first 500 chars):\n{content[:500]}..."
        )
    if results is not None:
        results.append((desc, True))


def verify_exit_code_nonzero(returncode: int, *, results=None) -> None:
    """Raise VerificationError if returncode is 0."""
    if returncode == 0:
        raise VerificationError("Expected non-zero exit code")
    if results is not None:
        results.append(("exit code non-zero (expected failure)", True))


def verify_stderr_matches(stderr: str, pattern: str, *, results=None) -> None:
    """Raise VerificationError if stderr does not match the regex pattern."""
    if not stderr or not re.search(pattern, stderr, re.IGNORECASE):
        raise VerificationError(f"Expected stderr to match {pattern!r}")
    if results is not None:
        results.append((f"stderr matched pattern {pattern!r}", True))


def run_verify(test_dir: str, **kwargs) -> None:
    """Run expected.verify(**kwargs) if present. Raises on failure."""
    mod = load_expected(test_dir)
    if mod is None:
        return
    verify = getattr(mod, "verify", None)
    if verify is not None and callable(verify):
        verify(**kwargs)
