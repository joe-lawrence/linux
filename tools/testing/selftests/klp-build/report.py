#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Generate a plain-text report from artifacts/ (profile x test matrix).
Writes artifacts/report.txt: build and runtime results per test, staggered header,
grouped by tree type.
"""

import re
import subprocess
import sys
from pathlib import Path

# Add lib to path so we can import from lib
SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import get_artifacts_dir, get_test_dir, get_kernel_src_dir
from lib.verification import get_expect_success

TREE_TYPES = ("current-tree", "patched-tree")

RESULT_SUCCESS = re.compile(r"Result:\s+SUCCESS")
RESULT_FAILURE = re.compile(r"Result:\s+FAILURE")
VERDICT_RE = re.compile(r"Verdict:\s+(\S+)")

ROW_PREFIX_LEN = 9
ROW_LABEL_PADDING = 6
COL_WIDTH = 5
COL_SPACE = 2
HEADER_TEXT_OFFSET = 8


MAX_COMMITS_SHOWN = 10


def _git(*args, cwd=None):
    """Run a git command and return stripped stdout, or None on failure."""
    try:
        r = subprocess.run(
            ["git", *args], capture_output=True, text=True,
            timeout=5, cwd=cwd,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def gather_git_summary() -> dict | None:
    """Collect git describe, branch, and commits-since-tag from the kernel tree.

    Returns a dict with keys: describe, branch, tag, commits (list of
    oneline strings), total (int count since tag).  Returns None when
    the kernel source is not inside a git repo.
    """
    cwd = str(get_kernel_src_dir())

    describe = _git("describe", "--dirty", "--always", cwd=cwd)
    if describe is None:
        return None

    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    if branch == "HEAD":
        branch = None

    tag = _git("describe", "--abbrev=0", "--always", cwd=cwd)
    commits: list[str] = []
    total = 0
    if tag and tag != describe:
        log = _git("log", "--oneline", f"{tag}..HEAD", cwd=cwd)
        if log:
            commits = log.splitlines()
            total = len(commits)
            if total > MAX_COMMITS_SHOWN:
                commits = commits[:MAX_COMMITS_SHOWN]

    return {
        "describe": describe,
        "branch": branch,
        "tag": tag,
        "commits": commits,
        "total": total,
    }


def _format_git_text(info: dict) -> list[str]:
    """Format git summary as plain-text lines."""
    header = f"Kernel: {info['describe']}"
    if info.get("branch"):
        header += f"  (branch: {info['branch']})"
    lines = [header]
    for c in info["commits"]:
        lines.append(f"  {c}")
    if info["total"] > len(info["commits"]):
        lines.append(f"  ... and {info['total'] - len(info['commits'])} "
                      f"more since {info['tag']}")
    elif info["total"] > 0:
        lines.append(f"  ({info['total']} commits since {info['tag']})")
    return lines


def _format_git_html(info: dict) -> str:
    """Format git summary as an HTML block."""
    import html as _html
    header = _html.escape(info["describe"])
    branch = ""
    if info.get("branch"):
        branch = (f' <span style="color:#888">'
                  f'(branch: {_html.escape(info["branch"])})</span>')
    parts = [f"<b>Kernel:</b> <code>{header}</code>{branch}"]
    if info["commits"]:
        parts.append('<pre style="margin:.4rem 0 0 1rem; font-size:.82rem; '
                     'line-height:1.5; color:#555">')
        for c in info["commits"]:
            parts.append(_html.escape(c))
        if info["total"] > len(info["commits"]):
            parts.append(f'... and {info["total"] - len(info["commits"])} '
                         f'more since {_html.escape(info["tag"])}')
        elif info["total"] > 0:
            parts.append(f'({info["total"]} commits since '
                         f'{_html.escape(info["tag"])})')
        parts.append("</pre>")
    return "\n".join(parts)


def discover_profiles(artifacts_root: Path) -> list[str]:
    """Return sorted list of profile names (directories under artifacts/)."""
    if not artifacts_root.exists():
        return []
    return sorted(
        p.name for p in artifacts_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def discover_tree_types(artifacts_root: Path, profiles: list[str]) -> list[str]:
    """Return tree types that have at least one test artifact."""
    found = set()
    for profile in profiles:
        profile_dir = artifacts_root / profile
        if not profile_dir.is_dir():
            continue
        for tree_type in TREE_TYPES:
            tree_dir = profile_dir / tree_type
            if tree_dir.is_dir() and any(tree_dir.iterdir()):
                found.add(tree_type)
        # Legacy flat layout: test dirs directly under profile (no tree-type level)
        for d in profile_dir.iterdir():
            if d.is_dir() and d.name not in TREE_TYPES and (
                    (d / "build-test.log").exists()
                    or (d / "runtime-test.log").exists()):
                found.add("unknown")
    result = [t for t in TREE_TYPES if t in found]
    if "unknown" in found:
        result.append("unknown")
    return result


def discover_tests(
    artifacts_root: Path, profiles: list[str], tree_type: str,
) -> list[str]:
    """Return sorted test names for a specific tree type across all profiles."""
    tests = set()
    for profile in profiles:
        if tree_type == "unknown":
            profile_dir = artifacts_root / profile
            if not profile_dir.is_dir():
                continue
            for d in profile_dir.iterdir():
                if d.is_dir() and d.name not in TREE_TYPES and (
                        (d / "build-test.log").exists()
                        or (d / "runtime-test.log").exists()):
                    tests.add(d.name)
        else:
            tree_dir = artifacts_root / profile / tree_type
            if not tree_dir.is_dir():
                continue
            for d in tree_dir.iterdir():
                if d.is_dir() and (
                        (d / "build-test.log").exists()
                        or (d / "runtime-test.log").exists()):
                    tests.add(d.name)
    return sorted(tests)



def _get_expect_success_for_test(test_name: str) -> bool:
    """True if test expects success (pass/), False if it expects failure (fail/)."""
    tests_dir = get_test_dir() / "tests"
    for test_type in ("current-tree", "patched-tree"):
        for outcome in ("pass", "fail"):
            if test_type == "current-tree":
                for speed in ("quick", "long"):
                    test_dir = tests_dir / test_type / outcome / speed / test_name
                    if test_dir.is_dir() and (test_dir / "expected.py").exists():
                        return get_expect_success(str(test_dir))
            else:
                test_dir = tests_dir / test_type / outcome / test_name
                if test_dir.is_dir() and (test_dir / "expected.py").exists():
                    return get_expect_success(str(test_dir))
    return True


def _read_log(
    artifacts_root: Path, profile: str, tree_type: str, test: str,
    filename: str,
) -> str:
    if tree_type == "unknown":
        path = artifacts_root / profile / test / filename
    else:
        path = artifacts_root / profile / tree_type / test / filename
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def _parse_result(text: str) -> bool | None:
    """Parse Result: line.  Returns True for SUCCESS, False for FAILURE, None if not found."""
    if RESULT_SUCCESS.search(text):
        return True
    if RESULT_FAILURE.search(text):
        return False
    return None


def _parse_verdict(text: str) -> str | None:
    """Parse Verdict: line.  Returns pass/FAIL/xfail/XPASS, or None if absent."""
    m = VERDICT_RE.search(text)
    if not m:
        return None
    v = m.group(1)
    if v == "PASS":
        return "pass"
    return v


def get_build_result(
    artifacts_root: Path, profile: str, tree_type: str, test: str,
) -> str:
    """Return pass/FAIL/xfail/XPASS/skip for a build result."""
    text = _read_log(artifacts_root, profile, tree_type, test, "build-test.log")
    verdict = _parse_verdict(text)
    if verdict is not None:
        return verdict
    # Fallback for logs without new Verdict format
    actual_success = _parse_result(text)
    if actual_success is None:
        return "skip"
    expect_success = _get_expect_success_for_test(test)
    if expect_success:
        return "pass" if actual_success else "FAIL"
    return "XPASS" if actual_success else "xfail"


def get_runtime_result(
    artifacts_root: Path, profile: str, tree_type: str, test: str,
) -> str:
    """Return pass/FAIL/xfail/XPASS/--/skip for a runtime result."""
    text = _read_log(artifacts_root, profile, tree_type, test, "runtime-test.log")
    verdict = _parse_verdict(text)
    if verdict is not None:
        return verdict
    # Fallback for logs without new Verdict format
    expect_success = _get_expect_success_for_test(test)
    actual_success = _parse_result(text)
    if actual_success is None:
        return "--" if not expect_success else "skip"
    if expect_success:
        return "pass" if actual_success else "FAIL"
    return "XPASS" if actual_success else "xfail"


def _render_header_and_connector(
    profiles: list[str],
    row_label_width: int,
    num_cols: int,
) -> list[str]:
    """Staggered header + connector line."""
    col_x_positions = [
        row_label_width + i * (COL_WIDTH + COL_SPACE) for i in range(num_cols)
    ]
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
    tree_types: list[str],
    tests_by_tree: dict[str, list[str]],
) -> dict[str, int]:
    """Return counts dict with keys: b_pass, b_fail, b_skip, b_xfail, b_xpass,
       r_pass, r_fail, r_skip, r_na, r_xfail, r_xpass."""
    c = {k: 0 for k in ("b_pass", "b_fail", "b_skip", "b_xfail", "b_xpass",
                         "r_pass", "r_fail", "r_skip", "r_na", "r_xfail",
                         "r_xpass")}
    for tree_type in tree_types:
        for test in tests_by_tree.get(tree_type, []):
            for profile in profiles:
                br = get_build_result(artifacts_root, profile, tree_type, test)
                rr = get_runtime_result(artifacts_root, profile, tree_type, test)
                if br == "pass":     c["b_pass"] += 1
                elif br == "FAIL":   c["b_fail"] += 1
                elif br == "xfail":  c["b_xfail"] += 1
                elif br == "XPASS":  c["b_xpass"] += 1
                else:                c["b_skip"] += 1
                if rr == "pass":     c["r_pass"] += 1
                elif rr == "FAIL":   c["r_fail"] += 1
                elif rr == "xfail":  c["r_xfail"] += 1
                elif rr == "XPASS":  c["r_xpass"] += 1
                elif rr == "--":     c["r_na"] += 1
                else:                c["r_skip"] += 1
    return c


def generate_report(
    artifacts_root: Path,
    profiles: list[str],
    tree_types: list[str],
    tests_by_tree: dict[str, list[str]],
    git_info: dict | None = None,
) -> list[str]:
    """Full report: title, summary, details (staggered header + data grouped by tree type)."""
    lines = [
        "klp-build kselftest report",
        "==========================",
        "",
    ]
    if git_info:
        lines.extend(_format_git_text(git_info))
        lines.append("")
    if not profiles:
        return lines

    all_tests = [t for tt in tree_types for t in tests_by_tree.get(tt, [])]
    num_cols = len(profiles)
    max_test_len = max(len(t) for t in all_tests) if all_tests else 0
    test_col_width = max_test_len + ROW_LABEL_PADDING
    row_label_width = ROW_PREFIX_LEN + test_col_width

    c = _count_results(artifacts_root, profiles, tree_types, tests_by_tree)
    b_parts = [f"{c['b_pass']} pass"]
    if c["b_xfail"]:
        b_parts.append(f"{c['b_xfail']} xfail")
    b_parts.append(f"{c['b_fail']} FAIL")
    if c["b_xpass"]:
        b_parts.append(f"{c['b_xpass']} XPASS")
    b_parts.append(f"{c['b_skip']} skip")
    r_parts = [f"{c['r_pass']} pass"]
    if c["r_xfail"]:
        r_parts.append(f"{c['r_xfail']} xfail")
    r_parts.append(f"{c['r_fail']} FAIL")
    if c["r_xpass"]:
        r_parts.append(f"{c['r_xpass']} XPASS")
    r_parts.extend([f"{c['r_skip']} skip", f"{c['r_na']} n/a"])
    lines.extend([
        "Summary",
        "-------",
        f"build:   {', '.join(b_parts)}",
        f"runtime: {', '.join(r_parts)}",
        "",
        "Details",
        "-------",
        "",
    ])
    lines.extend(_render_header_and_connector(profiles, row_label_width, num_cols))

    for ti, tree_type in enumerate(tree_types):
        tests = tests_by_tree.get(tree_type, [])
        if not tests:
            continue
        if ti > 0:
            lines.append("")
        lines.append(tree_type)
        lines.append("-" * len(tree_type))

        for test in tests:
            build_results = [
                get_build_result(artifacts_root, p, tree_type, test)
                for p in profiles
            ]
            runtime_results = [
                get_runtime_result(artifacts_root, p, tree_type, test)
                for p in profiles
            ]
            build_row = "build:   " + test.ljust(test_col_width)
            runtime_row = "runtime: " + test.ljust(test_col_width)
            for c in range(num_cols):
                sep = COL_SPACE * " " if c < num_cols - 1 else ""
                build_row += build_results[c].ljust(COL_WIDTH) + sep
                runtime_row += runtime_results[c].ljust(COL_WIDTH) + sep
            lines.append(build_row)
            lines.append(runtime_row)
            lines.append("")

    return lines


def _log_path(profile: str, tree_type: str, test: str, filename: str) -> str:
    """Return the relative path from artifacts/ to a log file."""
    if tree_type == "unknown":
        return f"{profile}/{test}/{filename}"
    return f"{profile}/{tree_type}/{test}/{filename}"


def _log_exists(artifacts_root: Path, profile: str, tree_type: str,
                test: str, filename: str) -> bool:
    if tree_type == "unknown":
        return (artifacts_root / profile / test / filename).exists()
    return (artifacts_root / profile / tree_type / test / filename).exists()


# ---------------------------------------------------------------------------
# Profile display helpers
# ---------------------------------------------------------------------------

_ICON_RHEL = (
    'M16.009 13.386c1.577 0 3.86-.326 3.86-2.202a1.765 1.765 0 0 0-.04-.431'
    'l-.94-4.08c-.216-.898-.406-1.305-1.982-2.093-1.223-.625-3.888-1.658-4.676'
    '-1.658-.733 0-.947.946-1.822.946-.842 0-1.467-.706-2.255-.706-.757 0-1.25'
    '.515-1.63 1.576 0 0-1.06 2.99-1.197 3.424a.81.81 0 0 0-.028.245c0 1.162'
    ' 4.577 4.974 10.71 4.974m4.101-1.435c.218 1.032.218 1.14.218 1.277 0'
    ' 1.765-1.984 2.745-4.593 2.745-5.895.004-11.06-3.451-11.06-5.734a2.326'
    ' 2.326 0 0 1 .19-.925C2.746 9.415 0 9.794 0 12.217c0 3.969 9.405 8.861'
    ' 16.851 8.861 5.71 0 7.149-2.582 7.149-4.62 0-1.605-1.387-3.425-3.887-4.512'
)

_ICON_FEDORA = (
    'M12.001 0C5.376 0 .008 5.369.004 11.992H.002v9.287h.002A2.726 2.726 0 0 0'
    ' 2.73 24h9.275c6.626-.004 11.993-5.372 11.993-11.997C23.998 5.375 18.628 0'
    ' 12 0zm2.431 4.94c2.015 0 3.917 1.543 3.917 3.671 0 .197.001.395-.03.619a'
    '1.002 1.002 0 0 1-1.137.893 1.002 1.002 0 0 1-.842-1.175 2.61 2.61 0 0 0'
    ' .013-.337c0-1.207-.987-1.672-1.92-1.672-.934 0-1.775.784-1.777 1.672.016'
    ' 1.027 0 2.046 0 3.07l1.732-.012c1.352-.028 1.368 2.009.016 1.998l-1.748'
    '.013c-.004.826.006.677.002 1.093 0 0 .015 1.01-.016 1.776-.209 2.25-2.124'
    ' 4.046-4.424 4.046-2.438 0-4.448-1.993-4.448-4.437.073-2.515 2.078-4.492'
    ' 4.603-4.469l1.409-.01v1.996l-1.409.013h-.007c-1.388.04-2.577.984-2.6 2.47'
    'a2.438 2.438 0 0 0 2.452 2.439c1.356 0 2.441-.987 2.441-2.437l-.001-7.557'
    'c0-.14.005-.252.02-.407.23-1.848 1.883-3.256 3.754-3.256z'
)

_ICON_OPENSUSE = (
    'M10.724 0a12 12 0 0 0-9.448 4.623c1.464.391 2.5.727 2.81.832.005-.19.037'
    '-1.893.037-1.893s.004-.04.025-.06c.026-.026.065-.018.065-.018.385.056 8.602'
    ' 1.274 12.066 3.292.427.25.638.517.902.786.958.99 2.223 5.108 2.359 5.957'
    '.005.033-.036.07-.054.083a5.177 5.177 0 0 1-.313.228c-.82.55-2.708 1.872'
    '-5.13 1.656-2.176-.193-5.018-1.44-8.445-3.699.336.79.668 1.58 1 2.371.497'
    '.258 5.287 2.7 7.651 2.651 1.904-.04 3.941-.968 4.756-1.458 0 0 .179-.108'
    '.257-.048.085.066.061.167.041.27-.05.234-.164.66-.242.863l-.065.165c-.093'
    '.25-.183.482-.356.625-.48.436-1.246.784-2.446 1.305-1.855.812-4.865 1.328'
    '-7.66 1.31-1.001-.022-1.968-.133-2.817-.232-1.743-.197-3.161-.357-4.026'
    '.269A12 12 0 0 0 10.724 24a12 12 0 0 0 12-12 12 12 0 0 0-12-12zM13.4'
    ' 6.963a3.503 3.503 0 0 0-2.521.942 3.498 3.498 0 0 0-1.114 2.449 3.528'
    ' 3.528 0 0 0 3.39 3.64 3.48 3.48 0 0 0 2.524-.946 3.504 3.504 0 0 0'
    ' 1.114-2.446 3.527 3.527 0 0 0-3.393-3.64zm-.03 1.035a2.458 2.458 0 0 1'
    ' 2.368 2.539 2.43 2.43 0 0 1-.774 1.706 2.456 2.456 0 0 1-1.762.659'
    ' 2.461 2.461 0 0 1-2.364-2.542c.02-.655.3-1.26.777-1.707a2.419 2.419 0 0'
    ' 1 1.756-.655zm.402 1.23c-.602 0-1.087.325-1.087.727 0 .4.485.725 1.087'
    '.725.6 0 1.088-.326 1.088-.725 0-.402-.487-.726-1.088-.726Z'
)

_ICON_UBUNTU = (
    'M17.61.455a3.41 3.41 0 0 0-3.41 3.41 3.41 3.41 0 0 0 3.41 3.41 3.41 3.41'
    ' 0 0 0 3.41-3.41 3.41 3.41 0 0 0-3.41-3.41zM12.92.8C8.923.777 5.137 2.941'
    ' 3.148 6.451a4.5 4.5 0 0 1 .26-.007 4.92 4.92 0 0 1 2.585.737A8.316 8.316'
    ' 0 0 1 12.688 3.6 4.944 4.944 0 0 1 13.723.834 11.008 11.008 0 0 0 12.92.8'
    'zm9.226 4.994a4.915 4.915 0 0 1-1.918 2.246 8.36 8.36 0 0 1-.273 8.303'
    ' 4.89 4.89 0 0 1 1.632 2.54 11.156 11.156 0 0 0 .559-13.089zM3.41 7.932'
    'A3.41 3.41 0 0 0 0 11.342a3.41 3.41 0 0 0 3.41 3.409 3.41 3.41 0 0 0'
    ' 3.41-3.41 3.41 3.41 0 0 0-3.41-3.41zm2.027 7.866a4.908 4.908 0 0 1-2.915'
    '.358 11.1 11.1 0 0 0 7.991 6.698 11.234 11.234 0 0 0 2.422.249 4.879 4.879'
    ' 0 0 1-.999-2.85 8.484 8.484 0 0 1-.836-.136 8.304 8.304 0 0 1-5.663-4.32'
    'zm11.405.928a3.41 3.41 0 0 0-3.41 3.41 3.41 3.41 0 0 0 3.41 3.41 3.41'
    ' 3.41 0 0 0 3.41-3.41 3.41 3.41 0 0 0-3.41-3.41z'
)

_ICON_LINUX = (
    'M12.504 0c-.155 0-.315.008-.48.021-4.226.333-3.105 4.807-3.17 6.298-.076'
    ' 1.092-.3 1.953-1.05 3.02-.885 1.051-2.127 2.75-2.716 4.521-.278.832-.41'
    ' 1.684-.287 2.489a.424.424 0 00-.11.135c-.26.268-.45.6-.663.839-.199.199'
    '-.485.267-.797.4-.313.136-.658.269-.864.68-.09.189-.136.394-.132.602 0'
    ' .199.027.4.055.536.058.399.116.728.04.97-.249.68-.28 1.145-.106 1.484.174'
    '.334.535.47.94.601.81.2 1.91.135 2.774.6.926.466 1.866.67 2.616.47.526-.116'
    '.97-.464 1.208-.946.587-.003 1.23-.269 2.26-.334.699-.058 1.574.267 2.577.2'
    '.025.134.063.198.114.333l.003.003c.391.778 1.113 1.132 1.884 1.071.771-.06'
    ' 1.592-.536 2.257-1.306.631-.765 1.683-1.084 2.378-1.503.348-.199.629-.469'
    '.649-.853.023-.4-.2-.811-.714-1.376v-.097l-.003-.003c-.17-.2-.25-.535-.338'
    '-.926-.085-.401-.182-.786-.492-1.046h-.003c-.059-.054-.123-.067-.188-.135'
    'a.357.357 0 00-.19-.064c.431-1.278.264-2.55-.173-3.694-.533-1.41-1.465'
    '-2.638-2.175-3.483-.796-1.005-1.576-1.957-1.56-3.368.026-2.152.236-6.133'
    '-3.544-6.139zm.529 3.405h.013c.213 0 .396.062.584.198.19.135.33.332.438.533'
    '.105.259.158.459.166.724 0-.02.006-.04.006-.06v.105a.086.086 0 01-.004-.021'
    'l-.004-.024a1.807 1.807 0 01-.15.706.953.953 0 01-.213.335.71.71 0 00-.088'
    '-.042c-.104-.045-.198-.064-.284-.133a1.312 1.312 0 00-.22-.066c.05-.06.146'
    '-.133.183-.198.053-.128.082-.264.088-.402v-.02a1.21 1.21 0 00-.061-.4c-.045'
    '-.134-.101-.2-.183-.333-.084-.066-.167-.132-.267-.132h-.016c-.093 0-.176.03'
    '-.262.132a.8.8 0 00-.205.334 1.18 1.18 0 00-.09.4v.019c.002.089.008.179.02'
    '.267-.193-.067-.438-.135-.607-.202a1.635 1.635 0 01-.018-.2v-.02a1.772 1.772'
    ' 0 01.15-.768c.082-.22.232-.406.43-.533a.985.985 0 01.594-.2zm-2.962.059h'
    '.036c.142 0 .27.048.399.135.146.129.264.288.344.465.09.199.14.4.153.667v'
    '.004c.007.134.006.2-.002.266v.08c-.03.007-.056.018-.083.024-.152.055-.274'
    '.135-.393.2.012-.09.013-.18.003-.267v-.015c-.012-.133-.04-.2-.082-.333a.613'
    '.613 0 00-.166-.267.248.248 0 00-.183-.064h-.021c-.071.006-.13.04-.186.132'
    'a.552.552 0 00-.12.27.944.944 0 00-.023.33v.015c.012.135.037.2.08.334.046'
    '.134.098.2.166.268.01.009.02.018.034.024-.07.057-.117.07-.176.136a.304.304'
    ' 0 01-.131.068 2.62 2.62 0 01-.275-.402 1.772 1.772 0 01-.155-.667 1.759'
    ' 1.759 0 01.08-.668 1.43 1.43 0 01.283-.535c.128-.133.26-.2.418-.2zm1.37'
    ' 1.706c.332 0 .733.065 1.216.399.293.2.523.269 1.052.468h.003c.255.136.405'
    '.266.478.399v-.131a.571.571 0 01.016.47c-.123.31-.516.643-1.063.842v.002c'
    '-.268.135-.501.333-.775.465-.276.135-.588.292-1.012.267a1.139 1.139 0 01'
    '-.448-.067 3.566 3.566 0 01-.322-.198c-.195-.135-.363-.332-.612-.465v-.005h'
    '-.005c-.4-.246-.616-.512-.686-.71-.07-.268-.005-.47.193-.6.224-.135.38-.271'
    '.483-.336.104-.074.143-.102.176-.131h.002v-.003c.169-.202.436-.47.839-.601'
    '.139-.036.294-.065.466-.065zm2.8 2.142c.358 1.417 1.196 3.475 1.735 4.473'
    '.286.534.855 1.659 1.102 3.024.156-.005.33.018.513.064.646-1.671-.546-3.467'
    '-1.089-3.966-.22-.2-.232-.335-.123-.335.59.534 1.365 1.572 1.646 2.757.13'
    '.535.16 1.104.021 1.67.067.028.135.06.205.067 1.032.534 1.413.938 1.23'
    ' 1.537v-.043c-.06-.003-.12 0-.18 0h-.016c.151-.467-.182-.825-1.065-1.224'
    '-.915-.4-1.646-.336-1.77.465-.008.043-.013.066-.018.135-.068.023-.139.053'
    '-.209.064-.43.268-.662.669-.793 1.187-.13.533-.17 1.156-.205 1.869v.003c-.02'
    '.334-.17.838-.319 1.35-1.5 1.072-3.58 1.538-5.348.334a2.645 2.645 0 00-.402'
    '-.533 1.45 1.45 0 00-.275-.333c.182 0 .338-.03.465-.067a.615.615 0 00.314'
    '-.334c.108-.267 0-.697-.345-1.163-.345-.467-.931-.995-1.788-1.521-.63-.4'
    '-.986-.87-1.15-1.396-.165-.534-.143-1.085-.015-1.645.245-1.07.873-2.11'
    ' 1.274-2.763.107-.065.037.135-.408.974-.396.751-1.14 2.497-.122 3.854a8.123'
    ' 8.123 0 01.647-2.876c.564-1.278 1.743-3.504 1.836-5.268.048.036.217.135'
    '.289.202.218.133.38.333.59.465.21.201.477.335.876.335.039.003.075.006.11'
    '.006.412 0 .73-.134.997-.268.29-.134.52-.334.74-.4h.005c.467-.135.835-.402'
    ' 1.044-.7zm2.185 8.958c.037.6.343 1.245.882 1.377.588.134 1.434-.333 1.791'
    '-.765l.211-.01c.315-.007.577.01.847.268l.003.003c.208.199.305.53.391.876.085'
    '.4.154.78.409 1.066.486.527.645.906.636 1.14l.003-.007v.018l-.003-.012c-.015'
    '.262-.185.396-.498.595-.63.401-1.746.712-2.457 1.57-.618.737-1.37 1.14-2.036'
    ' 1.191-.664.053-1.237-.2-1.574-.898l-.005-.003c-.21-.4-.12-1.025.056-1.69'
    '.176-.668.428-1.344.463-1.897.037-.714.076-1.335.195-1.814.12-.465.308-.797'
    '.641-.984l.045-.022zm-10.814.049h.01c.053 0 .105.005.157.014.376.055.706.333'
    ' 1.023.752l.91 1.664.003.003c.243.533.754 1.064 1.189 1.637.434.598.77 1.131'
    '.729 1.57v.006c-.057.744-.48 1.148-1.125 1.294-.645.135-1.52.002-2.395-.464'
    '-.968-.536-2.118-.469-2.857-.602-.369-.066-.61-.2-.723-.4-.11-.2-.113-.602'
    '.123-1.23v-.004l.002-.003c.117-.334.03-.752-.027-1.118-.055-.401-.083-.71.043'
    '-.94.16-.334.396-.4.69-.533.294-.135.64-.202.915-.47h.002v-.002c.256-.268.445'
    '-.601.668-.838.19-.201.38-.336.663-.336zm7.159-9.074c-.435.201-.945.535-1.488'
    '.535-.542 0-.97-.267-1.28-.466-.154-.134-.28-.268-.373-.335-.164-.134-.144'
    '-.333-.074-.333.109.016.129.134.199.2.096.066.215.2.36.333.292.2.68.467'
    ' 1.167.467.485 0 1.053-.267 1.398-.466.195-.135.445-.334.648-.467.156-.136'
    '.149-.267.279-.267.128.016.034.134-.147.332a8.097 8.097 0 01-.69.468zm-1.082'
    '-1.583V5.64c-.006-.02.013-.042.029-.05.074-.043.18-.027.26.004.063 0 .16.067'
    '.15.135-.006.049-.085.066-.135.066-.055 0-.092-.043-.141-.068-.052-.018-.146'
    '-.008-.163-.065zm-.551 0c-.02.058-.113.049-.166.066-.047.025-.086.068-.14.068'
    '-.05 0-.13-.02-.136-.068-.01-.066.088-.133.15-.133.08-.031.184-.047.259-.005'
    '.019.009.036.03.03.05v.02h.003z'
)


def _profile_icon_path(profile: str) -> str:
    """Return the SVG path data for a profile's distro icon."""
    lp = profile.lower()
    if "rhel" in lp:
        return _ICON_RHEL
    if "fedora" in lp:
        return _ICON_FEDORA
    if "suse" in lp or "sles" in lp:
        return _ICON_OPENSUSE
    if "ubuntu" in lp:
        return _ICON_UBUNTU
    return _ICON_LINUX


