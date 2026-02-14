# SPDX-License-Identifier: GPL-2.0
"""State and artifact paths keyed by (test_id, profile_name)."""

import json
import os

STATE_FILENAME = ".test_state.json"
ARTIFACTS_DIR = "artifacts"


def state_key(test_id: str, profile: str) -> str:
    """Composite key for (test, profile)."""
    return f"{test_id}@{profile}"


def get_state_path(selftest_root: str) -> str:
    """Path to the state file."""
    return os.path.join(selftest_root, STATE_FILENAME)


def load_state(selftest_root: str) -> dict:
    """Load state dict; return {} if missing or invalid."""
    path = get_state_path(selftest_root)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(selftest_root: str, state: dict) -> None:
    """Write state dict to disk."""
    path = get_state_path(selftest_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_artifact_dir(selftest_root: str, test_id: str, profile: str) -> str:
    """Directory for artifacts for (test, profile)."""
    return os.path.join(selftest_root, ARTIFACTS_DIR, test_id, profile)


def record_result(
    selftest_root: str, test_id: str, profile: str, status: str, details: dict = None
) -> None:
    """Record a test result in state."""
    state = load_state(selftest_root)
    key = state_key(test_id, profile)
    state[key] = {"status": status, **(details or {})}
    save_state(selftest_root, state)
