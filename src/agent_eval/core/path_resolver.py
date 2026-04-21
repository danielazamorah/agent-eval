"""Resolve canonical paths for the unified ``tests/eval/`` layout.

Per the SDK-aligned plan §3, evaluation files live under ``tests/eval/``:

.. code-block:: text

    <agent_dir>/
    └── tests/eval/
        ├── dataset.jsonl
        ├── metrics/metric_definitions.json
        └── results/

Older projects use the legacy ``eval/`` layout (or ``app/eval/`` in
Agent Starter Pack projects). These helpers return the canonical path when
present, falling back to legacy locations so existing projects keep working
without forcing migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


_CANONICAL_EVAL = Path("tests") / "eval"
_LEGACY_EVAL_FLAT = Path("eval")
_LEGACY_EVAL_NESTED = Path("app") / "eval"


def find_eval_dir(agent_dir: Path | str) -> Path:
    """Return the eval directory in use for ``agent_dir``.

    Preference order:
      1. ``<agent_dir>/tests/eval/`` (canonical)
      2. ``<agent_dir>/eval/`` (legacy flat)
      3. ``<agent_dir>/app/eval/`` (legacy Agent Starter Pack)

    Falls back to the canonical path even if it doesn't exist yet — callers
    that need to *write* into the eval folder can rely on this returning a
    consistent location.
    """
    base = Path(agent_dir)
    for candidate in (
        base / _CANONICAL_EVAL,
        base / _LEGACY_EVAL_FLAT,
        base / _LEGACY_EVAL_NESTED,
    ):
        if candidate.exists():
            return candidate
    return base / _CANONICAL_EVAL


def find_metrics_path(agent_dir: Path | str) -> Optional[Path]:
    """Return the active ``metric_definitions.json`` path or ``None`` if missing.

    Searches the same canonical/legacy precedence as :func:`find_eval_dir`.
    Returns ``None`` when no metric definitions file exists anywhere — callers
    decide whether to fall back to a default metric set.
    """
    eval_dir = find_eval_dir(agent_dir)
    candidate = eval_dir / "metrics" / "metric_definitions.json"
    if candidate.exists():
        return candidate

    base = Path(agent_dir)
    for legacy in (
        base / _LEGACY_EVAL_FLAT / "metrics" / "metric_definitions.json",
        base / _LEGACY_EVAL_NESTED / "metrics" / "metric_definitions.json",
    ):
        if legacy.exists():
            return legacy
    return None


def find_dataset_path(agent_dir: Path | str) -> Optional[Path]:
    """Return the active ``dataset.jsonl`` path or ``None`` if missing."""
    eval_dir = find_eval_dir(agent_dir)
    candidate = eval_dir / "dataset.jsonl"
    if candidate.exists():
        return candidate
    return None
