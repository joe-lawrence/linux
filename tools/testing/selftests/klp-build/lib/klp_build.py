# SPDX-License-Identifier: GPL-2.0
"""Invoke scripts/livepatch/klp-build for a test."""

import os
import re
import subprocess
from collections import namedtuple

# Result from run_klp_build: returncode, stdout, stderr, tmp_dir, ko_path.
KlpBuildResult = namedtuple(
    "KlpBuildResult", ["returncode", "stdout", "stderr", "tmp_dir", "ko_path"]
)


def get_klp_build_script(kernel_root: str) -> str:
    """Path to klp-build script."""
    return os.path.join(kernel_root, "scripts", "livepatch", "klp-build")


def _default_ko_path(kernel_root: str, patch_paths: list) -> str:
    """Default .ko path when script does not use -o (matches klp-build logic)."""
    if not patch_paths:
        name = "patch"
    elif len(patch_paths) == 1:
        name = os.path.splitext(os.path.basename(patch_paths[0]))[0] or "patch"
    else:
        name = "patch"
    # Match script: livepatch-<name>, sanitize to [a-zA-Z0-9_-], max 55 chars
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", f"livepatch-{name}")[:55]
    return os.path.join(kernel_root, f"{sanitized}.ko")


def run_klp_build(
    kernel_root: str,
    patch_paths: list,
    output_path: str = None,
    jobs: int = None,
    keep_tmp: bool = False,
    short_circuit: int = None,
) -> KlpBuildResult:
    """Run klp-build from kernel_root with given patch file(s).
    short_circuit: if set (e.g. 2), pass -T and -S N to reuse existing klp-tmp.
    Returns KlpBuildResult with returncode, stdout, stderr, tmp_dir, ko_path.
    """
    script = get_klp_build_script(kernel_root)
    if not os.path.isfile(script):
        raise FileNotFoundError(f"klp-build not found: {script}")
    cmd = [script]
    if output_path:
        cmd += ["-o", output_path]
    if jobs is not None:
        cmd += ["-j", str(jobs)]
    if short_circuit is not None:
        keep_tmp = True
        cmd += ["--keep-tmp", "--short-circuit", str(short_circuit)]
    elif keep_tmp:
        cmd += ["--keep-tmp"]
    cmd += list(patch_paths)
    result = subprocess.run(
        cmd,
        cwd=kernel_root,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    tmp_dir = os.path.join(kernel_root, "klp-tmp")
    ko_path = output_path if output_path else _default_ko_path(kernel_root, patch_paths)
    return KlpBuildResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        tmp_dir=tmp_dir,
        ko_path=ko_path,
    )