def _profile_display_name(profile: str) -> str:
    """Convert a profile directory name to a human-friendly display name.

    Examples:
        full-rhel-10.2+overlay-virtme-ng  ->  rhel-10.2 + virtme-ng
        full-virtme-ng+overlay-thin-lto   ->  virtme-ng + thin-lto
        full-virtme-ng                    ->  virtme-ng
    """
    name = profile
    if name.startswith("full-"):
        name = name[5:]
    name = name.replace("+overlay-", " + ")
    return name


def _profile_slug(profile: str) -> str:
    """Convert a profile name into a CSS-safe slug for element IDs."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", profile).strip("-").lower()


def _chip_icon_svg(profile: str) -> str:
    """Return an inline SVG element for a profile chip icon."""
    path_d = _profile_icon_path(profile)
    return (
        f'<svg class="chip-icon" viewBox="0 0 24 24" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path fill="currentColor" d="{path_d}"/></svg>'
    )


# ---------------------------------------------------------------------------
# HTML report – CSS
# ---------------------------------------------------------------------------

_HTML_CSS = """\
:root { --bg: #f0f2f5; --card: #fff; --fg: #1f2328; --muted: #656d76;
        --border: #d0d7de; --green: #1a7f37; --red: #cf222e;
        --green-bg: #dafbe1; --red-bg: #ffebe9; --green-light: #e6ffec;
        --red-light: #fff1e5; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --card: #161b22; --fg: #c9d1d9; --muted: #8b949e;
          --border: #30363d; --green: #3fb950; --red: #f85149;
          --green-bg: #0d2818; --red-bg: #3c1118; --green-light: #0d2818;
          --red-light: #3c1118; }
  .stat-card { background: var(--card); }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: var(--bg); color: var(--fg); padding: 1.5rem; }
