#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Generate a plain-text report from artifacts/ (profile × test matrix).
Writes artifacts/report.txt: build and runtime results per test, staggered header.
"""

import re
import sys
from pathlib import Path

# Add lib to path so we can import from lib
SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import get_artifacts_dir, get_test_dir
from lib.verification import get_expect_success


# Build and runtime logs both use Result:     SUCCESS | FAILURE
RESULT_SUCCESS = re.compile(r"Result:\s+SUCCESS")
RESULT_FAILURE = re.compile(r"Result:\s+FAILURE")

# Layout: "build:   " / "runtime: " (9 chars) + test name + padding, then fixed-width result columns
ROW_PREFIX_LEN = 9
ROW_LABEL_PADDING = 6
COL_WIDTH = 4
COL_SPACE = 2
HEADER_TEXT_OFFSET = 8


def discover_profiles(artifacts_root: Path) -> list[str]:
    """Return sorted list of profile names (directories under artifacts/)."""
    if not artifacts_root.exists():
        return []
    return sorted(p.name for p in artifacts_root.iterdir() if p.is_dir() and not p.name.startswith("."))


def discover_tests(artifacts_root: Path, profiles: list[str]) -> list[str]:
    """Return sorted union of test names that have build-test.log or runtime-test.log under any profile."""
    tests = set()
    for name in profiles:
        profile_dir = artifacts_root / name
        if not profile_dir.is_dir():
            continue
        for d in profile_dir.iterdir():
            if d.is_dir() and ((d / "build-test.log").exists() or (d / "runtime-test.log").exists()):
                tests.add(d.name)
    return sorted(tests)


def _get_expect_success_for_test(test_name: str) -> bool:
    """True if test expects success (pass/), False if it expects failure (fail/). Default True if not found."""
    tests_dir = get_test_dir() / "tests"
    for outcome in ("pass", "fail"):
        for speed in ("quick", "long"):
            test_dir = tests_dir / outcome / speed / test_name
            if test_dir.is_dir() and (test_dir / "expected.py").exists():
                return get_expect_success(str(test_dir))
    return True


def _read_log(artifacts_root: Path, profile: str, test: str, filename: str) -> str:
    path = artifacts_root / profile / test / filename
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def get_build_result(artifacts_root: Path, profile: str, test: str) -> str:
    """Return ok if result matches expectation (pass/ or fail/), FAIL if not, skip if no log."""
    text = _read_log(artifacts_root, profile, test, "build-test.log")
    if not text:
        return "skip"
    if RESULT_SUCCESS.search(text):
        actual_success = True
    elif RESULT_FAILURE.search(text):
        actual_success = False
    else:
        return "skip"
    expect_success = _get_expect_success_for_test(test)
    return "ok" if actual_success == expect_success else "FAIL"


def get_runtime_result(artifacts_root: Path, profile: str, test: str) -> str:
    """Return ok if result matches expectation, FAIL if not, -- if expected-fail (runtime not run), else skip."""
    text = _read_log(artifacts_root, profile, test, "runtime-test.log")
    expect_success = _get_expect_success_for_test(test)
    if not text:
        return "--" if not expect_success else "skip"
    if RESULT_SUCCESS.search(text):
        actual_success = True
    elif RESULT_FAILURE.search(text):
        actual_success = False
    else:
        return "--" if not expect_success else "skip"
    return "ok" if actual_success == expect_success else "FAIL"


def _render_header_and_connector(
    profiles: list[str],
    row_label_width: int,
    num_cols: int,
) -> list[str]:
    """Staggered header + connector line; draw-by-intersections. All header text starts at same X."""
    col_x_positions = [row_label_width + i * (COL_WIDTH + COL_SPACE) for i in range(num_cols)]
    text_start_x = col_x_positions[-1] + HEADER_TEXT_OFFSET
    lines = []
    for i in range(num_cols):
        line = ""
        for x in range(text_start_x):
            if x in col_x_positions[:i]:
                line += "|"
            elif x == col_x_positions[i]:
                line += "."
            elif x > col_x_positions[i]:
                line += "-"
            else:
                line += " "
        line += " " + profiles[i]
        lines.append(line)
    connector = ""
    for x in range(text_start_x):
        connector += "|" if x in col_x_positions else " "
    lines.append(connector)
    lines.append("")
    return lines


def _count_results(
    artifacts_root: Path,
    profiles: list[str],
    tests: list[str],
) -> tuple[int, int, int, int, int, int, int]:
    """Return (build_ok, build_fail, build_skip, runtime_ok, runtime_fail, runtime_skip, runtime_na)."""
    b_ok = b_fail = b_skip = r_ok = r_fail = r_skip = r_na = 0
    for test in tests:
        for profile in profiles:
            br = get_build_result(artifacts_root, profile, test)
            rr = get_runtime_result(artifacts_root, profile, test)
            if br == "ok":
                b_ok += 1
            elif br == "FAIL":
                b_fail += 1
            else:
                b_skip += 1
            if rr == "ok":
                r_ok += 1
            elif rr == "FAIL":
                r_fail += 1
            elif rr == "--":
                r_na += 1
            else:
                r_skip += 1
    return (b_ok, b_fail, b_skip, r_ok, r_fail, r_skip, r_na)


def generate_report(
    artifacts_root: Path,
    profiles: list[str],
    tests: list[str],
) -> list[str]:
    """Full report: title, summary, details (staggered header + data)."""
    lines = [
        "klp-build kselftest report",
        "==========================",
        "",
    ]
    if not profiles:
        return lines

    num_cols = len(profiles)
    max_test_len = max(len(t) for t in tests) if tests else 0
    test_col_width = max_test_len + ROW_LABEL_PADDING
    row_label_width = ROW_PREFIX_LEN + test_col_width

    b_ok, b_fail, b_skip, r_ok, r_fail, r_skip, r_na = _count_results(artifacts_root, profiles, tests)
    lines.extend([
        "Summary",
        "-------",
        f"build:   {b_ok} ok, {b_fail} FAIL, {b_skip} skip",
        f"runtime: {r_ok} ok, {r_fail} FAIL, {r_skip} skip, {r_na} n/a",
        "",
        "Details",
        "-------",
        "",
    ])
    lines.extend(_render_header_and_connector(profiles, row_label_width, num_cols))

    for test in tests:
        build_results = [get_build_result(artifacts_root, p, test) for p in profiles]
        runtime_results = [get_runtime_result(artifacts_root, p, test) for p in profiles]
        build_row = "build:   " + test.ljust(test_col_width)
        runtime_row = "runtime: " + test.ljust(test_col_width)
        for c in range(num_cols):
            build_row += build_results[c].ljust(COL_WIDTH) + (COL_SPACE * " " if c < num_cols - 1 else "")
            runtime_row += runtime_results[c].ljust(COL_WIDTH) + (COL_SPACE * " " if c < num_cols - 1 else "")
        lines.append(build_row)
        lines.append(runtime_row)
        lines.append("")

    return lines


def main() -> int:
    artifacts_root = get_artifacts_dir()
    profiles = discover_profiles(artifacts_root)
    tests = discover_tests(artifacts_root, profiles)

    out_path = artifacts_root / "report.txt"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    out_lines = generate_report(artifacts_root, profiles, tests)
    if not profiles:
        out_lines.append("(no profile directories under artifacts/)")
    elif not tests:
        out_lines.append("(no tests with build-test.log or runtime-test.log found)")

    out_path.write_text("\n".join(out_lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
