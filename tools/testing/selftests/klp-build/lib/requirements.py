# SPDX-License-Identifier: GPL-2.0
"""Test-profile association: CONFIG_PROFILES and requirement checks."""

import os
import platform
import re
from typing import List, Optional

# Expected.py attributes
CONFIG_PROFILES = "CONFIG_PROFILES"
REQUIRED_CONFIG = "REQUIRED_CONFIG"
SUPPORTED_COMPILERS = "SUPPORTED_COMPILERS"
SUPPORTED_ARCHES = "SUPPORTED_ARCHES"


def get_current_compiler() -> str:
    """Return canonical compiler name: gcc, clang, or unknown."""
    cc = os.environ.get("CC", "cc")
    if "/" in cc or cc.startswith("-"):
        base = os.path.basename(cc.split()[0]) if cc else "cc"
    else:
        base = cc.split()[0] if cc else "cc"
    if "gcc" in base or "g++" in base:
        return "gcc"
    if "clang" in base:
        return "clang"
    return "unknown"


def config_has_symbol(config_path: str, symbol: str) -> bool:
    """True if .config has CONFIG_FOO=y or CONFIG_FOO=m."""
    if not os.path.isfile(config_path):
        return False
    pattern = re.compile(r"^" + re.escape(symbol) + r"=(y|m)\s*$")
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            if pattern.match(line.strip()):
                return True
    return False


def profile_satisfies_required_config(config_path: str, required: List[str]) -> bool:
    """True if config has each of the required symbols as y or m."""
    for sym in required:
        if not config_has_symbol(config_path, sym):
            return False
    return True


def test_belongs_to_profile(
    expected_attrs: dict,
    profile_name: str,
    profile_config_path: Optional[str],
    profile_compiler: Optional[str],
) -> bool:
    """
    True if this test belongs to the given profile (explicit or requirements).
    expected_attrs: dict from expected.py (CONFIG_PROFILES, REQUIRED_CONFIG, etc.).
    profile_config_path: path to profile's merged .config (None for current env).
    profile_compiler: profile's compiler (None = use current).
    """
    # (a) Explicit CONFIG_PROFILES
    config_profiles = expected_attrs.get(CONFIG_PROFILES)
    if isinstance(config_profiles, list) and profile_name in config_profiles:
        return True
    if isinstance(config_profiles, str) and profile_name == config_profiles:
        return True

    # (b) Requirements
    required_config = expected_attrs.get(REQUIRED_CONFIG)
    if isinstance(required_config, list) and required_config and profile_config_path:
        if not profile_satisfies_required_config(profile_config_path, required_config):
            return False
    elif isinstance(required_config, list) and required_config and not profile_config_path:
        return False

    supported_compilers = expected_attrs.get(SUPPORTED_COMPILERS)
    compiler = profile_compiler or get_current_compiler()
    if isinstance(supported_compilers, list) and supported_compilers:
        if compiler not in supported_compilers:
            return False

    supported_arches = expected_attrs.get(SUPPORTED_ARCHES)
    arch = platform.machine()
    if isinstance(supported_arches, list) and supported_arches:
        if arch not in supported_arches:
            return False

    # No declaration => run in all profiles
    if not any(
        [
            expected_attrs.get(CONFIG_PROFILES),
            expected_attrs.get(REQUIRED_CONFIG),
            expected_attrs.get(SUPPORTED_COMPILERS),
            expected_attrs.get(SUPPORTED_ARCHES),
        ]
    ):
        return True

    return True