.container { max-width: 800px; margin: 0 auto; }
header { margin-bottom: 1.2rem; }
h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: .2rem; }
.sub { font-size: .78rem; color: var(--muted); }
.stats { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0 1.2rem; }
.stat-card { background: var(--card); border: 1px solid var(--border);
             border-radius: 8px; padding: .8rem 1.2rem; flex: 1; min-width: 180px; }
.stat-card h4 { font-size: .68rem; text-transform: uppercase;
                letter-spacing: .06em; color: var(--muted); margin-bottom: .3rem;
                font-weight: 600; }
.stat-big { font-size: 1.8rem; font-weight: 700; line-height: 1; }
.stat-big.green { color: var(--green); }
.stat-big.mixed { color: var(--red); }
.stat-detail { font-size: .72rem; color: var(--muted); margin-top: .25rem; }
.bar { height: 6px; border-radius: 3px; background: var(--border);
       margin-top: .5rem; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; }
.bar-fill.green { background: var(--green); }
.bar-fill.red { background: var(--red); }
.git-panel { background: var(--card); border: 1px solid var(--border);
             border-radius: 8px; padding: .7rem 1rem; margin-bottom: 1.2rem;
             font-size: .8rem; line-height: 1.6; }
.controls { display: flex; gap: .5rem; margin-bottom: 1rem; flex-wrap: wrap;
            align-items: center; }
