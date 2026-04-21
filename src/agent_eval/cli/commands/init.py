"""agent-eval init — scaffold the eval/ folder structure for a new agent project."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from agent_eval.cli._pacing import _PAUSE_LONG, _PAUSE_SHORT, _continue, _pause, styled_pager
from agent_eval.core.scaffold import scaffold_eval_structure

console = Console()

# Directories to skip when searching for agent.py
_SKIP_DIRS = {".venv", "venv", "site-packages", "node_modules", "__pycache__",
              ".git", ".adk", "sub_agents", "app_env", "eval_history"}

INTERACTION_MODES = [
    ("both", "Both (recommended)",
     "Generates files for both methods — use whichever fits when you're ready."),
    ("user-sim", "ADK User Sim (multi-turn)",
     "An LLM plays the role of a user, following scenario scripts you define.\n"
     "       Best for: conversational agents with back-and-forth dialogue."),
    ("diy", "DIY Interactions (single-turn)",
     "You send specific queries from a golden dataset to a running agent.\n"
     "       Best for: pipeline agents, deployed endpoints, or regression testing."),
]

STARTER_METRICS = [
    ("general_quality", "General Quality",
     "Overall response quality (Vertex AI built-in)", True),
    ("trajectory_accuracy", "Trajectory Accuracy",
     "Did the agent call the right tools in the right order?", True),
    ("tool_use_quality", "Tool Use Quality",
     "Were tool arguments correct and calls non-redundant?", False),
    ("safety", "Safety",
     "Safety compliance check (Vertex AI built-in)", False),
]

# Descriptions for generated files, shown in the summary
_FILE_DESCRIPTIONS = {
    "metrics/metric_definitions.json": "LLM-as-judge scoring rubrics",
    "scenarios/session_input.json": "Agent name + user ID for traces",
    "scenarios/conversation_scenarios.json": "User Sim scenario scripts",
    "eval_data/golden_dataset.json": "Test queries with expected behaviors",
    "results/.gitkeep": "Evaluation output directory",
}


def _find_agents(search_dir: Path) -> list[tuple[str, Path]]:
    """Find ADK agents by looking for agent.py files.

    Returns a list of (agent_module_name, agent_module_dir) tuples.
    Sub-agents (inside sub_agents/ directories) are excluded — they run as
    part of a parent agent and should be evaluated through the parent.
    """
    agents = []
    for agent_py in sorted(search_dir.rglob("agent.py")):
        if any(part in _SKIP_DIRS for part in agent_py.parts):
            continue
        module_dir = agent_py.parent
        agents.append((module_dir.name, module_dir))
    return agents


# ── Welcome preamble ──────────────────────────────────────────────────────


def _display_intro() -> None:
    """Brief, oriented welcome shown right after the banner.

    The goal: tell the user the *shape* of what's about to happen so the
    rest of the flow lands with context. No surprises, no sudden labels.
    """
    console.print()
    console.print("  [bold]Setting up evaluation for your agent.[/]")
    console.print("  [dim]This is a one-time scaffold — once it's done, you'll run[/] [cyan]agent-eval run[/] [dim]to evaluate.[/]")
    console.print()
    console.print("  [dim]Here's what we'll do together:[/]")
    console.print("    [dim]1.[/] Verify your Google Cloud environment is ready for Vertex AI Eval")
    console.print("    [dim]2.[/] Detect how to reach your agent (deployed Agent Engine, local ADK source, or both)")
    console.print("    [dim]3.[/] Pick the metrics that fit your agent")
    console.print("    [dim]4.[/] Generate scenarios + golden data and write everything to [cyan]eval/[/]")
    console.print()
    _pause(_PAUSE_LONG)


# ── Optional pre-step: legacy-layout migration prompt ──────────────────────


def _maybe_offer_legacy_migration(agent_dir: Path) -> None:
    """Detect a pre-unification eval/ layout and offer to migrate it in place.

    Newly scaffolded files land under ``tests/eval/`` after the SDK-aligned
    refactor. Existing projects with ``eval/scenarios/`` and ``eval/eval_data/``
    keep working via the path_resolver fallback, but the user is one prompt
    away from the canonical layout — we surface that prompt here.
    """
    from agent_eval.core.dataset_io import _find_legacy_eval_dir

    legacy = _find_legacy_eval_dir(agent_dir)
    if legacy is None:
        return

    has_scenarios = (legacy / "scenarios" / "conversation_scenarios.json").exists()
    has_golden = (legacy / "eval_data" / "golden_dataset.json").exists()
    if not (has_scenarios or has_golden):
        return

    unified = agent_dir / "tests" / "eval" / "dataset.jsonl"
    if unified.exists():
        # Already migrated — nothing to offer.
        return

    console.print()
    console.print("  [bold yellow]Legacy eval/ layout detected[/]")
    console.print(f"  [dim]Found:[/] [cyan]{legacy}[/]")
    console.print(
        "  [dim]Migrating folds [cyan]scenarios/[/] + [cyan]eval_data/[/] into a single "
        "[cyan]tests/eval/dataset.jsonl[/]. Originals are backed up — non-destructive.[/]"
    )
    try:
        confirm = questionary.confirm(
            "Migrate to the unified tests/eval/ layout now?",
            default=True,
        ).unsafe_ask()
    except (KeyboardInterrupt, Exception):
        return

    if not confirm:
        console.print("  [dim]Skipped. Run `agent-eval migrate` later when you're ready.[/]")
        return

    from agent_eval.core.dataset_io import migrate_legacy
    summary = migrate_legacy(agent_dir)
    console.print(f"  [green]>[/] Wrote [bold]{summary['total_rows']}[/] rows to [cyan]{summary['output_path']}[/]")
    if summary.get("backup_dir"):
        console.print(f"  [dim]Originals backed up to:[/] [cyan]{summary['backup_dir']}[/]")


# ── Step 0: Environment readiness check ────────────────────────────────────


def _verify_environment(auto_approve: bool = False) -> None:
    """Confirm the GCP env is ready for evaluation, or point at `agent-eval setup`.

    The heavy lifting — gcloud auth, ADC, API enablement, autorater binding —
    lives in `agent-eval setup`. Init only verifies the post-setup state so it
    can proceed, or stop early with a clear "run setup first" pointer. The
    `auto_approve` flag is accepted for signature compatibility but doesn't
    change behavior here: we never prompt to fix things, we just check.
    """
    from dotenv import load_dotenv

    # Lazy import — setup.py imports _pause from this module, so a top-level
    # import the other way would create a cycle at module load time.
    from agent_eval.cli.commands.setup import (
        _adc_file_path,
        _check_api_enabled as _setup_check_api,
    )

    load_dotenv(override=True)

    console.print(Rule(style="dim"))
    console.print()
    console.print("  [bold]Step 1 — Checking your Google Cloud environment[/]")
    console.print(
        "  [dim]Eval needs a project, ADC credentials, and the Vertex AI API enabled.[/]"
    )
    console.print(
        "  [dim]All of that is set up by[/] [cyan]agent-eval setup[/][dim] — this is just a quick check.[/]"
    )
    _pause()

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1"
    missing: list[str] = []

    console.print()
    if project:
        console.print(f"  [green]>[/] GOOGLE_CLOUD_PROJECT = [cyan]{project}[/]")
    else:
        console.print("  [red]x[/] GOOGLE_CLOUD_PROJECT is not set")
        missing.append("project")

    console.print(f"  [green]>[/] GOOGLE_CLOUD_LOCATION = [cyan]{location}[/]")

    adc_file = _adc_file_path()
    if adc_file.exists():
        console.print("  [green]>[/] Application Default Credentials present")
    else:
        console.print("  [red]x[/] Application Default Credentials not found")
        console.print(f"      [dim]expected at:[/] [dim]{adc_file}[/]")
        missing.append("adc")

    if project:
        api_ok = _setup_check_api(project, "aiplatform.googleapis.com")
        if api_ok is True:
            console.print("  [green]>[/] Vertex AI API is enabled")
        elif api_ok is False:
            console.print("  [red]x[/] Vertex AI API is not enabled on this project")
            missing.append("api")
        else:
            console.print("  [dim]-[/] Vertex AI API status — could not verify (gcloud unavailable)")

    if missing:
        console.print()
        console.print("  [yellow]![/] Your Google Cloud environment isn't ready yet.")
        console.print(
            "  [dim]Run this first — it walks the same checks and fixes anything missing:[/]"
        )
        console.print()
        console.print("      [bold cyan]agent-eval setup[/]")
        console.print()
        console.print("  [dim]Then re-run[/] [cyan]agent-eval init[/][dim].[/]")
        raise click.Abort()

    if not auto_approve:
        _continue("Next: selecting which agent to evaluate →", console=console)


# ── Path detection (Vertex AI GenAI Eval execution path) ──────────────────


def _display_path_detection(search_dir: Path) -> "PathDetection":  # noqa: F821
    """Detect and explain how we'll reach the user's agent.

    The narrative leads with the *local* pipeline (always available, the
    typical starting point) and frames a deployed Agent Engine as a
    streamlined single-turn pass that *adds on top* — they compose, never
    replace each other.

    BYOD is roadmap-only (see docs/reference.md).
    """
    from agent_eval.core.path_detector import (
        PathDetection,
        _detect_agent_engine,
        _detect_local_adk,
    )

    console.print()
    console.print(Rule(style="dim"))
    console.print()
    console.print("  [bold]Step 3 — Figuring out how to reach your agent[/]")
    console.print()
    console.print(
        "  [dim]── Why this step ──[/]"
    )
    console.print(
        "  [dim]Before[/] [bold]agent-eval[/] [dim]can score your agent, it needs to[/] [bold]run it against[/]"
    )
    console.print(
        "  [bold]test inputs[/] [dim]and[/] [bold]capture what happens[/] [dim]— every prompt, response, tool[/]"
    )
    console.print(
        "  [dim]call, and execution trace. This step decides[/] [bold]how agent-eval reaches your[/]"
    )
    console.print(
        "  [bold]agent[/] [dim]to do that capture.[/]"
    )
    console.print()
    console.print(
        "  [dim]The[/] [bold]local pipeline[/] [dim]is the default — it imports your[/] [cyan]agent.py[/] "
        "[dim]directly so you can[/]"
    )
    console.print(
        "  [dim]iterate on changes without deploying. If we[/] [bold]also[/] [dim]find an Agent Engine deployment[/]"
    )
    console.print(
        "  [dim]for the same agent, we[/] [bold]additionally[/] [dim]wire up Vertex's streamlined single-turn pass —[/]"
    )
    console.print(
        "  [dim]the two[/] [bold]compose[/][dim], they don't replace each other.[/]"
    )
    console.print()
    console.print(
        "  [dim]Either way, the captured interactions land in a single file:[/]"
    )
    console.print()
    console.print(
        "      [cyan]tests/eval/dataset.jsonl[/]   [dim](canonical SDK columns — see Step 4 backgrounder)[/]"
    )
    console.print()
    console.print(
        "  [dim]Step 4 hands that file to Vertex's[/] [cyan]client.evals.evaluate()[/] [dim]for scoring. The[/]"
    )
    console.print(
        "  [dim]format maps directly to the docs' dataset spec:[/]"
    )
    console.print(
        "  [cyan]https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-dataset[/]"
    )
    _continue("Next: how agent-eval reaches your agent →", console=console)
    console.print()
    console.print(
        "  [dim]── Two ways agent-eval can collect that interaction data ──[/]"
    )
    console.print()
    console.print(
        "    [bold cyan]Local pipeline[/]      [bold]Local ADK source (or any ADK FastAPI URL)[/]  "
        "[dim]— UserSim multi-turn + interact single-turn, full traces.[/]"
    )
    console.print(
        "             [dim italic]UserSim docs:[/] [cyan]https://adk.dev/evaluate/user-sim/[/]"
    )
    console.print(
        "    [bold cyan]Streamlined pass[/]    [bold]Deployed to Agent Engine[/]                  "
        "[dim]— Vertex calls your agent for us (managed, single-turn). Adds on top.[/]"
    )
    console.print()

    # ── Scan 1: deployed Agent Engine ──
    _continue("Next: look for a deployed Agent Engine →", console=console)
    with console.status(
        "  [dim]Looking for an Agent Engine deployment...[/]",
        spinner="dots",
    ):
        _pause(_PAUSE_LONG)
        ae_detection = _detect_agent_engine(search_dir)

    console.print()

    if ae_detection is not None:
        console.print(
            "  [green]>[/] [bold]Found a deployed Agent Engine.[/]  "
            "[dim](streamlined pass available)[/]"
        )
        console.print(f"    [dim]How we know:[/]  {ae_detection.evidence}")
        if ae_detection.agent_engine_resource:
            console.print(
                f"    [dim]Resource:   [/]  [cyan]{ae_detection.agent_engine_resource}[/]"
            )
        console.print()
        _pause()
        console.print("  [bold]What this adds to your eval:[/]")
        console.print(
            "    [dim]>[/] [cyan]agent-eval agent-engine[/] sends your dataset to Vertex's [cyan]create_evaluation_run()[/]."
        )
        console.print(
            "    [dim]>[/] Vertex calls your deployed agent, scores the responses,"
        )
        console.print(
            "    [dim]>[/] and uploads results to GCS — all in one managed call. No local server needed."
        )
        console.print()
        _pause()
        console.print(
            "    [yellow]Heads-up:[/] [cyan]create_evaluation_run()[/] is "
            "[bold]single-turn only[/] — no multi-turn replay,"
        )
        console.print(
            "    no built-in user simulator. We'll see next whether the local pipeline picks up the slack ↓"
        )
    else:
        console.print(
            "  [yellow]·[/] [bold]No Agent Engine deployment found here.[/] "
            "[dim](that's fine — local pipeline still works)[/]"
        )
        console.print(
            "    [dim italic]No[/] [cyan]deployment_metadata.json[/] [dim italic]with[/] "
            "[cyan]remote_agent_engine_id[/][dim italic], and no[/] "
            "[cyan]AGENT_ENGINE_RESOURCE_NAME[/] [dim italic]env var.[/]"
        )

    # ── Scan 2: local ADK source ──
    console.print()
    _continue("Next: look for local source for the same agent →", console=console)
    with console.status(
        "  [dim]Looking for a local agent.py...[/]",
        spinner="dots",
    ):
        _pause(_PAUSE_LONG)
        local_detection = _detect_local_adk(search_dir)

    console.print()

    if local_detection is not None:
        local_count = len(local_detection.local_agents)
        first = local_detection.local_agents[0]
        try:
            rel = first.relative_to(search_dir)
        except ValueError:
            rel = first
        extra = f" (+{local_count - 1} more)" if local_count > 1 else ""

        if ae_detection is not None:
            # Both surfaces detected — connect them: the local pipeline runs
            # against this agent.py, and the streamlined pass runs against the
            # already-detected deployment.
            console.print(
                "  [green]+[/] [bold]Local source for the same agent is also here.[/]  "
                "[dim](local pipeline available too — both compose)[/]"
            )
            console.print(f"    [dim]How we know:[/]  agent.py at {rel}{extra}")
            console.print()
            _pause()
            console.print(
                "    [dim]>[/] [bold]agent-eval[/]'s local UserSim imports your agent module directly"
            )
            console.print(
                "    [dim]>[/] (no FastAPI server needed) — so [bold]multi-turn coverage is on the table[/]"
            )
            console.print(
                "    [dim]>[/] alongside the streamlined single-turn pass."
            )
        else:
            console.print(
                "  [green]>[/] [bold]Found a local ADK agent.[/]  "
                "[dim](local pipeline ready)[/]"
            )
            console.print(f"    [dim]How we know:[/]  agent.py at {rel}{extra}")
            console.print()
            _pause()
            console.print("  [bold]What this means for your eval:[/]")
            console.print(
                "    [dim]>[/] [bold]Multi-turn conversations[/] — we'll start your agent locally and drive it"
            )
            console.print(
                "      with ADK's [cyan]UserSim[/] (an LLM playing the role of a scripted user)."
            )
            console.print(
                "    [dim]>[/] [bold]Single-turn queries[/] — [cyan]agent-eval interact[/] hits ADK's REST endpoints"
            )
            console.print(
                "      ([cyan]/run[/], [cyan]/debug/trace[/]) on whatever URL you point it at — local dev,"
            )
            console.print(
                "      Cloud Run, or any other ADK FastAPI host."
            )
            console.print(
                "    [dim]>[/] [bold]Scoring[/] — every trace converges at Vertex's "
                "[cyan]client.evals.evaluate()[/] with the metrics you'll pick in a moment."
            )
            console.print()
            _pause()
            console.print(
                "    [dim italic]Heads-up: if you later run this against a Cloud Run deployment, "
                "ADK's debug traces aren't always persisted there — we'll fall back to "
                "state-derived metrics only.[/]"
            )
    else:
        if ae_detection is not None:
            console.print(
                "  [yellow]·[/] [bold]No local agent.py found nearby.[/]  "
                "[dim](streamlined Agent Engine pass only — point[/] [cyan]--target-dir[/] [dim]at agent.py to also enable UserSim)[/]"
            )
        else:
            console.print(
                "  [yellow]>[/] [bold]Couldn't auto-detect a local agent or a deployment here.[/]"
            )
            console.print()
            _pause()
            console.print("  [bold]What this means for your eval:[/]")
            console.print(
                "    [dim]>[/] We'll scaffold a starter [cyan]tests/eval/dataset.jsonl[/] you can hand-edit,"
            )
            console.print(
                "    [dim]>[/] then point [cyan]agent-eval interact --base-url <url>[/] at any ADK"
            )
            console.print(
                "    [dim]>[/] FastAPI endpoint (local dev, Cloud Run, or any host) to collect traces."
            )
            console.print()
            _pause()
            console.print(
                "    [dim italic]Have non-ADK traces? See[/] [cyan]docs/reference.md[/] [dim italic]→ "
                "Experimental & on the roadmap (BYOD ingest is in design).[/]"
            )

    # Compose the unified PathDetection downstream code expects.
    if ae_detection is not None and local_detection is not None:
        ae_detection.local_agents = local_detection.local_agents
        ae_detection.evidence = (
            f"{ae_detection.evidence}; also found {local_detection.evidence}"
        )
        detection: PathDetection = ae_detection
    elif ae_detection is not None:
        detection = ae_detection
    elif local_detection is not None:
        detection = local_detection
    else:
        detection = PathDetection(
            path="unknown",
            evidence="no agent.py or deployment metadata found",
        )

    console.print()
    _continue("Next: configuring the metrics that will score your agent →", console=console)
    return detection


def _derive_chosen_paths(detection) -> set[str]:  # noqa: ANN001
    """Derive which evaluation surfaces to scaffold from what was detected.

    Local source and a deployed Agent Engine *compose* — UserSim imports
    ``agent.py`` directly and works fine alongside the managed pass — so
    there's no chooser. Every detected surface is included automatically.

    Returns a subset of ``{"A", "B"}``:
    - local source detected → ``"B"`` (local pipeline)
    - Agent Engine deployment detected → ``"A"`` (streamlined single-turn pass)
    - both detected → both
    - neither → ``set()`` (caller defaults to local-only — the typical
      "I'm iterating before deploying" starting point)
    """
    if detection.path == "unknown":
        return set()

    chosen: set[str] = set()
    if detection.local_agents:
        chosen.add("B")
    if detection.agent_engine_resource is not None:
        chosen.add("A")
    if not chosen:
        # Belt-and-braces — `path` was set but neither marker fields were.
        chosen.add(detection.path)
    return chosen


def _prompt_path_choice(detection) -> set[str]:  # noqa: ANN001
    """Announce what we'll scaffold based on detection — no chooser.

    The local pipeline (``simulate`` + ``interact`` + ``evaluate`` + ``analyze``)
    is the default: it works against any local ``agent.py`` and is what most
    people use while iterating. A detected Agent Engine deployment *adds* the
    streamlined ``create_evaluation_run`` pass on top — never replaces local.
    """
    chosen = _derive_chosen_paths(detection)

    console.print()
    if chosen == {"A", "B"}:
        console.print(
            "  [green]>[/] Scaffolding the [bold]local pipeline[/] [dim]+[/] "
            "the [bold]Agent Engine streamlined pass[/]."
        )
        console.print(
            "    [dim]They compose — keep iterating locally, re-run the streamlined pass to confirm against the deployed agent.[/]"
        )
    elif chosen == {"B"}:
        console.print(
            "  [green]>[/] Scaffolding the [bold]local pipeline[/] only."
        )
        console.print(
            "    [dim]No deployment detected — that's the typical starting point. Deploy with[/] "
            "[cyan]make backend[/] [dim](or any agent_engine target) to also unlock the streamlined pass.[/]"
        )
    elif chosen == {"A"}:
        console.print(
            "  [yellow]·[/] Scaffolding the [bold]Agent Engine streamlined pass[/] only."
        )
        console.print(
            "    [dim]No local[/] [cyan]agent.py[/] [dim]found nearby — point us at it with[/] "
            "[cyan]--target-dir <path>[/] [dim]to also enable the local UserSim pipeline.[/]"
        )
    # chosen == set() → caller falls back to local-only and prints its own
    # message; no announcement here.

    return chosen


# ── Step 2: Agent Selection ─────────────────────────────────────────────────


def _prompt_agent_selection(agents: list[tuple[str, Path]], search_dir: Path) -> tuple[str, Path]:
    """Let the user select which discovered agent to scaffold for."""
    console.print()
    console.print("  [bold]Step 2 — Selecting your agent[/]")
    console.print("  [dim]The agent module is the folder containing your agent.py, tools, and prompts.[/]")
    console.print("  [dim]The eval/ folder will be created inside it.[/]")
    console.print()

    for i, (name, module_dir) in enumerate(agents, 1):
        rel_path = module_dir.relative_to(search_dir)
        console.print(f"    [bold]{i}.[/] [cyan]{name}/[/]  [dim]→ {rel_path}/agent.py[/]")

    if len(agents) > 1:
        console.print()
        console.print("  [dim]Sub-agents (inside sub_agents/) are excluded —[/]")
        console.print("  [dim]evaluate them through their parent agent.[/]")

    console.print()
    if len(agents) == 1:
        choice = IntPrompt.ask("  Select agent", default=1)
    else:
        choice = IntPrompt.ask(f"  Select agent [dim](1-{len(agents)})[/]")

    while choice < 1 or choice > len(agents):
        console.print(f"  [red]Please enter a number between 1 and {len(agents)}[/]")
        choice = IntPrompt.ask("  Select agent")

    selected = agents[choice - 1]
    _continue("Next: figuring out how to reach this agent →", console=console)
    return selected


def _prompt_agent_name_manual() -> tuple[str, Path]:
    """Prompt for agent module path when no agents are discovered."""
    console.print()
    console.print("  [bold]Step 2 — Selecting your agent[/]")
    console.print()
    console.print("  [yellow]![/] No ADK agents found in the current directory tree.")
    console.print("  [dim]An ADK agent is identified by a folder containing an agent.py file.[/]")
    console.print("  [dim]You can still scaffold eval/ manually — enter the path to your agent module.[/]")

    console.print()
    target_input = Prompt.ask(
        "  Agent module path [dim](folder with agent.py)[/]",
        default="app",
    )
    target = Path(target_input)
    _continue("Next: figuring out how to reach this agent →", console=console)
    return target.name, target


# ── Step 3 sub-prompt: Interaction Mode (local pipeline only) ──────────────


def _prompt_interaction_mode(chosen_paths: set[str] | None = None) -> str:
    """Prompt for interaction mode (user-sim / diy / both).

    When ``chosen_paths == {"A"}`` the prompt is skipped — the streamlined
    Agent Engine pass scaffolds only ``tests/eval/dataset.jsonl``, no
    scenarios (there's no local agent to drive). Returns ``"dataset-only"``
    in that case so downstream code can branch on it.
    """
    if chosen_paths == {"A"}:
        console.print()
        console.print(
            "  [dim]Streamlined Agent Engine pass scaffolds[/] [cyan]tests/eval/dataset.jsonl[/] "
            "[dim]only — no scenarios needed (no local agent to drive).[/]"
        )
        return "dataset-only"

    console.print()
    console.print("  [bold]Choose interaction mode[/] [dim](sub-step of Step 3 — how the local pipeline drives your agent)[/]")
    console.print("  [dim]How will you generate traces for evaluation?[/]")
    console.print("  [dim]This determines which starter files are created.[/]")
    console.print()

    for i, (_, label, desc) in enumerate(INTERACTION_MODES, 1):
        console.print(f"    [bold]{i}.[/] [cyan]{label}[/]")
        console.print(f"       [dim]{desc}[/]")
        if i < len(INTERACTION_MODES):
            console.print()

    console.print()
    console.print("  [dim]Both is recommended — having both file types ready makes switching easy later.[/]")

    console.print()
    choice = IntPrompt.ask("  Select", default=1)
    while choice < 1 or choice > len(INTERACTION_MODES):
        console.print(f"  [red]Please enter a number between 1 and {len(INTERACTION_MODES)}[/]")
        choice = IntPrompt.ask("  Select", default=1)

    selected = INTERACTION_MODES[choice - 1][0]

    # Surface the Cloud Run trace caveat when DIY (live URL) is involved.
    # Vertex AI's ADK FastAPI sub-modes differ in trace persistence: local
    # dev keeps full traces, but Cloud Run often does not. Existing code
    # at processor.py:56-73 already degrades gracefully (latency_data=None,
    # state-derived metrics still work) — but the user should know upfront.
    if selected in ("diy", "both"):
        console.print()
        console.print(
            "  [yellow]![/] [bold]Cloud Run trace caveat[/]"
        )
        console.print(
            "  [dim]If you point DIY at a Cloud Run URL, traces often don't persist —[/]"
        )
        console.print(
            "  [dim]you'll get state-derived metrics only (no latency/spans/tools).[/]"
        )
        console.print(
            "  [dim]For full trace fidelity, deploy to Agent Engine instead:[/]"
        )
        console.print(
            "  [dim]  uvx agent-starter-pack enhance --adk -d agent_engine && make backend[/]"
        )

    return selected


# ── Step 4: Metrics ─────────────────────────────────────────────────────────


def _prompt_metrics_choice(agent_dir: Path, agent_name: str) -> tuple[list[str], dict | None, dict | None, dict | None]:
    """Let user choose between starter metrics or AI-generated metrics.

    Returns (starter_metric_keys, custom_definitions_or_None, recommendations_or_None, agent_analysis_or_None).
    """
    console.print()
    console.print(Rule(style="dim"))
    console.print()
    console.print("  [bold]Step 4 — Configuring the metrics that will score your agent[/]")
    console.print("  [dim]Deterministic metrics (latency, tokens, cost) are always included — they come for free[/]")
    console.print("  [dim]from the trace. Now we'll pick the LLM-as-judge metrics that grade content quality.[/]")
    _pause()

    return _prompt_ai_metrics_multistep(agent_dir, agent_name)


def _prompt_starter_metrics() -> list[str]:
    """Original starter metrics toggle UI."""
    selected = [key for key, _, _, default in STARTER_METRICS if default]

    console.print()
    _draw_metrics(selected)

    console.print("\n  [dim]Enter numbers to toggle, or press Enter to continue.[/]")

    while True:
        raw = Prompt.ask("  Toggle", default="")
        if raw.strip() == "":
            break
        try:
            idx = int(raw.strip()) - 1
            if 0 <= idx < len(STARTER_METRICS):
                key = STARTER_METRICS[idx][0]
                if key in selected:
                    selected.remove(key)
                else:
                    selected.append(key)
                console.print()
                _draw_metrics(selected)
                console.print()
        except ValueError:
            console.print("  [red]Enter a number or press Enter to continue.[/]")

    return selected


def _display_metrics_education(managed_metrics: Dict[str, Dict]) -> None:
    """Walk the user through the relevant Vertex AI eval docs before the picker.

    Three short backgrounders, in the order the docs sidebar uses:
      1. The SDK call we'll run for them when they later run `agent-eval evaluate`.
      2. The canonical dataset columns each row in `tests/eval/dataset.jsonl` may use.
      3. The four families managed metrics belong to.
    Then a callout that the picker is SDK-introspected — resilient to upstream changes.
    """
    from rich.syntax import Syntax
    from agent_eval.core import metric_families

    # Mirror the picker's grouping (anything classified as "custom" — i.e. GCS YAML
    # metrics like COHERENCE / FLUENCY — gets bucketed as adaptive in the picker).
    family_counts: Dict[str, int] = {}
    for key, info in managed_metrics.items():
        family = metric_families.classify(info.get("managed_metric_name") or key)
        if family == "custom":
            family = "adaptive_rubric"
        family_counts[family] = family_counts.get(family, 0) + 1

    try:
        import importlib.metadata
        sdk_version = importlib.metadata.version("google-cloud-aiplatform")
    except Exception:
        sdk_version = "installed"

    # ── Background 1 — the SDK call ──────────────────────────────────────
    console.print()
    console.print("  [dim]── Background 1 of 3 — the SDK call we'll run for you ──[/]")
    console.print()
    console.print("  [dim]When you later run[/] [cyan]agent-eval evaluate[/][dim], we hand the dataset and[/]")
    console.print("  [dim]the metrics you select below to the Vertex AI Evaluation SDK like this:[/]")
    console.print()
    code = (
        "from vertexai import Client, types\n\n"
        "client = Client(project=PROJECT, location=LOCATION)\n\n"
        "result = client.evals.evaluate(\n"
        '    dataset=eval_dataset,              # tests/eval/dataset.jsonl\n'
        "    metrics=[ ...your selections... ], # SDK Metric objects\n"
        ")"
    )
    console.print(Syntax(code, "python", theme="monokai", padding=(0, 4), background_color="default"))
    console.print()
    console.print("  [dim]Docs:[/] [cyan]https://cloud.google.com/vertex-ai/generative-ai/docs/models/run-evaluation[/]")
    _continue("Next: dataset columns →", console=console)

    # ── Background 2 — the dataset columns ───────────────────────────────
    console.print()
    console.print("  [dim]── Background 2 of 3 — the columns each row in your dataset may use ──[/]")
    console.print()
    console.print("  [dim]Each row in[/] [cyan]tests/eval/dataset.jsonl[/] [dim]is a JSON object. You don't need every[/]")
    console.print("  [dim]column on every row — different metrics consume different columns:[/]")
    console.print()
    cols = Table(show_header=False, box=None, padding=(0, 2), show_edge=False)
    cols.add_column(style="cyan", min_width=22)
    cols.add_column(style="dim")
    cols.add_row("prompt", "user input — always present")
    cols.add_row("response", "agent's text reply — filled in at runtime by simulate / interact")
    cols.add_row("reference", "expected answer — used by computation + final_response_match")
    cols.add_row("conversation_history", "multi-turn dialogue — multi_turn_* metrics")
    cols.add_row("intermediate_events", "tool calls + thoughts — tool_use_quality")
    cols.add_row("session_inputs", "ADK session init (app_name, user_id, state)")
    cols.add_row("expected_*", "free-form columns surfaced to custom metric templates")
    console.print(cols)
    console.print()
    console.print("  [dim]Docs:[/] [cyan]https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-dataset[/]")
    _continue("Next: the four metric families →", console=console)

    # ── Background 3 — the four families ─────────────────────────────────
    console.print()
    console.print("  [dim]── Background 3 of 3 — the four families managed metrics belong to ──[/]")
    console.print()
    console.print("  [dim]Knowing the family tells you what data the metric needs and how it's scored.[/]")
    console.print("  [dim]The picker below groups its options by family in this exact order.[/]")
    console.print()
    fams = Table(show_header=True, header_style="bold dim", box=None, padding=(0, 2), show_edge=False)
    fams.add_column("Family", style="bold cyan", min_width=18)
    fams.add_column("How it's scored", style="dim", min_width=44)
    fams.add_column("Reference?", style="dim")
    fams.add_row("Adaptive Rubric", "Judge LLM generates rubrics on the fly", "optional")
    fams.add_row("Static Rubric", "Judge LLM applies a fixed rubric (safety / grounding)", "optional")
    fams.add_row("Computation", "Deterministic math (BLEU, ROUGE, exact_match, tool_*)", "[bold]required[/]")
    fams.add_row("Translation", "Niche — translation-quality scorers (comet, metricx)", "[bold]required[/]")
    console.print(fams)
    console.print()
    console.print("  [dim]Docs:[/] [cyan]https://cloud.google.com/vertex-ai/generative-ai/docs/models/rubric-metric-details[/]")
    _pause(_PAUSE_LONG)

    # ── Resilience callout ───────────────────────────────────────────────
    counts_str = " · ".join(
        f"{family_counts.get(f, 0)} {label}"
        for f, label in [
            ("adaptive_rubric", "adaptive"),
            ("static_rubric", "static"),
            ("computation", "computation"),
            ("translation", "translation"),
        ]
        if family_counts.get(f, 0) > 0
    )
    console.print()
    console.print(
        f"  [green]>[/] [dim]Found[/] [bold]{len(managed_metrics)}[/] [dim]managed metrics in[/] "
        f"[cyan]google-cloud-aiplatform=={sdk_version}[/]  [dim]({counts_str})[/]"
    )
    console.print(
        "  [dim]Pulled live via[/] [cyan]metric_families.classify()[/] [dim]reading the installed SDK —[/]"
    )
    console.print(
        "  [dim]when Google adds a new managed metric upstream, this picker stays current automatically.[/]"
    )
    console.print()
    console.print(
        "  [yellow]Heads-up:[/] [dim]you'll[/] [bold]pick from this catalog[/] [dim]in the very next step,[/]"
    )
    console.print(
        "  [dim]so take a moment to read what each metric scores. Inside the pager:[/]"
    )
    console.print(
        "  [bold]↑/↓[/] [dim]or[/] [bold]Space[/] [dim]to scroll ·[/] [bold]q[/] [dim]to exit when done.[/]"
    )
    _continue("Next: open the metrics catalog →", console=console)


def _prompt_managed_metrics_selection(
    managed_metrics: Dict[str, Dict],
    preselected: Optional[set] = None,
) -> Dict[str, Dict]:
    """Arrow-key checkbox selection for managed metrics.

    Uses questionary.checkbox() with grouped separators for a clean UX.
    Returns a dict of selected metric entries ready for metric_definitions.json.

    Args:
        managed_metrics: All available managed metrics from SDK discovery.
        preselected: Keys to pre-check. If None, defaults to general_quality + safety.
    """
    # Per the Vertex AI docs ("Determine your evaluation strategy"):
    # "We recommend starting with GENERAL_QUALITY as the default."
    # Everything else is opt-in via the checkbox below.
    defaults = preselected if preselected is not None else {"general_quality"}
    # Track whether `defaults` came from an existing metric_definitions.json
    # so the picker's helper text can honestly say "loaded from your file"
    # vs "the Vertex AI docs' recommended starting point". Without this, the
    # message lies whenever a re-run finds non-default selections.
    _from_existing_file = preselected is not None and bool(preselected)

    # Group by metric family (adaptive/static/computation/translation) per the
    # plan §3.4. Family classification comes from SDK introspection — adding a
    # new managed metric upstream lands it in the right group automatically.
    from agent_eval.core import metric_families

    # Known families with curated ordering and display labels (see
    # `family_short` / `family_subtitle` below). If the SDK ever introduces a
    # new family, we still surface it — under its raw key, with a "not yet
    # curated" subtitle — at the end of the list rather than silently dropping
    # it into adaptive_rubric.
    KNOWN_FAMILY_ORDER = ["adaptive_rubric", "static_rubric", "computation", "translation"]
    grouped: Dict[str, Dict[str, Dict]] = {f: {} for f in KNOWN_FAMILY_ORDER}

    for key, info in managed_metrics.items():
        family = metric_families.classify(info.get("managed_metric_name") or key)
        if family == "custom":
            # `metric_families.classify` returns "custom" for GCS-YAML legacy
            # rubric metrics (COHERENCE, FLUENCY, …); they belong in adaptive.
            family = "adaptive_rubric"
        grouped.setdefault(family, {})[key] = info

    # Order: known families first (curated), then any new ones the SDK invents.
    family_order = KNOWN_FAMILY_ORDER + [
        f for f in grouped if f not in KNOWN_FAMILY_ORDER
    ]

    def _tag_for(info: Dict) -> str:
        """Short capability gate that decides whether a metric can run on the user's data."""
        if info.get("requires_multi_turn") or info.get("applies_to") == "scenarios":
            return "multi-turn"
        if info.get("requires_reference"):
            return "needs ref"
        return ""

    # ── Step 1: Rich catalog table ────────────────────────────────────────
    # Why Rich (not a fake table built inside questionary choices): Rich
    # auto-wraps long descriptions, adapts to terminal width, and does its own
    # box drawing. Manual width math + `…` truncation inside questionary
    # choices breaks the moment any value grows or the terminal shrinks.
    console.print()
    console.print("  [bold]Now pick which managed metrics to enable[/]")
    console.print(
        "  [dim]Same four families you just saw, grouped the same way. "
        "Catalog first, picker right after.[/]"
    )
    console.print()

    # Render one sub-table per family, sandwiched between Rich rules. This
    # keeps the Name column from being widened by long family titles, and
    # gives each family a clear visual block.
    family_subtitle = {
        "adaptive_rubric": "LLM-generated rubrics, judge-scored — start here",
        "static_rubric":   "Fixed criteria — safety, grounding, hallucination",
        "computation":     "Deterministic — needs reference",
        "translation":     "Translation-quality scorers — needs reference",
    }
    family_short = {
        "adaptive_rubric": "Adaptive Rubric",
        "static_rubric":   "Static Rubric",
        "computation":     "Computation",
        "translation":     "Translation",
    }

    def _family_label(key: str) -> str:
        """Display label for a family key, with a graceful fallback for new SDK families."""
        return family_short.get(key, key.replace("_", " ").title())

    def _family_subtitle(key: str) -> str:
        return family_subtitle.get(key, "[new family from SDK — not yet curated]")

    # Iteration counter the catalog reads to vary the "Pre-checked" wording
    # between the first render and re-opens. Dict-wrapped so the closure can
    # mutate it without `nonlocal` gymnastics.
    _picker_iteration = {"count": 0}

    # Catalog rendering lives in a closure so we can re-render it if the user
    # picks the "↩ Reopen the catalog" sentinel from the picker.
    def _render_catalog() -> None:
        # Catalog goes through the system pager (less / more) so the user
        # controls the scroll instead of having content blast past. After they
        # press `q`, the picker opens with the terminal at the top.
        with styled_pager(console):
            console.rule("[bold]Managed metrics catalog[/]", style="grey50")
            for family in family_order:
                members = grouped[family]
                if not members:
                    continue
                console.print()
                console.print(
                    f"  [bold cyan]{_family_label(family)}[/]  "
                    f"[dim]· {_family_subtitle(family)}[/]"
                )
                sub = Table(
                    header_style="bold cyan",
                    border_style="grey50",
                    show_lines=False,
                    padding=(0, 1),
                    expand=True,
                )
                sub.add_column("Name", style="bold", no_wrap=True)
                sub.add_column("Range", justify="center", no_wrap=True)
                sub.add_column("Tag", no_wrap=True)
                sub.add_column("What it scores", overflow="fold", ratio=1)
                for key in sorted(members):
                    info = members[key]
                    sr = info.get("score_range", {})
                    score = f"{sr.get('min', '?')}-{sr.get('max', '?')}"
                    sub.add_row(
                        info["managed_metric_name"],
                        score,
                        _tag_for(info),
                        info.get("description", ""),
                    )
                console.print(sub)

            # Legend (about reading the tags) lives inside the pager.
            # Picker controls (toggle/navigate/confirm) live with the picker
            # itself, just below — that's where they're actually used.
            console.print()
            console.rule("[bold]Tag legend[/]", style="grey50")
            console.print()
            console.print(
                "  [bold]multi-turn[/] [dim]needs[/] [cyan]agent-eval simulate[/] [dim]rows[/]"
            )
            console.print(
                "  [bold]needs ref[/] [dim]needs the[/] [cyan]reference[/] [dim]column populated[/]"
            )
            console.print()
            console.print(
                "  [bold yellow]End of catalog.[/]  "
                "[dim]Press[/] [bold]q[/] [dim]to exit and open the picker.[/]"
            )
            console.rule(style="grey50")
        console.print()

        # ── Picker controls cheat-sheet (printed right before the prompt) ──
        console.print(
            "  [bold]Picker controls:[/]  "
            "[bold green]●[/] [dim]= selected ·[/]  [bold]○[/] [dim]= unselected ·[/]  "
            "[bold]space[/] [dim]toggles ·[/] [bold]↑/↓[/] [dim]navigates ·[/] "
            "[bold]enter[/] [dim]confirms[/]"
        )
        # Reflect what's actually pre-checked, and where it came from. Reading
        # `defaults` (mutated on reopen) keeps this honest across loop iterations.
        _checked_names = sorted(
            managed_metrics[k]["managed_metric_name"]
            for k in defaults
            if k in managed_metrics
        )
        _names_text = ", ".join(_checked_names) if _checked_names else "nothing"
        if _from_existing_file and not _picker_iteration["count"]:
            console.print(
                f"  [dim]Pre-checked from your existing[/] "
                f"[cyan]metric_definitions.json[/][dim]:[/] "
                f"[bold green]{_names_text}[/] [dim]— uncheck any you no longer want.[/]"
            )
        elif _picker_iteration["count"]:
            console.print(
                f"  [dim]Pre-checked:[/] [bold green]{_names_text}[/] "
                f"[dim]— your selections so far (preserved across reopens).[/]"
            )
        else:
            console.print(
                f"  [dim]Pre-checked for you:[/] [bold green]{_names_text}[/] "
                "[dim]— the Vertex AI docs' recommended starting point.[/]"
            )
        console.print(
            "  [dim]Forgot what something does? Tick[/] [bold]↩ Reopen the catalog[/] "
            "[dim](first option) and confirm — selections are kept.[/]"
        )
        console.print()

    picker_style = questionary.Style([
        ("qmark",       "fg:#00d7ff bold"),
        ("question",    "bold"),
        ("answer",      "fg:#5fff87 bold"),
        ("pointer",     "fg:#00d7ff bold"),
        ("highlighted", "fg:#00d7ff bold"),
        ("selected",    "fg:#5fff87 bold"),
        ("separator",   "fg:#6c6c6c bold"),
        ("instruction", "fg:#6c6c6c italic"),
    ])

    # Sentinel value for the "↩ Reopen the catalog" choice. If the user leaves
    # this checked when they confirm, we re-render the catalog (preserving
    # their other selections as defaults) and re-prompt.
    _REOPEN_CATALOG = "__reopen_catalog__"

    # ── Step 2: Lightweight picker ────────────────────────────────────────
    # Each choice is just NAME (+ optional [tag]). No fake columns, no
    # truncation, no width math — terminal width is irrelevant.
    while True:
        _render_catalog()
        _picker_iteration["count"] += 1

        choices: list = [
            questionary.Choice(
                "↩ Reopen the catalog (jump back to re-read — your selections are kept)",
                value=_REOPEN_CATALOG,
                checked=False,
            ),
            questionary.Separator(" "),
        ]
        for idx, family in enumerate(family_order):
            members = grouped[family]
            if not members:
                continue
            # Thin grouping marker — full label/subtitle live in the catalog above.
            choices.append(questionary.Separator(f"── {_family_label(family)} ──"))
            for key in sorted(members):
                info = members[key]
                tag = _tag_for(info)
                label = info["managed_metric_name"]
                if tag:
                    label = f"{label}  [{tag}]"
                choices.append(
                    questionary.Choice(label, value=key, checked=(key in defaults))
                )

        selected_keys = questionary.checkbox(
            "Select managed metrics:",
            choices=choices,
            instruction=" ",  # legend already printed above; keep prompt line clean
            style=picker_style,
            qmark="?",
        ).ask()

        if selected_keys is None:
            raise KeyboardInterrupt

        if _REOPEN_CATALOG in selected_keys:
            # Preserve everything else they had ticked so reopening doesn't
            # wipe their progress; loop back to re-render the catalog.
            defaults = {k for k in selected_keys if k != _REOPEN_CATALOG}
            console.print()
            console.print(
                "  [dim]↩ Reopening the catalog — your[/] "
                f"[bold]{len(defaults)}[/] [dim]selection"
                f"{'s' if len(defaults) != 1 else ''} so far[/] [dim]will be kept.[/]"
            )
            console.print()
            continue

        break

    # Build selected metrics dict
    from agent_eval.core.metric_discovery import get_metric_definition_entry
    selected: Dict[str, Dict] = {}
    for key in selected_keys:
        entry = get_metric_definition_entry(key, managed_metrics)
        if entry:
            selected[key] = entry

    # Recap grouped by family — confirms the choice and ties back to the
    # four-family taxonomy one last time.
    console.print()
    if selected:
        from collections import defaultdict as _defaultdict
        by_family: Dict[str, list] = _defaultdict(list)
        for key, entry in selected.items():
            fam = metric_families.classify(entry.get("managed_metric_name") or key)
            by_family[fam].append(entry.get("managed_metric_name") or key)

        console.print(
            f"  [green]✓[/] [bold]Selected {len(selected)} managed metric"
            f"{'s' if len(selected) != 1 else ''}[/]"
        )
        for fam in family_order:
            if fam not in by_family:
                continue
            names = ", ".join(sorted(by_family[fam]))
            console.print(f"    [dim]·[/] [bold cyan]{_family_label(fam)}[/] [dim]—[/] {names}")
    else:
        console.print(
            "  [yellow]>[/] [bold]No managed metrics selected.[/] "
            "[dim]Custom metrics are still available in the next step.[/]"
        )

    return selected


def _display_agent_analysis(analysis: Dict[str, Any]) -> None:
    """Display the agent analysis results in a Rich table."""
    console.print("  [bold]Your agent's evaluation data[/]")
    console.print("  [dim]These are the data points found in your code. Custom metrics[/]")
    console.print("  [dim]will be designed to evaluate your agent using this data.[/]")
    console.print()
    table = Table(
        border_style="cyan",
        padding=(0, 2),
    )
    table.add_column("Source", style="bold cyan", min_width=30)
    table.add_column("Description", ratio=2)

    # Always-available data
    table.add_row("user_inputs", "User messages (always available)")
    table.add_row("final_response", "Agent's final text response")
    table.add_row("trace_summary", "Execution trajectory summary")

    # Tools
    tools = analysis.get("tools", [])
    if tools:
        tool_names = ", ".join(t.get("name", "?") for t in tools[:5])
        table.add_row("tool_interactions", f"{len(tools)} tools: {tool_names}")

    # State variables
    state_vars = analysis.get("state_variables", {})
    for var_name, description in state_vars.items():
        table.add_row(f"state: {var_name}", str(description)[:60])

    # Sub-agents
    sub_agents = analysis.get("sub_agents", [])
    if sub_agents:
        agent_names = ", ".join(a.get("name", "?") for a in sub_agents[:5])
        table.add_row("sub_agent_trace", f"{len(sub_agents)} sub-agents: {agent_names}")

    # Conversation history
    table.add_row("conversation_history", "Full multi-turn conversation (if simulation)")

    console.print(table)
    console.print()
    console.print("  [dim]State variables are available via extracted_data:<name>[/]")
    console.print("  [dim]Creating state variables in your agent makes them[/]")
    console.print("  [dim]available for evaluation metrics automatically.[/]")

    # Key behaviors
    behaviors = analysis.get("key_behaviors", [])
    if behaviors:
        console.print()
        console.print("  [bold]Key behaviors to evaluate:[/]")
        for b in behaviors[:5]:
            console.print(f"    [dim]-[/] {b}")


def _display_state_suggestions(suggestions: list[dict]) -> None:
    """Display suggested state variables the user could add to their agent."""
    from rich.syntax import Syntax

    console.print()
    console.print("  [bold]Suggested state variables[/]")
    console.print("  [dim]Adding these to your agent code would enable richer evaluation metrics.[/]")
    console.print("  [dim]State variables saved during execution become available for metrics automatically.[/]")
    console.print("  [yellow]![/] [dim]These snippets are AI-generated — review carefully before pasting,[/]")
    console.print("    [dim]preserve your existing docstrings, and verify the function still returns correctly.[/]")
    console.print()

    for i, s in enumerate(suggestions, 1):
        name = s.get("name", "unknown")
        purpose = s.get("purpose", "")
        snippet = s.get("code_snippet", "")
        eval_use = s.get("evaluation_use", "")

        console.print(f"  [bold cyan]{i}. {name}[/]")
        console.print(f"     [dim]Purpose:[/] {purpose}")
        console.print(f"     [dim]Metric use:[/] {eval_use}")
        if snippet:
            console.print()
            syntax = Syntax(snippet, "python", theme="monokai", padding=1)
            console.print(syntax)
        console.print()

    console.print("  [dim]Learn more about ADK state management:[/]")
    console.print("  [cyan]https://adk.dev/sessions/state/#key-characteristics-of-state[/]")


def _prompt_ai_metrics_multistep(
    agent_dir: Path, agent_name: str,
) -> tuple[list[str], dict | None, dict | None, dict | None]:
    """Multi-step AI metric generation pipeline.

    Step 3a: Discover managed metrics + ADK knowledge
    Step 3b: User selects managed metrics
    Step 3c: Gemini Call 1 — Analyze agent source code
    Step 3d: Gemini Call 2 — Generate custom metric definitions
    Step 3e: Gemini Call 3 — Generate scenarios + golden data
    Step 3f: Display & confirm

    Returns (starter_keys, custom_definitions_or_None, recommendations_or_None, agent_analysis_or_None).
    """
    # ── Load existing eval files first ───────────────────────────────────
    existing_metrics = _load_existing_metrics(agent_dir)
    existing_scenarios, existing_golden = _load_existing_eval_data(agent_dir)

    # Split existing metrics into managed and custom
    existing_managed_keys: set = set()
    existing_custom: Dict[str, Any] = {}
    if existing_metrics:
        for k, v in existing_metrics.items():
            if isinstance(v, dict) and v.get("is_managed"):
                existing_managed_keys.add(k)
            elif isinstance(v, dict):
                existing_custom[k] = v

    # Show existing metrics summary if re-running
    if existing_metrics:
        console.print()
        console.print("  [bold]Existing metrics found[/]")
        if existing_managed_keys:
            managed_names = ", ".join(sorted(existing_managed_keys))
            console.print(f"  [green]>[/] {len(existing_managed_keys)} managed: [cyan]{managed_names}[/]")
        if existing_custom:
            custom_names = ", ".join(sorted(existing_custom.keys()))
            console.print(f"  [green]>[/] {len(existing_custom)} custom: [cyan]{custom_names}[/]")
        console.print("  [dim]Your existing selections will be pre-checked below.[/]")

    # ── Discover managed metrics from SDK ─────────────────────────────────
    console.print()
    managed_metrics = {}
    try:
        with console.status(
            "[bold blue]  Asking the Vertex AI Eval SDK what's available...[/]", spinner="dots"
        ):
            from agent_eval.core.metric_discovery import discover_managed_metrics
            managed_metrics = discover_managed_metrics()
            _pause(_PAUSE_LONG)
    except Exception as e:
        console.print(f"  [yellow]![/] Could not discover managed metrics: {e}")
        console.print("  [dim]Falling back to starter metrics.[/]")
        return _prompt_starter_metrics(), None, None, None

    # ── Hand-on-shoulder walk through the relevant docs ───────────────────
    _display_metrics_education(managed_metrics)

    # ── User selects managed metrics (intro lives inside the helper) ──────
    preselected = existing_managed_keys if existing_managed_keys else None
    selected_managed = _prompt_managed_metrics_selection(managed_metrics, preselected)

    if selected_managed:
        names = ", ".join(
            info["managed_metric_name"] for info in selected_managed.values()
        )
        console.print(f"\n  [green]Selected:[/] {names}")
    else:
        console.print("\n  [dim]No managed metrics selected.[/]")

    # ── Custom metrics priorities (always generated) ──────────────────────
    console.print()
    console.print("  [bold]Custom metrics[/]  [dim]— tailored to your agent's behaviors[/]")
    if existing_custom:
        console.print(f"  [dim]You have {len(existing_custom)} existing custom metric(s): "
                       f"{', '.join(sorted(existing_custom.keys()))}[/]")
        console.print("  [dim]Gemini will preserve and may improve them.[/]")
    console.print("  [dim]Guide what custom metrics should focus on (optional) — e.g., accuracy[/]")
    console.print("  [dim]of billing lookups, tool call efficiency, out-of-scope handling.[/]")
    console.print("  [dim]Press Enter to skip — Gemini will analyze the code on its own.[/]")
    console.print()
    user_priorities = Prompt.ask("  What should custom metrics focus on?", default="")
    generate_custom = True  # always generate; refine/skip loop is the user's off-ramp

    _continue("Next: scan your agent's code for evaluation data →", console=console)

    # ── Gemini Call 1 — Analyze agent source code ─────────────────────────
    console.print()
    console.print("  [bold cyan]Analyzing your agent's code[/]")
    console.print("  [dim]Reading agent.py, tools, and prompts to understand available evaluation data.[/]")
    console.print()
    agent_analysis: Dict[str, Any] = {}
    with console.status(
        "[bold blue]  Analyzing agent source code...[/]",
        spinner="dots",
    ):
        try:
            from agent_eval.core.metric_generator import analyze_agent_data
            agent_analysis = analyze_agent_data(agent_dir, agent_name)
        except Exception as e:
            console.print(f"  [yellow]Agent analysis failed:[/] {e}")
            console.print("  [dim]Continuing with default data assumptions.[/]")
            agent_analysis = {"tools": [], "state_variables": {}, "key_behaviors": []}

    if agent_analysis.get("tools") or agent_analysis.get("state_variables"):
        console.print()
        _display_agent_analysis(agent_analysis)

    # ── State variable suggestions + optional re-analyze ─────────────
    suggestions = agent_analysis.get("suggested_state_variables", [])

    if suggestions:
        _display_state_suggestions(suggestions)
        _continue("Next: re-analyze (if you added the snippets) or continue →", console=console)

        while True:
            console.print()
            console.print("    [bold]1.[/] [cyan]I've made changes[/] — re-analyze my agent")
            console.print("    [bold]2.[/] [green]Continue[/] — use current state variables")
            console.print()
            action = IntPrompt.ask("  Select", default=2)
            while action not in (1, 2):
                console.print("  [red]Please enter 1 or 2[/]")
                action = IntPrompt.ask("  Select", default=2)

            if action == 2:
                break

            console.print()
            console.print("  [bold cyan]Re-analyzing your agent's code[/]")
            console.print("  [dim]Reading updated agent.py, tools, and prompts...[/]")
            console.print()
            with console.status(
                "[bold blue]  Re-analyzing agent source code...[/]", spinner="dots",
            ):
                try:
                    from agent_eval.core.metric_generator import analyze_agent_data as _reanalyze
                    agent_analysis = _reanalyze(agent_dir, agent_name)
                except Exception as e:
                    console.print(f"  [yellow]Re-analysis failed:[/] {e}")
                    console.print("  [dim]Continuing with previous analysis.[/]")
                    break

            if agent_analysis.get("tools") or agent_analysis.get("state_variables"):
                console.print()
                _display_agent_analysis(agent_analysis)

            suggestions = agent_analysis.get("suggested_state_variables", [])
            if not suggestions:
                console.print()
                console.print("  [green]>[/] No additional state variable suggestions.")
                break

            _display_state_suggestions(suggestions)

    # ── Gemini Call 2 — Generate custom metrics (if opted in) ─────────────
    custom_metrics: Dict[str, Any] = {}
    rationale = ""

    if generate_custom:
        console.print()
        console.print("  [bold cyan]Generating custom scoring rubrics[/]")
        console.print("  [dim]Creating LLM-as-judge metrics tailored to your agent's specific behaviors.[/]")
        console.print("  [dim]These complement your selected managed metrics — they won't be replaced.[/]")
        console.print()
        with console.status(
            "[bold blue]  Generating custom metrics...[/]", spinner="dots"
        ):
            try:
                from agent_eval.core.metric_generator import generate_metric_definitions
                custom_metrics, rationale = generate_metric_definitions(
                    agent_dir=agent_dir,
                    agent_name=agent_name,
                    agent_analysis=agent_analysis,
                    selected_managed=selected_managed,
                    user_priorities=user_priorities,
                    existing_metrics=existing_metrics,
                )
            except Exception as e:
                console.print(f"\n  [yellow]Metric generation failed:[/] {e}")
                console.print("  [dim]Continuing with managed metrics only.[/]")

        # ── Confirm/Refine custom metrics ─────────────────────────────────
        if custom_metrics:
            console.print()
            _display_generated_metrics(custom_metrics, rationale)
            _continue("Next: accept, refine, or skip the generated metrics →", console=console)

            while True:
                console.print()
                console.print("    [bold]1.[/] [green]Accept[/] — use these metrics")
                console.print("    [bold]2.[/] [cyan]Refine[/] — provide feedback and regenerate")
                console.print("    [bold]3.[/] [yellow]Skip custom[/] — use managed metrics only")
                console.print()
                action = IntPrompt.ask("  Select", default=1)
                while action not in (1, 2, 3):
                    console.print("  [red]Please enter 1, 2, or 3[/]")
                    action = IntPrompt.ask("  Select", default=1)

                if action == 1:
                    break

                if action == 3:
                    custom_metrics = {}
                    break

                # action == 2: Refine
                console.print()
                console.print("  [bold]What should change?[/]")
                console.print("  [dim]Tell Gemini what to adjust — e.g., \"focus more on tool error[/]")
                console.print("  [dim]handling\", \"add a metric for latency awareness\"[/]")
                console.print()
                feedback = Prompt.ask("  Feedback")
                if not feedback.strip():
                    continue

                combined_priorities = user_priorities
                if combined_priorities:
                    combined_priorities += f"\n\nADDITIONAL FEEDBACK: {feedback}"
                else:
                    combined_priorities = f"FEEDBACK on previous generation: {feedback}"

                console.print()
                with console.status(
                    "[bold blue]Regenerating metrics...[/]", spinner="dots"
                ):
                    try:
                        custom_metrics, rationale = generate_metric_definitions(
                            agent_dir=agent_dir,
                            agent_name=agent_name,
                            agent_analysis=agent_analysis,
                            selected_managed=selected_managed,
                            user_priorities=combined_priorities,
                            existing_metrics=existing_metrics,
                        )
                    except Exception as e:
                        console.print(f"\n  [yellow]Regeneration failed:[/] {e}")
                        console.print("  [dim]Showing previous results.[/]")
                        continue

                user_priorities = combined_priorities
                console.print()
                _display_generated_metrics(custom_metrics, rationale)

    # ── Finalize metrics ──────────────────────────────────────────────────
    if not custom_metrics:
        custom_metrics = dict(selected_managed)
        if existing_custom:
            custom_metrics.update(existing_custom)

    # ── Test data guidance ────────────────────────────────────────────────
    console.print()
    console.print("  [bold cyan]Creating test scenarios and sample queries[/]")
    console.print("  [dim]Generating multi-turn conversation scripts (for simulation) and[/]")
    console.print("  [dim]single-turn test queries (for regression testing) based on your metrics.[/]")
    console.print()
    if existing_scenarios or existing_golden:
        console.print("  [dim]You have existing test data. Gemini will extend it — guide what new[/]")
        console.print("  [dim]scenarios should focus on, or press Enter to let Gemini decide.[/]")
    else:
        console.print("  [dim]Guide what test data should focus on — e.g., edge cases for billing,[/]")
        console.print("  [dim]multi-step workflows, error handling, out-of-scope requests.[/]")
        console.print("  [dim]Press Enter to skip — Gemini will generate based on agent code and metrics.[/]")
    console.print()
    test_data_priorities = Prompt.ask("  What should test data focus on?", default="")

    _continue("Next: generate test scenarios and sample queries →", console=console)

    # ── Gemini Call 3 — Generate test data ────────────────────────────────
    recommendations: Dict[str, Any] = {}
    with console.status(
        "[bold blue]  Generating test data...[/]", spinner="dots"
    ):
        try:
            from agent_eval.core.metric_generator import generate_eval_data
            recommendations = generate_eval_data(
                agent_dir=agent_dir,
                agent_name=agent_name,
                agent_analysis=agent_analysis,
                metric_definitions=custom_metrics,
                existing_scenarios=existing_scenarios,
                existing_golden=existing_golden,
                user_priorities=test_data_priorities,
            )
        except Exception as e:
            console.print(f"  [yellow]Test data generation failed:[/] {e}")
            console.print("  [dim]You can add scenarios and golden data manually later.[/]")

    # ── Confirm/Refine test data ──────────────────────────────────────────
    if recommendations:
        _display_recommendations(recommendations)
        _continue("Next: accept, refine, or skip the generated test data →", console=console)

        while True:
            console.print()
            console.print("    [bold]1.[/] [green]Accept[/] — create eval files with these metrics and test data")
            console.print("    [bold]2.[/] [cyan]Refine[/] — provide feedback and regenerate test data")
            console.print("    [bold]3.[/] [yellow]Skip[/]   — keep metrics, use starter test data instead")
            console.print()
            action = IntPrompt.ask("  Select", default=1)
            while action not in (1, 2, 3):
                console.print("  [red]Please enter 1, 2, or 3[/]")
                action = IntPrompt.ask("  Select", default=1)

            if action == 1:
                break

            if action == 3:
                recommendations = None
                break

            # action == 2: Refine test data
            console.print()
            console.print("  [bold]What should change?[/]")
            console.print("  [dim]Tell Gemini what to adjust — e.g., \"add more edge cases\",[/]")
            console.print("  [dim]\"the golden queries are too simple\", \"test error handling more\"[/]")
            console.print()
            feedback = Prompt.ask("  Feedback")
            if not feedback.strip():
                continue

            if test_data_priorities:
                test_data_priorities += f"\n\nADDITIONAL FEEDBACK: {feedback}"
            else:
                test_data_priorities = f"FEEDBACK on previous generation: {feedback}"

            console.print()
            with console.status(
                "[bold blue]Regenerating test data...[/]", spinner="dots"
            ):
                try:
                    recommendations = generate_eval_data(
                        agent_dir=agent_dir,
                        agent_name=agent_name,
                        agent_analysis=agent_analysis,
                        metric_definitions=custom_metrics,
                        existing_scenarios=existing_scenarios,
                        existing_golden=existing_golden,
                        user_priorities=test_data_priorities,
                    )
                except Exception as e:
                    console.print(f"\n  [yellow]Regeneration failed:[/] {e}")
                    console.print("  [dim]Showing previous results.[/]")
                    continue

            console.print()
            _display_recommendations(recommendations)

    # ── Return ────────────────────────────────────────────────────────────
    starter_keys = list(selected_managed.keys())
    return starter_keys, custom_metrics, recommendations, agent_analysis


def _load_existing_metrics(agent_dir: Path) -> Optional[Dict[str, Any]]:
    """Load existing metric definitions if present."""
    eval_dir = agent_dir / "eval"
    if not eval_dir.exists():
        return None

    from agent_eval.core.config import find_eval_files
    discovered = find_eval_files(eval_dir)
    for metrics_file in discovered["metrics"]:
        try:
            data = json.loads(metrics_file.read_text())
            return data.get("metrics", {})
        except Exception:
            pass
    return None


def _load_existing_eval_data(
    agent_dir: Path,
) -> tuple[Optional[list], Optional[list]]:
    """Load existing scenarios and golden data if present."""
    eval_dir = agent_dir / "eval"
    if not eval_dir.exists():
        return None, None

    from agent_eval.core.config import find_eval_files
    discovered = find_eval_files(eval_dir)

    scenarios = None
    all_scenarios: list = []
    for f in discovered["scenarios"]:
        try:
            content = json.loads(f.read_text())
            all_scenarios.extend(content.get("scenarios", []))
        except Exception:
            pass
    if all_scenarios:
        scenarios = all_scenarios

    golden = None
    all_questions: list = []
    for f in discovered["golden_data"]:
        try:
            content = json.loads(f.read_text())
            all_questions.extend(
                content.get("golden_questions", content.get("questions", []))
            )
        except Exception:
            pass
    if all_questions:
        golden = all_questions

    return scenarios, golden


def _display_generated_metrics(metrics: dict, rationale: str) -> None:
    """Display AI-generated metrics in a Rich table with managed/custom separation."""
    console.print("  [bold]Evaluation Metrics[/]")
    console.print()
    table = Table(
        border_style="cyan",
        padding=(0, 2),
    )
    table.add_column("Metric", style="bold cyan")
    table.add_column("Type", style="dim", width=10)
    table.add_column("Description")
    table.add_column("Runs On", style="dim", justify="center")

    def _runs_on(defn: dict) -> str:
        if defn.get("requires_multi_turn") or defn.get("applies_to") == "scenarios":
            return "multi-turn rows"
        if defn.get("requires_reference") or defn.get("applies_to") == "golden_dataset":
            return "reference rows"
        return "any row"

    # Sort: managed metrics first, then custom
    sorted_metrics = sorted(metrics.items(), key=lambda x: (0 if x[1].get("is_managed") else 1, x[0]))

    shown_custom_separator = False
    for name, defn in sorted_metrics:
        is_managed = defn.get("is_managed", False)

        # Add separator before first custom metric
        if not is_managed and not shown_custom_separator:
            table.add_row(
                "[dim]── Custom Metrics (AI-generated) ──[/]",
                "", "", "",
            )
            shown_custom_separator = True

        metric_type = "managed" if is_managed else "custom"
        desc = defn.get("description", "") if is_managed else defn.get("score_range", {}).get("description", "")
        table.add_row(name, metric_type, desc[:60], _runs_on(defn))

    console.print(table)

    console.print()
    console.print("  [dim]Runs On:  any row       = no row capability required[/]")
    console.print("  [dim]         multi-turn rows = needs conversation_history (simulate output)[/]")
    console.print("  [dim]         reference rows  = needs reference_data (golden questions)[/]")
    console.print()
    console.print("  [dim]Managed = Google's built-in rubrics (you selected these)[/]")
    console.print("  [dim]Custom  = AI-generated rubrics tailored to your agent[/]")

    if rationale and not rationale.startswith("\n"):
        console.print()
        console.print("  [bold]Rationale[/]")
        for line in rationale.strip().splitlines():
            console.print(f"  [dim]{line}[/]")


def _display_recommendations(recommendations: dict) -> None:
    """Display Gemini's evaluation recommendations."""

    # ── Strategy & file feedback ──────────────────────────────────────────
    strategy_parts = []
    strategy = recommendations.get("strategy", "")
    if strategy:
        strategy_parts.append(f"[bold]Strategy:[/] {strategy}")

    feedback = recommendations.get("existing_file_feedback", "")
    if feedback and feedback != "No existing files provided.":
        strategy_parts.append(f"\n[bold]Existing files:[/] {feedback}")

    if strategy_parts:
        console.print()
        console.print("  [bold]Recommendations[/]")
        for part in strategy_parts:
            for line in part.strip().splitlines():
                console.print(f"  {line}")

    # ── Scenario table (multi-turn) ──────────────────────────────────────
    scenarios = recommendations.get("scenarios", [])
    if scenarios:
        console.print()
        console.print(
            "  [bold]Suggested Scenarios[/] [dim]— multi-turn conversations for ADK User Sim.[/]"
        )
        console.print(
            "  [dim]The simulator follows these plans without reference data —[/]"
            "\n  [dim]it evaluates how the agent handles the full conversation.[/]"
        )
        scenario_table = Table(border_style="cyan", padding=(0, 2), expand=True)
        scenario_table.add_column("#", style="dim", width=3)
        scenario_table.add_column("Starting Prompt", style="cyan", ratio=2)
        scenario_table.add_column("Description", ratio=3)
        for i, s in enumerate(scenarios[:5], 1):
            prompt = s.get("starting_prompt", "")
            desc = s.get("description", s.get("conversation_plan", ""))
            scenario_table.add_row(str(i), prompt, desc)
        console.print(scenario_table)

    # ── Golden queries table (single-turn) ────────────────────────────────
    golden = recommendations.get("golden_data", [])
    if golden:
        console.print()
        console.print(
            "  [bold]Suggested Test Queries[/] [dim]— single-turn queries with reference data.[/]"
        )
        console.print(
            "  [dim]Each query includes expected behavior so the evaluator can[/]"
            "\n  [dim]check if the agent's response matches what it should do.[/]"
        )
        golden_table = Table(border_style="cyan", padding=(0, 2), expand=True)
        golden_table.add_column("#", style="dim", width=3)
        golden_table.add_column("Query", style="cyan", ratio=2)
        golden_table.add_column("Expected Behavior", ratio=3)
        for i, g in enumerate(golden[:5], 1):
            inputs = g.get("user_inputs", [])
            query = inputs[0] if inputs else g.get("description", "")
            ref_data = g.get("reference_data", {})
            expected = ref_data.get("expected_behavior", "") if isinstance(ref_data, dict) else ""
            if not expected:
                expected = g.get("expected_behavior", g.get("description", ""))
            golden_table.add_row(str(i), query, expected)
        console.print(golden_table)


def _draw_metrics(selected: list[str]) -> None:
    for i, (key, label, desc, _) in enumerate(STARTER_METRICS, 1):
        marker = "[green]x[/]" if key in selected else " "
        console.print(f"    [{marker}] [bold]{i}.[/] {label:24s} [dim]{desc}[/]")


# ── Summary & Next Steps ───────────────────────────────────────────────────


def _display_summary(
    agent_dir: Path, agent_name: str, mode: str,
    metrics: list[str], custom_metrics: dict | None = None,
    chosen_paths: set[str] | None = None,
) -> None:
    """Show what files will be created/kept, with descriptions of each file's purpose."""
    eval_dir = agent_dir / "eval"
    unified_dir = agent_dir / "tests" / "eval"
    is_existing = eval_dir.exists() or unified_dir.exists()
    chosen_paths = chosen_paths or {"A", "B"}

    # Determine what will happen to each file
    existing_metrics = (eval_dir / "metrics" / "metric_definitions.json").exists()
    existing_scenarios = (eval_dir / "scenarios" / "conversation_scenarios.json").exists()
    existing_golden = (eval_dir / "eval_data" / "golden_dataset.json").exists()
    existing_session = (eval_dir / "scenarios" / "session_input.json").exists()
    existing_dataset = (unified_dir / "dataset.jsonl").exists()
    existing_unified_metrics = (unified_dir / "metrics" / "metric_definitions.json").exists()
    has_ai = custom_metrics is not None

    if "B" in chosen_paths:
        console.print(f"  Creating local pipeline files in [cyan]{eval_dir}/[/]")
    if "A" in chosen_paths:
        console.print(f"  Creating Agent Engine pass files in [cyan]{unified_dir}/[/]")
    if is_existing and has_ai:
        console.print("  [dim]Existing files will be backed up to .backup/ before updating.[/]")
    elif is_existing:
        console.print("  [dim]Existing files will not be overwritten.[/]")
    console.print()

    # Build file table with descriptions
    table = Table(show_header=True, border_style="blue", padding=(0, 2), expand=True)
    table.add_column("Status", width=10)
    table.add_column("File", style="cyan", ratio=2)
    table.add_column("Purpose", ratio=3)

    # ── Agent Engine pass: unified SDK-aligned layout ────────────────────
    if "A" in chosen_paths:
        if existing_dataset:
            table.add_row("[yellow]kept[/]", "[dim]tests/eval/dataset.jsonl[/]", "[dim]Existing unified dataset for Agent Engine (unchanged)[/]")
        else:
            table.add_row("[green]new[/]", "tests/eval/dataset.jsonl", "Unified prompt/session_inputs rows for `agent-eval agent-engine`")

        if "B" not in chosen_paths:
            # Path-A-only flow scaffolds metrics into tests/eval too
            if existing_unified_metrics:
                table.add_row("[yellow]kept[/]", "[dim]tests/eval/metrics/metric_definitions.json[/]", "[dim]Existing scoring rubrics (unchanged)[/]")
            else:
                label = "[green]new[/]" if not has_ai else "[green]new[/]"
                table.add_row(label, "tests/eval/metrics/metric_definitions.json", "LLM-as-judge scoring rubrics")

    # ── Local pipeline: ADK-runtime layout (used by simulate/UserSim) ────
    if "B" in chosen_paths:
        if has_ai:
            if existing_metrics:
                table.add_row("[green]updated[/]", "eval/metrics/metric_definitions.json", "AI-generated scoring rubrics (previous version backed up)")
            else:
                table.add_row("[green]new[/]", "eval/metrics/metric_definitions.json", "AI-generated scoring rubrics for evaluating agent responses")
        elif existing_metrics:
            table.add_row("[yellow]kept[/]", "[dim]eval/metrics/metric_definitions.json[/]", "[dim]Your current scoring rubrics (unchanged)[/]")
        else:
            table.add_row("[green]new[/]", "eval/metrics/metric_definitions.json", "LLM-as-judge scoring rubrics for evaluating agent responses")

        if mode in ("user-sim", "both"):
            if has_ai:
                if existing_scenarios:
                    table.add_row("[green]updated[/]", "eval/scenarios/conversation_scenarios.json", "AI scenarios merged with existing (previous version backed up)")
                else:
                    table.add_row("[green]new[/]", "eval/scenarios/conversation_scenarios.json", "AI-generated multi-turn conversation scripts for ADK User Sim")
            elif existing_scenarios:
                table.add_row("[yellow]kept[/]", "[dim]eval/scenarios/conversation_scenarios.json[/]", "[dim]Your current multi-turn scenario scripts (unchanged)[/]")
            else:
                table.add_row("[green]new[/]", "eval/scenarios/conversation_scenarios.json", "Multi-turn conversation scripts for ADK User Sim")

        if mode in ("diy", "both"):
            if has_ai:
                if existing_golden:
                    table.add_row("[green]updated[/]", "eval/eval_data/golden_dataset.json", "AI queries merged with existing (previous version backed up)")
                else:
                    table.add_row("[green]new[/]", "eval/eval_data/golden_dataset.json", "AI-generated test queries with expected behaviors")
            elif existing_golden:
                table.add_row("[yellow]kept[/]", "[dim]eval/eval_data/golden_dataset.json[/]", "[dim]Your current test queries (unchanged)[/]")
            else:
                table.add_row("[green]new[/]", "eval/eval_data/golden_dataset.json", "Single-turn test queries with expected behaviors")

        if not existing_session:
            table.add_row("[green]new[/]", "eval/scenarios/session_input.json", "Agent name + user ID for trace collection")

    console.print(table)


def _display_next_steps(
    agent_name: str, agent_dir: Path, mode: str,
    custom_metrics: dict | None = None,
    chosen_paths: set[str] | None = None,
) -> None:
    eval_path = agent_dir / "eval"
    unified_path = agent_dir / "tests" / "eval"
    has_ai = custom_metrics is not None
    chosen_paths = chosen_paths or {"A", "B"}

    lines = []
    step = 1

    # Review files — point at whichever metrics file actually exists
    metrics_path = (
        eval_path / "metrics" / "metric_definitions.json"
        if "B" in chosen_paths
        else unified_path / "metrics" / "metric_definitions.json"
    )
    lines.append(f"[bold]{step}.[/] Review your metric definitions:")
    lines.append(f"   [cyan]{metrics_path}[/]")
    step += 1
    if "A" in chosen_paths:
        lines.append(f"[bold]{step}.[/] Review your Agent Engine dataset:")
        lines.append(f"   [cyan]{unified_path}/dataset.jsonl[/]")
        step += 1
    if "B" in chosen_paths and mode in ("user-sim", "both"):
        lines.append(f"[bold]{step}.[/] Review your scenarios:")
        lines.append(f"   [cyan]{eval_path}/scenarios/conversation_scenarios.json[/]")
        step += 1
    if "B" in chosen_paths and mode in ("diy", "both"):
        lines.append(f"[bold]{step}.[/] Review your golden dataset:")
        lines.append(f"   [cyan]{eval_path}/eval_data/golden_dataset.json[/]")
        step += 1

    lines.append("")
    if chosen_paths == {"A"}:
        # No local source — only the streamlined pass is available.
        lines.append(f"[bold]{step}.[/] Run the streamlined Agent Engine pass:")
        lines.append(f"   [dim]$[/] agent-eval agent-engine")
        lines.append("")
        lines.append("   [dim]Vertex calls your deployed agent, scores responses against your metrics,[/]")
        lines.append("   [dim]and uploads results to GCS — one managed call.[/]")
        lines.append("")
        lines.append("   [dim]To also enable the local pipeline (multi-turn UserSim + full traces), put[/]")
        lines.append("   [dim]your agent.py somewhere we can find it and re-run[/] [cyan]agent-eval init[/][dim].[/]")
    elif chosen_paths == {"B"}:
        # The default, common case — iterating locally before deploying.
        lines.append(f"[bold]{step}.[/] Run the local pipeline:")
        lines.append(f"   [dim]$[/] agent-eval run --agent-dir {agent_dir}")
        lines.append("")
        lines.append("   [dim]Four phases in sequence — collect traces (UserSim + DIY) → evaluate → analyze.[/]")
        lines.append("   [dim]This is the iteration loop. Tweak your agent, re-run, compare.[/]")
        lines.append("")
        lines.append("   [dim]Once you deploy to Agent Engine ([/][cyan]make backend[/][dim]), re-run[/] "
                     "[cyan]agent-eval init[/] [dim]and we'll[/]")
        lines.append("   [dim]wire up the streamlined single-turn pass too.[/]")
    else:
        # Both surfaces detected — lead with the local iteration loop.
        lines.append(f"[bold]{step}.[/] Run the local pipeline (the iteration loop):")
        lines.append(f"   [dim]$[/] agent-eval run --agent-dir {agent_dir}")
        lines.append("")
        lines.append("   [dim]Four phases — collect traces (UserSim + DIY) → evaluate → analyze.[/]")
        lines.append("   [dim]Use this for every change you make.[/]")
        lines.append("")
        lines.append(f"[bold]{step + 1}.[/] Run the streamlined Agent Engine pass (confirm against the deployed agent):")
        lines.append(f"   [dim]$[/] agent-eval agent-engine")
        lines.append("")
        lines.append("   [dim]Single-turn managed scoring against the live deployment — slower iteration but[/]")
        lines.append("   [dim]the truth check. Compare both with[/] [cyan]agent-eval dashboard[/][dim].[/]")

    if has_ai and (eval_path / ".backup").exists():
        lines.append("")
        lines.append("[dim]Your previous eval files are backed up in eval/.backup/[/]")
        lines.append("[dim]Delete the backup when you're satisfied with the new files.[/]")

    if "B" in chosen_paths:
        lines.append("")
        lines.append("[dim]Note: The interact phase sends queries to a running agent.[/]")
        lines.append("[dim]Make sure your agent is serving (e.g. [bold]adk web[/bold]) before running.[/]")
        lines.append("[dim]If the agent isn't reachable, interact is skipped gracefully.[/]")
    lines.append("")
    lines.append("[dim]Or run individual steps — see: agent-eval --help[/]")

    console.print(Panel("\n".join(lines), title="[bold]Next Steps[/]", border_style="green", padding=(1, 2)))


def _metric_uses_reference_data(defn: dict) -> bool:
    """Whether a custom metric's mapping references reference_data.* columns."""
    return bool(_metric_reference_fields(defn))


def _metric_reference_fields(defn: dict) -> set[str]:
    """Field names from `reference_data.<field>` referenced by this metric.

    Returns an empty set if the metric doesn't pull from reference_data at all.
    Returns {"*"} if it pulls reference_data without naming a specific field.
    """
    fields: set[str] = set()
    mapping = defn.get("dataset_mapping", {})
    for config in mapping.values():
        if not isinstance(config, dict):
            continue
        cols = [config.get("source_column", "")] + config.get("source_columns", [])
        for col in cols:
            if not col or "reference_data" not in col:
                continue
            # Patterns: "reference_data:expected_response", "reference_data.expected_docs"
            for sep in (":", "."):
                if sep in col:
                    tail = col.split(sep, 1)[1]
                    if tail and tail != "reference_data":
                        fields.add(tail)
                        break
            else:
                fields.add("*")
    return fields


def _populated_reference_fields(recommendations: dict | None) -> set[str]:
    """Reference field names actually populated in generated golden data."""
    if not recommendations:
        return set()
    populated: set[str] = set()
    for entry in recommendations.get("golden_data", []) or []:
        if not isinstance(entry, dict):
            continue
        rd = entry.get("reference_data", {})
        if not isinstance(rd, dict):
            continue
        for field, val in rd.items():
            if val and str(val).strip():
                populated.add(field)
    return populated


def _display_connection_map(
    custom_metrics: dict | None,
    recommendations: dict | None,
    agent_analysis: dict | None = None,
) -> None:
    """Show how metrics, data sources, and test data connect."""
    if not custom_metrics:
        return

    console.print()
    console.print("  [bold]How everything connects[/]")
    console.print("  [dim]Each metric evaluates specific aspects of your agent using available data.[/]")
    console.print()

    table = Table(border_style="cyan", padding=(0, 2), expand=True)
    table.add_column("Metric", style="bold cyan", ratio=2)
    table.add_column("Data Sources", ratio=3)
    table.add_column("Runs On", style="dim", width=12)

    for name, defn in custom_metrics.items():
        if not isinstance(defn, dict):
            continue

        sources: list[str] = []
        if defn.get("is_managed"):
            sources.append("request/response (auto)")
        else:
            mapping = defn.get("dataset_mapping", {})
            for config in mapping.values():
                if isinstance(config, dict):
                    if "source_column" in config:
                        sources.append(config["source_column"])
                    elif "source_columns" in config:
                        sources.extend(config["source_columns"])

        source_str = ", ".join(sources) if sources else "default"

        if defn.get("requires_multi_turn") or defn.get("applies_to") == "scenarios":
            runs_on = "multi-turn"
        elif defn.get("requires_reference") or defn.get("applies_to") == "golden_dataset":
            runs_on = "reference"
        else:
            runs_on = "any"

        table.add_row(name, source_str, runs_on)

    console.print(table)

    if agent_analysis:
        state_vars = agent_analysis.get("state_variables", {})
        if state_vars:
            referenced: set[str] = set()
            for defn in custom_metrics.values():
                if not isinstance(defn, dict):
                    continue
                mapping = defn.get("dataset_mapping", {})
                for config in mapping.values():
                    if isinstance(config, dict):
                        for col in [config.get("source_column", "")] + config.get("source_columns", []):
                            if "state_variables" in col or col.startswith("extracted_data:"):
                                key = col.split(":")[-1].split(".")[-1]
                                if key in state_vars:
                                    referenced.add(key)

            unreferenced = set(state_vars.keys()) - referenced
            if referenced or unreferenced:
                console.print()
                console.print("  [bold]Agent state coverage[/]")
            if referenced:
                console.print(f"  [green]>[/] State variables used by metrics: [cyan]{', '.join(sorted(referenced))}[/]")
            if unreferenced:
                console.print(f"  [dim]>[/] Available but not in metrics: [dim]{', '.join(sorted(unreferenced))}[/]")

    if recommendations:
        scenarios = recommendations.get("scenarios", [])
        golden = recommendations.get("golden_data", [])
        if scenarios or golden:
            console.print()
            console.print("  [bold]Test data coverage[/]")
            if scenarios:
                console.print(f"  [green]>[/] {len(scenarios)} scenarios will exercise your metrics via multi-turn simulation")
            if golden:
                console.print(f"  [green]>[/] {len(golden)} golden queries will test against expected behaviors")

    ref_metric_fields: dict[str, set[str]] = {}
    for name, defn in custom_metrics.items():
        if not isinstance(defn, dict):
            continue
        used = _metric_reference_fields(defn)
        if defn.get("requires_reference"):
            field = defn.get("reference_field")
            if field:
                used.add(field)
            elif not used:
                used.add("*")
        if used:
            ref_metric_fields[name] = used

    if ref_metric_fields:
        all_required = {f for fields in ref_metric_fields.values() for f in fields if f != "*"}
        populated = _populated_reference_fields(recommendations)
        missing = all_required - populated

        console.print()
        console.print("  [bold]Reference-data metrics[/]")
        for name, fields in sorted(ref_metric_fields.items()):
            field_str = ", ".join(sorted(fields)) if fields != {"*"} else "any populated field (auto-resolved)"
            console.print(f"    [cyan]{name}[/] -> reads [bold]reference_data.{field_str}[/]")

        if populated:
            console.print(f"    [green]+[/] Generated golden data populates: [green]{', '.join(sorted(populated))}[/]")
        if missing:
            console.print(f"    [yellow]![/] Missing in golden data: [yellow]{', '.join(sorted(missing))}[/]")
            console.print("    [dim]  Edit `eval/eval_data/golden_dataset.json` to add these fields, or the metric will be skipped.[/]")
        console.print("    [dim]Gemini's drafts are starting points — sharpen them with the actual answers your agent should produce.[/]")


# ── Command ─────────────────────────────────────────────────────────────────


@click.command()
@click.option("--target-dir", default=None, help="Directory containing agent.py (eval/ will be created here).")
@click.option("--agent-name", default=None, help="Agent module name (auto-detected from target-dir if omitted).")
@click.option("--mode", type=click.Choice(["user-sim", "diy", "both"]), default=None,
              help="Interaction mode.")
@click.option("--auto-approve", "-y", is_flag=True, help="Skip interactive prompts, use defaults.")
@click.option("--ai-metrics", is_flag=True, help="Generate tailored metrics with AI (Gemini analyzes your agent code).")
def init(target_dir, agent_name, mode, auto_approve, ai_metrics):
    """Scaffold the eval/ folder structure for an ADK agent.

    Searches for agent.py files in the current directory tree and lets you
    select which agent to add evaluation to. The eval/ folder is created
    inside the agent module directory, as a sibling to agent.py.
    """
    from agent_eval.cli.main import _display_banner
    _display_banner()

    if not auto_approve:
        _display_intro()

    # ── Step 0: Environment verification ──
    _verify_environment(auto_approve=auto_approve)

    custom_metrics = None
    recommendations = None
    agent_analysis = None
    chosen_paths: set[str] = set()  # derived from detection below (interactive + auto)

    if auto_approve:
        if target_dir:
            agent_dir = Path(target_dir)
            agent_name = agent_name or agent_dir.name
        else:
            agents = _find_agents(Path("."))
            if agents:
                agent_name_found, agent_dir = agents[0]
                agent_name = agent_name or agent_name_found
                console.print(f"  Auto-selected agent: [cyan]{agent_name}/[/] [dim]({agent_dir})[/]")
            else:
                agent_name = agent_name or "app"
                agent_dir = Path(agent_name)

        mode = mode or "both"

        # Silent path detection so -y derives the same way as the interactive
        # flow — if the user has only local source we don't pointlessly
        # scaffold Agent Engine bits, and vice versa.
        from agent_eval.core.path_detector import detect_execution_path
        detect_root = agent_dir if agent_dir.exists() else Path(".")
        chosen_paths = _derive_chosen_paths(detect_execution_path(detect_root))
        if not chosen_paths:
            # No agent.py and no deployment found — default to local-only
            # (the typical "I'm starting fresh, going to wire up agent.py
            # next" case). Scaffolds tests/eval/dataset.jsonl + eval/ stubs.
            chosen_paths = {"B"}

        if ai_metrics:
            console.print()
            with console.status("[bold blue]Generating tailored metrics with Gemini...[/]", spinner="dots"):
                try:
                    from agent_eval.core.metric_discovery import discover_managed_metrics, get_metric_definition_entry
                    from agent_eval.core.metric_generator import analyze_agent_data, generate_metric_definitions, generate_eval_data

                    # Per Vertex AI docs: start with GENERAL_QUALITY as the default.
                    managed = discover_managed_metrics()
                    selected_managed = {}
                    for key in ("general_quality",):
                        entry = get_metric_definition_entry(key, managed)
                        if entry:
                            selected_managed[key] = entry

                    # Preserve any existing metrics/test data on re-runs
                    existing_metrics_auto = _load_existing_metrics(agent_dir)
                    existing_scenarios_auto, existing_golden_auto = _load_existing_eval_data(agent_dir)

                    # Run the 3-step pipeline
                    agent_analysis = analyze_agent_data(agent_dir, agent_name)
                    custom_metrics, rationale = generate_metric_definitions(
                        agent_dir=agent_dir,
                        agent_name=agent_name,
                        agent_analysis=agent_analysis,
                        selected_managed=selected_managed,
                        existing_metrics=existing_metrics_auto,
                    )
                    eval_data = generate_eval_data(
                        agent_dir=agent_dir,
                        agent_name=agent_name,
                        agent_analysis=agent_analysis,
                        metric_definitions=custom_metrics,
                        existing_scenarios=existing_scenarios_auto,
                        existing_golden=existing_golden_auto,
                    )
                    recommendations = eval_data
                    metrics = list(selected_managed.keys())
                    console.print(f"  [green]Generated {len(custom_metrics)} metrics[/]")
                except Exception as e:
                    console.print(f"  [yellow]AI generation failed:[/] {e}")
                    console.print("  [dim]Using default starter metrics.[/]")
                    metrics = [key for key, _, _, default in STARTER_METRICS if default]
        else:
            metrics = [key for key, _, _, default in STARTER_METRICS if default]
    else:
        search_dir = Path(target_dir) if target_dir else Path(".")

        # Step 2 — Pick the agent FIRST so detection can be scoped to its
        # subtree. Otherwise, in a multi-agent project, detection would
        # latch onto whichever agent happens to have a deployment_metadata.json
        # file — even if the user wants to work on a different one.
        agents = _find_agents(search_dir)
        if agents:
            agent_name_found, agent_dir = _prompt_agent_selection(agents, search_dir)
            agent_name = agent_name or agent_name_found
        else:
            agent_name, agent_dir = _prompt_agent_name_manual()

        # Step 2.5 — Detect a legacy eval/ layout and offer to migrate.
        # Scaffolds since the SDK-aligned refactor write to tests/eval/, but
        # earlier projects have eval/scenarios + eval/eval_data. Surface a
        # one-key migrate prompt before we add more files alongside the old
        # layout.
        _maybe_offer_legacy_migration(agent_dir)

        # Step 3 — Detect the execution path for THIS agent.
        # Scope rule:
        # - Multiple agents in search_dir → scope to agent_dir (avoid
        #   picking up a sibling agent's deployment_metadata.json).
        # - Single agent (typical ASP layout) → scope to search_dir so
        #   project-root metadata that lives one level above the agent
        #   module folder is still found.
        detect_root = agent_dir if len(agents) > 1 else search_dir
        detection = _display_path_detection(detect_root)
        chosen_paths = _prompt_path_choice(detection)

        mode = mode or _prompt_interaction_mode(chosen_paths)
        metrics, custom_metrics, recommendations, agent_analysis = _prompt_metrics_choice(agent_dir, agent_name)

    # No-detect fallback: default to the local pipeline. It's the typical
    # starting point — you don't need a deployment to start iterating, and
    # scaffolding the streamlined Agent Engine pass when no deployment exists
    # would just write stubs the user never runs.
    if not chosen_paths:
        chosen_paths = {"B"}

    console.print()
    _display_summary(agent_dir, agent_name, mode, metrics, custom_metrics, chosen_paths)

    if not auto_approve:
        _continue("Next: write the eval files →", console=console)

    console.print()
    if "B" in chosen_paths or not chosen_paths:
        scaffold_eval_structure(
            target_dir=agent_dir,
            agent_name=agent_name,
            mode=mode if mode != "dataset-only" else "both",
            metrics=metrics,
            custom_metric_definitions=custom_metrics,
            ai_recommendations=recommendations,
        )

    if "A" in chosen_paths or not chosen_paths:
        # The agent-engine command reads from tests/eval/metrics/ first;
        # write it whenever the Agent Engine pass is selected so it doesn't
        # fall back to the legacy eval/metrics/ layout.
        from agent_eval.core.scaffold import scaffold_dataset_jsonl, scaffold_metrics_only
        scaffold_metrics_only(
            target_dir=agent_dir,
            agent_name=agent_name,
            metrics=metrics,
            custom_metric_definitions=custom_metrics,
        )
        scaffold_dataset_jsonl(
            target_dir=agent_dir,
            agent_name=agent_name,
            recommendations=recommendations,
        )

    if custom_metrics:
        if not auto_approve:
            _continue("Next: see how everything connects →", console=console)
        _display_connection_map(custom_metrics, recommendations, agent_analysis)

    if not auto_approve:
        _continue("Next: how to run your first evaluation →", console=console)
    console.print()
    _display_next_steps(agent_name, agent_dir, mode, custom_metrics, chosen_paths)
