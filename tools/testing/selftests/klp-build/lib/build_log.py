# SPDX-License-Identifier: GPL-2.0
"""
Write build-test.log after klp-build runs.
Captures stdout/stderr and optionally klp-tmp logs (diff.log; orig/patched/kmod build.log when verbose).
"""

import os
import subprocess


def _get_toolchain_info(kernel_root: str) -> dict:
    """Detect kernel version and compiler/linker/assembler for log header."""
    info = {
        "kernel": "Unknown",
        "compiler": "Unknown",
        "linker": "Unknown",
        "assembler": "Unknown",
    }
    try:
        proc = subprocess.run(
            ["git", "describe", "HEAD"],
            cwd=kernel_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            info["kernel"] = proc.stdout.strip()
        else:
            proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=kernel_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                info["kernel"] = proc.stdout.strip()
    except Exception:
        pass

    try:
        if os.environ.get("LLVM") == "1":
            try:
                p = subprocess.run(
                    ["clang", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if p.returncode == 0:
                    info["compiler"] = p.stdout.split("\n")[0].strip()
            except Exception:
                info["compiler"] = "Clang (version unavailable)"
            try:
                p = subprocess.run(
                    ["ld.lld", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if p.returncode == 0:
                    info["linker"] = p.stdout.split("\n")[0].strip()
            except Exception:
                info["linker"] = "LLD (version unavailable)"
            info["assembler"] = "Clang integrated assembler"
        elif "clang" in os.environ.get("CC", "").lower():
            for tool, cmd, key in [
                ("clang", ["clang", "--version"], "compiler"),
                ("ld", ["ld", "--version"], "linker"),
                ("as", ["as", "--version"], "assembler"),
            ]:
                try:
                    p = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if p.returncode == 0:
                        info[key] = p.stdout.split("\n")[0].strip()
                except Exception:
                    pass
        else:
            for cmd, key in [
                (["gcc", "--version"], "compiler"),
                (["ld", "--version"], "linker"),
                (["as", "--version"], "assembler"),
            ]:
                try:
                    p = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if p.returncode == 0:
                        info[key] = p.stdout.split("\n")[0].strip()
                except Exception:
                    pass
    except Exception:
        pass
    return info


def append_klp_tmp_logs(log_file, tmp_dir: str, verbose: bool = False) -> None:
    """
    Append klp-tmp build logs to the open log file.
    - diff/diff.log: always
    - orig/build.log, patched/build.log, kmod/build.log: when verbose
    """
    entries = [
        ("diff/diff.log", "DIFF LOG (Object Changes)"),
    ]
    if verbose:
        entries.extend([
            ("orig/build.log", "ORIGINAL KERNEL BUILD LOG"),
            ("patched/build.log", "PATCHED KERNEL BUILD LOG"),
            ("kmod/build.log", "LIVEPATCH MODULE BUILD LOG"),
        ])
    for rel_path, title in entries:
        full_path = os.path.join(tmp_dir, rel_path)
        log_file.write(f"\n{'='*70}\n")
        log_file.write(f"{title}\n")
        log_file.write(f"{'='*70}\n")
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    log_file.write(f.read())
            except Exception as e:
                log_file.write(f"(error reading {rel_path}: {e})\n")
        else:
            log_file.write(f"(file not found: {rel_path})\n")
        log_file.write("\n")


def write_build_log(
    proc,
    test_id: str,
    artifact_dir: str,
    kernel_root: str,
    patch_paths: list,
    verbose: bool = False,
) -> None:
    """
    Write build-test.log after klp-build completes.
    proc: KlpBuildResult from run_klp_build (returncode, stdout, stderr, ...).
    """
    log_path = os.path.join(artifact_dir, "build-test.log")
    os.makedirs(artifact_dir, exist_ok=True)
    toolchain = _get_toolchain_info(kernel_root)
    tmp_dir = os.path.join(kernel_root, "klp-tmp")

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"{'='*70}\n")
        log.write(f"BUILD LOG: {test_id}\n")
        log.write(f"{'='*70}\n")
        log.write(f"Result:     {'SUCCESS' if proc.returncode == 0 else 'FAILURE'}\n")
        log.write(f"Exit code:  {proc.returncode}\n")
        log.write(f"\n")
        log.write(f"Kernel:     {toolchain['kernel']}\n")
        log.write(f"\n")
        log.write("Toolchain:\n")
        log.write(f"  Compiler:   {toolchain['compiler']}\n")
        log.write(f"  Linker:     {toolchain['linker']}\n")
        log.write(f"  Assembler:  {toolchain['assembler']}\n")
        log.write(f"{'='*70}\n\n")
        log.write(f"{'='*70}\n")
        log.write("FULL BUILD OUTPUT\n")
        log.write(f"{'='*70}\n\n")
        log.write("--- klp-build stdout ---\n")
        log.write(proc.stdout if proc.stdout else "(empty)\n")
        log.write("\n--- klp-build stderr ---\n")
        log.write(proc.stderr if proc.stderr else "(empty)\n")
        append_klp_tmp_logs(log, tmp_dir, verbose)
        log.write(f"\n{'='*70}\n")
        log.write("TEST PATCH(ES)\n")
        log.write(f"{'='*70}\n\n")
        for i, path in enumerate(patch_paths, 1):
            name = os.path.basename(path)
            if len(patch_paths) > 1:
                log.write(f"--- Patch {i}: {name} ---\n")
            else:
                log.write(f"--- Patch: {name} ---\n")
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        log.write(f.read())
                except Exception as e:
                    log.write(f"(error reading patch: {e})\n")
            else:
                log.write(f"(file not found)\n")
            log.write("\n")