.ctrl-btn { font-family: inherit; font-size: .75rem; font-weight: 600;
            padding: .35rem .8rem; border-radius: 6px;
            border: 1px solid var(--border); background: var(--card);
            color: var(--fg); cursor: pointer;
            transition: background .1s, border-color .1s; }
.ctrl-btn:hover { background: var(--bg); border-color: var(--muted); }
.ctrl-btn.active { background: var(--fg); color: var(--card);
                   border-color: var(--fg); }
.ctrl-sep { width: 1px; height: 1.2rem; background: var(--border);
            margin: 0 .2rem; }
.tree-group { margin-bottom: 1.5rem; }
.tree-group h2 { font-size: 1rem; font-weight: 700; margin-bottom: .5rem;
                 padding-bottom: .3rem; border-bottom: 2px solid var(--border); }
.test-card { background: var(--card); border: 1px solid var(--border);
             border-radius: 8px; margin-bottom: .5rem; overflow: hidden; }
.test-card summary { padding: .55rem .8rem; cursor: pointer; display: flex;
                     align-items: center; justify-content: space-between;
                     font-size: .85rem; list-style: none; }
.test-card summary::-webkit-details-marker { display: none; }
.test-card summary::before { content: "\\25B6"; font-size: .55rem;
                             margin-right: .5rem; color: var(--muted);
                             transition: transform .15s; flex-shrink: 0; }
