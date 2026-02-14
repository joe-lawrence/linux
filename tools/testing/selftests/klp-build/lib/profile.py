# SPDX-License-Identifier: GPL-2.0
"""
Profile discovery and config application for klp-build selftests.
Profiles live under profiles/<name>/ with config.yaml (YAML).
Paths in config_base/config_apply are relative to the profile directory.
Profile type is inferred from directory name: full-* => full, overlay-* => overlay.
PyYAML is required: pip install pyyaml
"""

import os
import subprocess
import glob
import sys
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

PROFILE_YAML_FILENAME = "config.yaml"


def get_profiles_dir() -> str:
    """Directory containing profiles/<profile>/ (selftest profiles root)."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")


def get_selftest_root() -> str:
    """Root of the klp-build selftest tree (parent of lib/ and profiles/)."""
    return os.path.dirname(os.path.dirname(__file__))


def discover_profiles() -> List[str]:
    """
    Return list of profile names (directory names under profiles/ that
    contain config.yaml). Only directories are considered profiles.
    """
    profiles_dir = get_profiles_dir()
    if not os.path.isdir(profiles_dir):
        return []
    names = []
    for name in sorted(os.listdir(profiles_dir)):
        path = os.path.join(profiles_dir, name)
        if not os.path.isdir(path):
            continue
        yaml_path = os.path.join(path, PROFILE_YAML_FILENAME)
        if os.path.isfile(yaml_path):
            names.append(name)
    return names


def _profile_type_from_name(name: str) -> str:
    """Infer full vs overlay from profile directory name."""
    if name.startswith("full-"):
        return "full"
    if name.startswith("overlay-"):
        return "overlay"
    return "full"  # default for legacy names


def load_profile(name: str) -> "Profile":
    """
    Load profile by name. Raises FileNotFoundError if config.yaml missing,
    or ValueError on invalid YAML/content.
    """
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML is required for profile loading (pip install pyyaml)")

    profiles_dir = get_profiles_dir()
    profile_dir = os.path.join(profiles_dir, name)
    yaml_path = os.path.join(profile_dir, PROFILE_YAML_FILENAME)
    if not os.path.isfile(yaml_path):
        raise FileNotFoundError(f"Profile '{name}' has no {PROFILE_YAML_FILENAME}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or not isinstance(data, dict):
        raise ValueError(f"Profile '{name}': invalid or empty YAML")

    name_val = data.get("name")
    desc = data.get("description")
    if not name_val or not desc:
        raise ValueError(f"Profile '{name}': 'name' and 'description' are required")

    config_base = data.get("config_base")
    if config_base is not None and isinstance(config_base, str):
        config_base = [config_base]
    if config_base is not None and not isinstance(config_base, list):
        config_base = None

    config_apply = data.get("config_apply")
    if config_apply is not None and isinstance(config_apply, str):
        config_apply = [config_apply]
    if config_apply is not None and not isinstance(config_apply, list):
        config_apply = None

    toolchain = data.get("toolchain")
    if toolchain is not None and not isinstance(toolchain, dict):
        toolchain = None

    runtime = data.get("runtime", True)
    if not isinstance(runtime, bool):
        runtime = True

    profile_type = _profile_type_from_name(name)

    return Profile(
        name=name_val,
        description=desc,
        profile_dir=profile_dir,
        profile_type=profile_type,
        config_base=config_base or [],
        config_apply=config_apply,
        toolchain=toolchain or {},
        runtime=runtime,
    )


@dataclass
class Profile:
    name: str
    description: str
    profile_dir: str
    profile_type: str = "full"  # "full" | "overlay"
    config_base: List[str] = field(default_factory=list)
    config_apply: Optional[List[str]] = None
    toolchain: dict = field(default_factory=dict)
    runtime: bool = True

    def _resolve_path(self, entry: str) -> str:
        """Resolve path relative to profile dir unless absolute."""
        if os.path.isabs(entry):
            return entry
        return os.path.join(self.profile_dir, entry)

    def _get_config_apply_list(self) -> List[str]:
        """List of config_apply entries; default = sorted *.fragment in profile dir."""
        if self.config_apply is not None:
            return list(self.config_apply)
        pattern = os.path.join(self.profile_dir, "*.fragment")
        files = sorted(glob.glob(pattern))
        return [os.path.basename(f) for f in files]

    def _is_path(self, entry: str) -> bool:
        """True if entry is a path to a file (not a command)."""
        if os.path.isabs(entry):
            return True
        if "/" in entry or os.path.sep in entry:
            return True
        resolved = os.path.join(self.profile_dir, entry)
        return os.path.isfile(resolved)


def _parse_fragment_config(path: str) -> dict:
    """Parse a Kconfig fragment file; return dict of symbol -> 'y'|'m'|'n'."""
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("# ") and " is not set" in line:
                rest = line[2:].strip()
                if rest.endswith(" is not set"):
                    sym = rest[: -len(" is not set")].strip()
                    if sym.startswith("CONFIG_"):
                        result[sym] = "n"
                continue
            if line.startswith("#"):
                continue
            if line.startswith("CONFIG_") and "=" in line:
                sym, _, val = line.partition("=")
                sym = sym.strip()
                val = val.strip()
                if val in ("y", "m"):
                    result[sym] = val
    return result


def _parse_dot_config(path: str) -> dict:
    """Parse kernel .config; return dict of symbol -> 'y'|'m'|'n' (or value string)."""
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                if line.startswith("# ") and " is not set" in line:
                    rest = line[2:].strip()
                    if rest.endswith(" is not set"):
                        sym = rest[: -len(" is not set")].strip()
                        if sym.startswith("CONFIG_"):
                            result[sym] = "n"
                continue
            if line.startswith("CONFIG_") and "=" in line:
                sym, _, val = line.partition("=")
                sym = sym.strip()
                val = val.strip()
                if val in ("y", "m"):
                    result[sym] = val
                elif val.startswith('"') and val.endswith('"'):
                    result[sym] = val
    return result


def _verify_config_apply_in_config(config_path: str, fragment_paths: List[str]) -> None:
    """
    Verify that all CONFIG_* from config_apply fragment files are in .config
    with the same value. Only config_apply is verified; config_base is not.
    """
    config_values = _parse_dot_config(config_path)
    for frag_path in fragment_paths:
        if not os.path.isfile(frag_path):
            continue
        requested = _parse_fragment_config(frag_path)
        for sym, req_val in requested.items():
            if sym not in config_values:
                raise ValueError(
                    f"Fragment {frag_path}: requested {sym}={req_val} but symbol not in .config"
                )
            actual = config_values[sym]
            if actual != req_val:
                raise ValueError(
                    f"Fragment {frag_path}: requested {sym}={req_val} but .config has {sym}={actual}"
                )


def set_toolchain_env(toolchain: dict) -> None:
    """Set CC, LD, AS in os.environ from profile toolchain for config and build."""
    if not toolchain:
        return
    compiler = toolchain.get("compiler")
    if compiler:
        os.environ["CC"] = compiler
    linker = toolchain.get("linker")
    if linker:
        os.environ["LD"] = linker
    assembler = toolchain.get("assembler")
    if assembler:
        os.environ["AS"] = assembler


def apply_profile(
    kernel_root: str,
    profile_name: str,
    base_config_path: Optional[str] = None,
) -> None:
    """
    Apply a single profile's config to the kernel tree.
    If base_config_path is set (e.g. saved .config), use that as the base when
    the profile has no config_base (overlay); otherwise use kernel_root/.config.
    All commands run from kernel_root.
    Verification: only config_apply fragment options are verified after
    olddefconfig; config_base is not verified.
    """
    profile = load_profile(profile_name)
    set_toolchain_env(profile.toolchain)
    config_path = os.path.join(kernel_root, ".config")

    if not profile.config_base and not (base_config_path and os.path.isfile(base_config_path)):
        if not os.path.isfile(config_path):
            raise FileNotFoundError(
                "Profile has no config_base and no .config exists. "
                "Create a .config first (e.g. make defconfig) or use a profile that sets config_base."
            )

    if profile.config_base:
        for entry in profile.config_base:
            resolved = profile._resolve_path(entry) if profile._is_path(entry) else None
            if resolved is not None and os.path.isfile(resolved):
                with open(resolved, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(content)
                break
            else:
                subprocess.run(
                    entry,
                    shell=True,
                    cwd=kernel_root,
                    check=True,
                    env=os.environ.copy(),
                )
                break
    else:
        if base_config_path and os.path.isfile(base_config_path):
            with open(base_config_path, "r", encoding="utf-8") as f:
                content = f.read()
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)
        # else: keep existing .config

    merge_list = profile._get_config_apply_list()
    if not merge_list:
        subprocess.run(
            ["make", "olddefconfig"],
            cwd=kernel_root,
            check=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        return

    fragment_paths = []
    tmp_files = []
    for entry in merge_list:
        if profile._is_path(entry):
            fragment_paths.append(profile._resolve_path(entry))
        else:
            result = subprocess.run(
                entry,
                shell=True,
                cwd=kernel_root,
                capture_output=True,
                text=True,
                check=True,
                env=os.environ.copy(),
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".fragment", delete=False
            ) as tf:
                tf.write(result.stdout or "")
                tmp_files.append(tf.name)
                fragment_paths.append(tf.name)

    try:
        if not fragment_paths:
            subprocess.run(
                ["make", "olddefconfig"],
                cwd=kernel_root,
                check=True,
                capture_output=True,
                env=os.environ.copy(),
            )
            return

        merge_script = os.path.join(
            kernel_root, "scripts", "kconfig", "merge_config.sh"
        )
        if not os.path.isfile(merge_script):
            raise FileNotFoundError(f"merge_config.sh not found at {merge_script}")

        cmd = [merge_script, "-m", config_path] + fragment_paths
        result = subprocess.run(
            cmd, cwd=kernel_root, capture_output=True, text=True,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            if result.stdout:
                print(result.stdout, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            result.check_returncode()
        subprocess.run(
            ["make", "olddefconfig"],
            cwd=kernel_root,
            check=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        _verify_config_apply_in_config(config_path, fragment_paths)
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass
