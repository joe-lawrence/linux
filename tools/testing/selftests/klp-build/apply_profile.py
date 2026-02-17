#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
#
# Apply a config profile (or profile chain) to the kernel tree.
# Usage: apply_profile.py [KERNEL_ROOT] PROFILE
# When PROFILE is overlay-only and no .config exists, exit 77 (kselftest skip).
# Requires PyYAML: pip install pyyaml
#

import os
import shutil
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: apply_profile.py [KERNEL_ROOT] PROFILE", file=sys.stderr)
        return 1
    if len(sys.argv) == 2:
        profile_name = sys.argv[1]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        kernel_root = script_dir
        for _ in range(4):
            kernel_root = os.path.dirname(kernel_root)
    else:
        kernel_root = sys.argv[1]
        profile_name = sys.argv[2]

    if not os.path.isdir(kernel_root):
        print(f"Not a directory: {kernel_root}", file=sys.stderr)
        return 1

    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(script_dir, "lib"))
    from profile import apply_profile
    from state import ARTIFACTS_DIR

    try:
        apply_profile(kernel_root, profile_name)
    except FileNotFoundError as e:
        if "Overlay-only chain and no .config exists" in str(e):
            print(f"skip: {e}", file=sys.stderr)
            return 77
        print(f"apply_profile failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"apply_profile failed: {e}", file=sys.stderr)
        return 1

    config_path = os.path.join(kernel_root, ".config")
    if os.path.isfile(config_path):
        artifacts_root = os.path.join(script_dir, ARTIFACTS_DIR)
        profile_artifact_dir = os.path.join(artifacts_root, profile_name)
        os.makedirs(profile_artifact_dir, exist_ok=True)
        shutil.copy2(config_path, os.path.join(profile_artifact_dir, "config"))
        with open(os.path.join(profile_artifact_dir, "profile"), "w", encoding="utf-8") as f:
            f.write(profile_name + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