.test-card[open] summary::before { transform: rotate(90deg); }
.test-title { font-family: "SF Mono", Menlo, monospace; font-size: .82rem;
              font-weight: 600; }
.ok-tag { font-size: .65rem; font-weight: 700; color: var(--green);
          background: var(--green-bg); padding: .15rem .5rem;
          border-radius: 10px; }
.fail-tag { font-size: .65rem; font-weight: 700; color: var(--red);
            background: var(--red-bg); padding: .15rem .5rem;
            border-radius: 10px; }
.fail-card { border-color: var(--red); border-width: 2px; }
.fail-card summary { background: var(--red-bg); }
.card-body { padding: 0 .8rem .6rem; }
.profile-row, .test-row { display: flex; align-items: center;
                          justify-content: space-between; padding: .3rem 0;
                          border-top: 1px solid var(--border); font-size: .8rem; }
.profile-row:first-child, h3 + .test-row { border-top: none; }
.profile-name, .test-name-cell { font-weight: 500; min-width: 180px; }
a.profile-name, a.profile-link { color: inherit; text-decoration: none; }
a.profile-name:hover, a.profile-link:hover { text-decoration: underline; }
a.test-name-cell { color: inherit; text-decoration: none; }
a.test-name-cell:hover { text-decoration: underline; }
.fail-row .test-name-cell { color: var(--red); font-weight: 600; }
.result-pair { display: grid;
               grid-template-columns: auto 46px 1rem auto 46px;
               align-items: center; gap: .2rem; }
