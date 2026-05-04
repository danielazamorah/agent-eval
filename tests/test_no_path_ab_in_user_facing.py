"""Guard: forbid 'Path A' / 'Path B' in user-facing strings.

The 2026-04-23 customer demo proved that "Path A vs Path B" vocabulary
makes the CLI feel like a false binary — it isn't, the two surfaces
compose. This test wraps tools/check_no_path_ab.sh so any regression
shows up under pytest, not just CI.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "tools" / "check_no_path_ab.sh"


def test_no_path_ab_strings_in_user_facing_code():
    assert GUARD.is_file(), f"Missing guard script at {GUARD}"
    result = subprocess.run(
        ["bash", str(GUARD), str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Surface the script's own diagnostic so the test failure is
        # actionable instead of just "exit 1."
        raise AssertionError(
            "tools/check_no_path_ab.sh failed:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
