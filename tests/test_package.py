"""Smoke tests: verify the package installs, imports, and wires up correctly."""

import importlib


def test_package_importable():
    """The top-level package must be importable."""
    mod = importlib.import_module("agent_eval")
    assert mod is not None


def test_core_modules_importable():
    """Every core module must import without errors."""
    modules = [
        "agent_eval.core.config",
        "agent_eval.core.agent_client",
        "agent_eval.core.converters",
        "agent_eval.core.data_mapper",
        "agent_eval.core.deterministic_metrics",
        "agent_eval.core.evaluator",
        "agent_eval.core.analyzer",
        "agent_eval.core.gemini_prompt_builder",
        "agent_eval.core.interactions",
        "agent_eval.core.processor",
    ]
    for name in modules:
        mod = importlib.import_module(name)
        assert mod is not None, f"Failed to import {name}"


def test_cli_importable():
    """The CLI entry point must be importable."""
    from agent_eval.cli.main import main

    assert callable(main)


def test_config_defaults():
    """Config should load with sensible defaults even without env vars."""
    from agent_eval.core.config import CONFIG

    assert CONFIG.GOOGLE_CLOUD_LOCATION == "us-central1"
    assert CONFIG.MAX_RETRIES == 3
    assert CONFIG.MAX_WORKERS == 4
    assert CONFIG.COL_PROMPT == "prompt"