.phase-label { font-size: .6rem; font-weight: 700; color: var(--muted);
               text-transform: uppercase; letter-spacing: .02em;
               text-align: right; }
.badge { display: inline-block; font-size: .6rem; font-weight: 700;
         padding: .12rem .4rem; border-radius: 4px; text-decoration: none;
         text-transform: uppercase; letter-spacing: .03em; text-align: center;
         min-width: 40px; }
.badge-ok { background: var(--green-bg); color: var(--green); }
.badge-fail { background: var(--red-bg); color: var(--red); }
.badge-skip { background: var(--bg); color: var(--muted); }
.badge-na { background: transparent; color: var(--border); }
a.badge:hover { opacity: .8; text-decoration: underline; }
.tree-sub { margin-bottom: .6rem; }
.tree-sub h3 { font-size: .75rem; font-weight: 700; color: var(--muted);
               text-transform: uppercase; letter-spacing: .04em;
               margin: 0 -.8rem .2rem; padding: .35rem .8rem;
               background: var(--bg); border-top: 1px solid var(--border);
               border-bottom: 1px solid var(--border); }
.tree-sub:first-child h3 { border-top: none; }
.profile-chips { display: flex; flex-wrap: wrap; gap: .5rem;
                 margin-bottom: 1.2rem; }
.profile-chip { display: flex; align-items: center; gap: .4rem;
                padding: .4rem .7rem; border-radius: 8px;
                border: 1px solid var(--border); background: var(--card);
                font-size: .78rem; cursor: pointer;
                transition: box-shadow .15s; }
.profile-chip:hover { box-shadow: 0 1px 4px rgba(0,0,0,.1); }
.profile-chip.chip-fail:hover { background: var(--red-bg); }
.profile-chip:not(.chip-fail):hover { background: var(--green-bg); }
.chip-icon { width: 16px; height: 16px; flex-shrink: 0; color: var(--fg); }
.chip-fail { border-color: var(--red); border-width: 2px; }
.chip-name { font-weight: 600; }
.chip-count { font-size: .68rem; color: var(--red); font-weight: 700; }
.chip-count-ok { color: var(--muted); font-weight: 500; }
#view-by-profile { display: none; }
"""

_HTML_JS = """\
function showProfile(slug) {
  showView('profile');
  var el = document.getElementById('profile-' + slug);
  if (el) {
    el.open = true;
    setTimeout(function() {
      el.scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 50);
  }
}
function showView(which) {
  var vt = document.getElementById('view-by-test');
  var vp = document.getElementById('view-by-profile');
  var bt = document.getElementById('btn-by-test');
  var bp = document.getElementById('btn-by-profile');
  if (which === 'profile') {
    vt.style.display = 'none';
    vp.style.display = 'block';
    bt.classList.remove('active');
    bp.classList.add('active');
  } else {
    vp.style.display = 'none';
    vt.style.display = 'block';
    bp.classList.remove('active');
    bt.classList.add('active');
  }
}
function activeView() {
  return document.getElementById('view-by-test').style.display !== 'none'
    ? 'view-by-test' : 'view-by-profile';
}
function expandAll() {
  document.getElementById(activeView())
    .querySelectorAll('.test-card').forEach(function(d) { d.open = true; });
}
function collapseAll() {
  document.getElementById(activeView())
    .querySelectorAll('.test-card').forEach(function(d) { d.open = false; });
}
function collapsePassing() {
  document.getElementById(activeView())
    .querySelectorAll('.test-card').forEach(function(d) {
      d.open = d.dataset.status === 'fail';
    });
}
"""


# ---------------------------------------------------------------------------
# HTML report – builder
# ---------------------------------------------------------------------------

def _badge(result: str, href: str | None) -> str:
    """Render a result badge (PASS/FAIL/XFAIL/XPASS/SKIP/N/A), optionally as a link."""
    cls_map = {"pass": "badge-ok", "FAIL": "badge-fail",
               "xfail": "badge-ok", "XPASS": "badge-fail",
               "skip": "badge-skip", "--": "badge-na"}
    text_map = {"pass": "PASS", "FAIL": "FAIL",
                "xfail": "XFAIL", "XPASS": "XPASS",
                "skip": "SKIP", "--": "N/A"}
    cls = cls_map.get(result, "badge-skip")
    text = text_map.get(result, result)
    if href and result in ("pass", "FAIL", "xfail", "XPASS"):
        return f'<a href="{href}" class="badge {cls}">{text}</a>'
    return f'<span class="badge {cls}">{text}</span>'


def _result_pair_html(
    artifacts_root: Path, profile: str, tree_type: str, test: str,
) -> str:
    """Render the BUILD: / RUNTIME: grid for one (profile, test) pair."""
    br = get_build_result(artifacts_root, profile, tree_type, test)
    rr = get_runtime_result(artifacts_root, profile, tree_type, test)

    b_href = _log_path(profile, tree_type, test, "build-test.log") \
        if _log_exists(artifacts_root, profile, tree_type, test,
                       "build-test.log") else None
    r_href = _log_path(profile, tree_type, test, "runtime-test.log") \
        if _log_exists(artifacts_root, profile, tree_type, test,
                       "runtime-test.log") else None

    return (
        '<span class="result-pair">'
        f'<span class="phase-label">BUILD:</span>{_badge(br, b_href)}'
        '<span></span>'
        f'<span class="phase-label">RUNTIME:</span>{_badge(rr, r_href)}'
        '</span>'
    )


def _stat_card(title: str, ok: int, fail: int, skip: int,
               na: int = 0, xfail: int = 0, xpass: int = 0) -> str:
    """Render a stats card (build or runtime)."""
    good = ok + xfail
    bad = fail + xpass
    total_decisive = good + bad
    pct = round(good / total_decisive * 100) if total_decisive else 100
    color_cls = "green" if bad == 0 else "mixed"
    bar_cls = "green" if bad == 0 else "red"
    detail = f"{ok} passed"
    if xfail:
        detail += f" &middot; {xfail} xfail"
    detail += f" &middot; {fail} failed"
    if xpass:
        detail += f" &middot; {xpass} xpass"
    detail += f" &middot; {skip} skipped"
    if na:
        detail += f" &middot; {na} n/a"
    return (
        '<div class="stat-card">'
        f'<h4>{title}</h4>'
        f'<div class="stat-big {color_cls}">{pct}%</div>'
        f'<div class="stat-detail">{detail}</div>'
        f'<div class="bar"><div class="bar-fill {bar_cls}" '
        f'style="width:{pct}%"></div></div>'
        '</div>'
    )


def _is_bad_result(result: str) -> bool:
    """True for results that need attention: FAIL or XPASS."""
    return result in ("FAIL", "XPASS")


def _count_profile_fails(
    artifacts_root: Path, profile: str,
    tree_types: list[str], tests_by_tree: dict[str, list[str]],
) -> int:
    """Count total failures (FAIL + XPASS for build + runtime) for a single profile."""
    count = 0
    for tt in tree_types:
        for test in tests_by_tree.get(tt, []):
            if _is_bad_result(get_build_result(artifacts_root, profile, tt, test)):
                count += 1
            if _is_bad_result(get_runtime_result(artifacts_root, profile, tt, test)):
                count += 1
    return count


def _count_test_fails(
    artifacts_root: Path, profiles: list[str],
    tree_type: str, test: str,
) -> int:
    """Count total failures (FAIL + XPASS for build + runtime) for a single test across profiles."""
    count = 0
    for p in profiles:
        if _is_bad_result(get_build_result(artifacts_root, p, tree_type, test)):
            count += 1
        if _is_bad_result(get_runtime_result(artifacts_root, p, tree_type, test)):
            count += 1
    return count


def generate_html_report(
    artifacts_root: Path,
    profiles: list[str],
    tree_types: list[str],
    tests_by_tree: dict[str, list[str]],
    git_info: dict | None = None,
) -> str:
    """Generate a self-contained HTML report with the new card-based design."""
    import html as _html
    from datetime import datetime

    c = _count_results(artifacts_root, profiles, tree_types, tests_by_tree)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- Profile chips ---
    chips = []
    total_tests = sum(len(tests_by_tree.get(tt, [])) for tt in tree_types)
    for profile in profiles:
        slug = _profile_slug(profile)
        disp = _profile_display_name(profile)
        icon = _chip_icon_svg(profile)
        fails = _count_profile_fails(artifacts_root, profile, tree_types,
                                     tests_by_tree)
        if fails:
            chip_cls = "profile-chip chip-fail"
            count_html = (f'<span class="chip-count">'
                          f'{fails} failed</span>')
        else:
            chip_cls = "profile-chip chip-ok"
            count_html = (f'<span class="chip-count chip-count-ok">'
                          f'{total_tests}/{total_tests}</span>')
        chips.append(
            f'<div class="{chip_cls}" onclick="showProfile(\'{slug}\')">'
            f'{icon}<span class="chip-name">{_html.escape(disp)}</span>'
            f'{count_html}</div>'
        )
    chips_html = '<div class="profile-chips">' + "".join(chips) + '</div>'

    # --- Git panel ---
    git_html = ""
    if git_info:
        git_html = ('<div class="git-panel">'
                    + _format_git_html(git_info) + '</div>')

    # --- "By test" view ---
    by_test_parts = []
    for tree_type in tree_types:
        tests = tests_by_tree.get(tree_type, [])
        if not tests:
            continue
        by_test_parts.append(
            f'<section class="tree-group"><h2>{tree_type} tests</h2>')
        for test in tests:
            fails = _count_test_fails(artifacts_root, profiles,
                                      tree_type, test)
            if fails:
                tag = f"<span class='fail-tag'>FAIL &times; {fails}</span>"
                card_cls = 'test-card fail-card'
                status = 'fail'
                extra = ' open'
            else:
                tag = "<span class='ok-tag'>OK</span>"
                card_cls = 'test-card'
                status = 'pass'
                extra = ''

            rows = []
            for p in profiles:
                disp = _profile_display_name(p)
                pair = _result_pair_html(artifacts_root, p, tree_type, test)
                rows.append(
                    f'<div class="profile-row">'
                    f'<a class="profile-name" href="{p}/">'
                    f'{_html.escape(disp)}</a>{pair}</div>'
                )

            by_test_parts.append(
                f'<details class="{card_cls}" data-status="{status}"{extra}>'
                f'<summary><span class="test-title">'
                f'{_html.escape(test)}</span>{tag}</summary>'
                f'<div class="card-body">{"".join(rows)}</div>'
                f'</details>'
            )
        by_test_parts.append('</section>')

    # --- "By profile" view ---
    by_profile_parts = []
    for profile in profiles:
        slug = _profile_slug(profile)
        disp = _profile_display_name(profile)
        fails = _count_profile_fails(artifacts_root, profile, tree_types,
                                     tests_by_tree)
        if fails:
            tag = f"<span class='fail-tag'>FAIL &times; {fails}</span>"
            card_cls = 'test-card fail-card'
            status = 'fail'
            extra = ' open'
        else:
            tag = "<span class='ok-tag'>OK</span>"
            card_cls = 'test-card'
            status = 'pass'
            extra = ''

        body_parts = []
        for tree_type in tree_types:
            tests = tests_by_tree.get(tree_type, [])
            if not tests:
                continue
            tree_rows = []
            for test in tests:
                br = get_build_result(artifacts_root, profile, tree_type, test)
                rr = get_runtime_result(artifacts_root, profile, tree_type,
                                        test)
                pair = _result_pair_html(artifacts_root, profile,
                                        tree_type, test)
                row_cls = "test-row"
                if _is_bad_result(br) or _is_bad_result(rr):
                    row_cls = "test-row fail-row"
                tree_rows.append(
                    f'<div class="{row_cls}">'
                    f'<a class="test-name-cell" '
                    f'href="{profile}/{tree_type}/{test}/">'
                    f'{_html.escape(test)}</a>{pair}</div>'
                )
            body_parts.append(
                f'<div class="tree-sub"><h3>{tree_type} tests</h3>'
                f'{"".join(tree_rows)}</div>'
            )

        by_profile_parts.append(
            f'<details class="{card_cls}" data-status="{status}" '
            f'id="profile-{slug}"{extra}>'
            f'<summary><a class="test-title profile-link" href="{profile}/">'
            f'{_html.escape(disp)}</a>{tag}</summary>'
            f'<div class="card-body">{"".join(body_parts)}</div>'
            f'</details>'
        )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>klp-build kselftest report</title>
<style>
{_HTML_CSS}</style>
</head>
<body>
<div class="container">
<header>
  <h1>klp-build kselftest report</h1>
  <div class="sub">{now}</div>
</header>
<div class="stats">
  {_stat_card("Build Tests", c["b_pass"], c["b_fail"], c["b_skip"],
              xfail=c["b_xfail"], xpass=c["b_xpass"])}
  {_stat_card("Runtime Tests", c["r_pass"], c["r_fail"], c["r_skip"],
              na=c["r_na"], xfail=c["r_xfail"], xpass=c["r_xpass"])}
</div>
{chips_html}
{git_html}
<div class="controls">
  <button class="ctrl-btn active" id="btn-by-test" onclick="showView('test')">By test</button>
  <button class="ctrl-btn" id="btn-by-profile" onclick="showView('profile')">By profile</button>
  <div class="ctrl-sep"></div>
  <button class="ctrl-btn" onclick="expandAll()">Expand all</button>
  <button class="ctrl-btn" onclick="collapseAll()">Collapse all</button>
  <button class="ctrl-btn" onclick="collapsePassing()">Collapse passing</button>
</div>
<div id="view-by-test">
{"".join(by_test_parts)}
</div>
<div id="view-by-profile">
{"".join(by_profile_parts)}
</div>
</div>
<script>
{_HTML_JS}</script>
</body>
</html>
"""


def main() -> int:
    artifacts_root = get_artifacts_dir()
    profiles = discover_profiles(artifacts_root)
    tree_types = discover_tree_types(artifacts_root, profiles)
    tests_by_tree = {
        tt: discover_tests(artifacts_root, profiles, tt) for tt in tree_types
    }

    git_info = gather_git_summary()

    artifacts_root.mkdir(parents=True, exist_ok=True)

    # Plain-text report.
    out_lines = generate_report(artifacts_root, profiles, tree_types, tests_by_tree,
                                git_info=git_info)
    if not profiles:
        out_lines.append("(no profile directories under artifacts/)")
    elif not any(tests_by_tree.values()):
        out_lines.append("(no tests with build-test.log or runtime-test.log found)")
    (artifacts_root / "report.txt").write_text("\n".join(out_lines) + "\n")

    # HTML report (results link to log files).
    html = generate_html_report(artifacts_root, profiles, tree_types, tests_by_tree,
                                git_info=git_info)
    (artifacts_root / "report.html").write_text(html)

    return 0


if __name__ == "__main__":
    sys.exit(main())
