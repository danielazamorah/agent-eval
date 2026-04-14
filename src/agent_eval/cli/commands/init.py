"""agent-eval init — scaffold the eval/ folder structure for a new agent project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

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


# ── Step 1: Agent Selection ─────────────────────────────────────────────────


def _prompt_agent_selection(agents: list[tuple[str, Path]], search_dir: Path) -> tuple[str, Path]:
    """Let the user select which discovered agent to scaffold for."""
    console.print(Panel(
        "[bold]Step 1 of 3[/] — Select your agent\n\n"
        "The [cyan]agent module[/] is the folder containing your [cyan]agent.py[/], tools,\n"
        "prompts, and sub-agents. For agents created with Agent Starter Pack,\n"
        "this is typically [cyan]app/[/]. The [cyan]eval/[/] folder will be created inside it.",
        border_style="blue",
        padding=(1, 2),
    ))

    console.print()
    for i, (name, module_dir) in enumerate(agents, 1):
        rel_path = module_dir.relative_to(search_dir)
        console.print(f"    [bold]{i}.[/] [cyan]{name}/[/]  [dim]→ {rel_path}/agent.py[/]")

    if len(agents) > 1:
        console.print(
            f"\n  [dim]Sub-agents (inside sub_agents/) are excluded —[/]"
            "\n  [dim]evaluate them through their parent agent.[/]"
        )

    console.print()
    if len(agents) == 1:
        choice = IntPrompt.ask("  Select agent", default=1)
    else:
        choice = IntPrompt.ask(f"  Select agent [dim](1-{len(agents)})[/]")

    while choice < 1 or choice > len(agents):
        console.print(f"  [red]Please enter a number between 1 and {len(agents)}[/]")
        choice = IntPrompt.ask("  Select agent")

    return agents[choice - 1]


def _prompt_agent_name_manual() -> tuple[str, Path]:
    """Prompt for agent module path when no agents are discovered."""
    console.print(Panel(
        "[bold]Step 1 of 3[/] — Select your agent\n\n"
        "[yellow]No ADK agents found[/] in the current directory tree.\n"
        "An ADK agent is identified by a folder containing an [cyan]agent.py[/] file.\n\n"
        "You can still scaffold the [cyan]eval/[/] folder manually — just tell us\n"
        "where your agent module is (or will be). For agents created with\n"
        "Agent Starter Pack, this is typically [cyan]app/[/].",
        border_style="yellow",
        padding=(1, 2),
    ))

    console.print()
    target_input = Prompt.ask(
        "  Agent module path [dim](folder with agent.py)[/]",
        default="app",
    )
    target = Path(target_input)
    return target.name, target


# ── Step 2: Interaction Mode ────────────────────────────────────────────────


def _prompt_interaction_mode() -> str:
    console.print(Panel(
        "[bold]Step 2 of 3[/] — Choose interaction mode\n\n"
        "How will you generate traces for evaluation? This determines which\n"
        "starter files are created. You can always add or remove files later.",
        border_style="blue",
        padding=(1, 2),
    ))

    console.print()
    for i, (_, label, desc) in enumerate(INTERACTION_MODES, 1):
        console.print(f"    [bold]{i}.[/] [cyan]{label}[/]")
        console.print(f"       [dim]{desc}[/]")
        if i < len(INTERACTION_MODES):
            console.print()

    console.print(
        "\n  [dim]Both is recommended — even if you only use one method now,[/]"
        "\n  [dim]having both file types ready makes switching easy later.[/]"
    )

    choice = IntPrompt.ask("\n  Select", default=1)
    while choice < 1 or choice > len(INTERACTION_MODES):
        console.print(f"  [red]Please enter a number between 1 and {len(INTERACTION_MODES)}[/]")
        choice = IntPrompt.ask("  Select", default=1)

    return INTERACTION_MODES[choice - 1][0]


# ── Step 3: Metrics ─────────────────────────────────────────────────────────


def _prompt_metrics_choice(agent_dir: Path, agent_name: str) -> tuple[list[str], dict | None, dict | None]:
    """Let user choose between starter metrics or AI-generated metrics.

    Returns (starter_metric_keys, custom_metric_definitions_or_None, recommendations_or_None).
    """
    console.print(Panel(
        "[bold]Step 3 of 3[/] — Select metrics\n\n"
        "These define how your agent's responses will be scored.\n"
        "[bold]Deterministic metrics[/] (latency, tokens, cost) are always included.\n"
        "Below are the [bold]LLM-as-judge metrics[/] — choose how to set them up.",
        border_style="blue",
        padding=(1, 2),
    ))

    console.print()
    console.print("    [bold]1.[/] [cyan]Generate with AI[/]  [dim](recommended)[/]")
    console.print("       [dim]Gemini analyzes your agent code and creates tailored metrics,[/]")
    console.print("       [dim]plus recommendations for scenarios and test data.[/]")
    console.print()
    console.print("    [bold]2.[/] [cyan]Pick from starter metrics[/]  [dim](manual selection)[/]")
    console.print("       [dim]Choose from 4 general-purpose evaluation metrics.[/]")

    console.print()
    choice = IntPrompt.ask("  Select", default=1)
    while choice not in (1, 2):
        console.print("  [red]Please enter 1 or 2[/]")
        choice = IntPrompt.ask("  Select", default=1)

    if choice == 2:
        return _prompt_starter_metrics(), None, None

    # AI generation path — multi-step pipeline
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


def _prompt_managed_metrics_selection(
    managed_metrics: Dict[str, Dict],
) -> Dict[str, Dict]:
    """Display all available managed metrics and let the user select by number.

    Returns a dict of selected metric entries ready for metric_definitions.json.
    """
    # Separate by type for display
    api_metrics = {
        k: v for k, v in managed_metrics.items()
        if v.get("resolution") == "api_predefined"
    }
    gcs_metrics = {
        k: v for k, v in managed_metrics.items()
        if v.get("resolution") == "gcs_yaml"
    }

    # Build ordered list for selection
    all_ordered: list[tuple[str, Dict]] = []
    all_ordered.extend(sorted(api_metrics.items()))
    all_ordered.extend(sorted(gcs_metrics.items()))

    # Defaults: general_quality and safety
    defaults = {"general_quality", "safety"}
    selected_indices = {
        i for i, (k, _) in enumerate(all_ordered) if k in defaults
    }

    # Build table
    def _draw_managed_table() -> None:
        table = Table(
            title="Available Managed Metrics",
            border_style="cyan",
            padding=(0, 1),
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("", width=3)  # checkbox
        table.add_column("Metric", style="bold cyan", min_width=30)
        table.add_column("Score", min_width=14)
        table.add_column("Type", style="dim", min_width=12)
        table.add_column("Description", ratio=2)

        for i, (key, info) in enumerate(all_ordered):
            marker = "[green]x[/]" if i in selected_indices else " "
            sr = info.get("score_range", {})
            score_type = sr.get("type", "unknown")
            score_str = f"{sr.get('min', '?')}-{sr.get('max', '?')}"
            applies = info.get("applies_to", "all")
            resolution = "server" if info.get("resolution") == "api_predefined" else "client"
            desc = info.get("description", "")[:50]

            if applies != "all":
                desc += f" [{applies}]"

            table.add_row(
                str(i + 1), f"[{marker}]",
                info["managed_metric_name"], f"{score_str} ({score_type})",
                resolution, desc,
            )

        console.print(table)
        console.print()
        console.print("  [dim]Rubric (0-1) metrics are recommended for most use cases.[/]")
        console.print("  [dim]Multi-turn metrics require scenarios (simulation) data.[/]")
        console.print("  [dim]Server = API Predefined (auto-evaluated). Client = GCS YAML template.[/]")

    _draw_managed_table()

    console.print()
    console.print("  [dim]Enter numbers to toggle (comma-separated), or press Enter to continue.[/]")

    while True:
        raw = Prompt.ask("  Toggle", default="")
        if raw.strip() == "":
            break
        for part in raw.split(","):
            try:
                idx = int(part.strip()) - 1
                if 0 <= idx < len(all_ordered):
                    if idx in selected_indices:
                        selected_indices.discard(idx)
                    else:
                        selected_indices.add(idx)
            except ValueError:
                console.print("  [red]Enter numbers or press Enter to continue.[/]")
                continue
        console.print()
        _draw_managed_table()
        console.print()

    # Build selected metrics dict
    from agent_eval.core.metric_discovery import get_metric_definition_entry
    selected: Dict[str, Dict] = {}
    for i in sorted(selected_indices):
        key, info = all_ordered[i]
        entry = get_metric_definition_entry(key, managed_metrics)
        if entry:
            selected[key] = entry

    return selected


def _display_agent_analysis(analysis: Dict[str, Any]) -> None:
    """Display the agent analysis results in a Rich table."""
    table = Table(
        title="Data Available for Evaluation",
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


def _prompt_ai_metrics_multistep(
    agent_dir: Path, agent_name: str,
) -> tuple[list[str], dict | None, dict | None]:
    """Multi-step AI metric generation pipeline.

    Step 3a: Discover managed metrics + ADK knowledge
    Step 3b: User selects managed metrics
    Step 3c: Gemini Call 1 — Analyze agent source code
    Step 3d: Gemini Call 2 — Generate custom metric definitions
    Step 3e: Gemini Call 3 — Generate scenarios + golden data
    Step 3f: Display & confirm

    Returns (starter_keys_for_managed, custom_definitions_or_None, recommendations_or_None).
    """
    # ── Step 3a: Discover evaluation resources ─────────────────────────────
    console.print()
    with console.status(
        "[bold blue]Validating latest evaluation resources...[/]", spinner="dots"
    ):
        from agent_eval.core.metric_discovery import discover_managed_metrics
        managed_metrics = discover_managed_metrics()

    console.print(
        f"  [green]Found {len(managed_metrics)} managed metrics[/] "
        f"from the Vertex AI GenAI Evaluation SDK."
    )

    # ── Step 3b: User selects managed metrics ──────────────────────────────
    console.print()
    console.print(Panel(
        "[bold]Select Managed Metrics[/]\n\n"
        "These are Google's built-in evaluation rubrics — no custom template needed.\n"
        "Toggle metrics on/off by entering their numbers.",
        border_style="blue",
        padding=(1, 2),
    ))
    console.print()

    selected_managed = _prompt_managed_metrics_selection(managed_metrics)

    if selected_managed:
        names = ", ".join(
            info["managed_metric_name"] for info in selected_managed.values()
        )
        console.print(f"\n  [green]Selected:[/] {names}")
    else:
        console.print("\n  [dim]No managed metrics selected.[/]")

    # ── Ask for user priorities ────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold]What matters most?[/]\n\n"
        "Tell Gemini what aspects of your agent are important to evaluate.\n"
        "For example: [dim]accuracy of billing lookups, whether it refuses\n"
        "out-of-scope requests, tool call efficiency, response tone[/]\n\n"
        "[dim]Press Enter to skip — Gemini will analyze the code on its own.[/]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()
    user_priorities = Prompt.ask("  Evaluation priorities", default="")

    # ── Load existing eval files ───────────────────────────────────────────
    existing_metrics = _load_existing_metrics(agent_dir)
    existing_scenarios, existing_golden = _load_existing_eval_data(agent_dir)

    # ── Step 3c: Gemini Call 1 — Analyze agent source code ─────────────────
    console.print()
    agent_analysis: Dict[str, Any] = {}
    with console.status(
        "[bold blue]Identifying evaluation data available in your agent...[/]",
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

    # ── Step 3d: Gemini Call 2 — Generate custom metrics ───────────────────
    console.print()
    custom_metrics: Dict[str, Any] = {}
    rationale = ""
    with console.status(
        "[bold blue]Generating custom metric definitions...[/]", spinner="dots"
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
            console.print("  [dim]Falling back to starter metrics.[/]\n")
            return _prompt_starter_metrics(), None, None

    # Display generated metrics
    console.print()
    _display_generated_metrics(custom_metrics, rationale)

    # ── Step 3e: Gemini Call 3 — Generate scenarios + golden data ──────────
    console.print()
    recommendations: Dict[str, Any] = {}
    with console.status(
        "[bold blue]Generating test scenarios and golden data...[/]", spinner="dots"
    ):
        try:
            from agent_eval.core.metric_generator import generate_eval_data
            eval_data = generate_eval_data(
                agent_dir=agent_dir,
                agent_name=agent_name,
                agent_analysis=agent_analysis,
                metric_definitions=custom_metrics,
                existing_scenarios=existing_scenarios,
                existing_golden=existing_golden,
            )
            recommendations = eval_data
        except Exception as e:
            console.print(f"  [yellow]Test data generation failed:[/] {e}")
            console.print("  [dim]You can add scenarios and golden data manually later.[/]")

    if recommendations:
        _display_recommendations(recommendations)

    # ── Step 3f: Confirm ───────────────────────────────────────────────────
    while True:
        console.print()
        has_existing = (agent_dir / "eval").exists()
        if has_existing:
            console.print(
                "  [dim]Existing eval files will be backed up before updating.[/]"
            )

        console.print()
        console.print(
            "    [bold]1.[/] [green]Accept[/] — create eval files with these metrics and test data"
        )
        console.print(
            "    [bold]2.[/] [cyan]Refine[/] — provide feedback and regenerate metrics"
        )
        console.print(
            "    [bold]3.[/] [yellow]Skip[/]   — use starter metrics instead"
        )

        console.print()
        action = IntPrompt.ask("  Select", default=1)
        while action not in (1, 2, 3):
            console.print("  [red]Please enter 1, 2, or 3[/]")
            action = IntPrompt.ask("  Select", default=1)

        if action == 1:
            # Return managed metric keys + custom metrics
            starter_keys = list(selected_managed.keys())
            return starter_keys, custom_metrics, recommendations

        if action == 3:
            console.print("  [dim]Switching to starter metrics.[/]\n")
            return _prompt_starter_metrics(), None, None

        # action == 2: Refine — regenerate metrics (Call 2 only, not analysis)
        console.print()
        console.print(Panel(
            "[bold]What should change?[/]\n\n"
            "Tell Gemini what to adjust. For example:\n"
            "[dim]  - \"focus more on tool error handling\"\n"
            "  - \"the trajectory metric is too strict\"\n"
            "  - \"add a metric for response latency awareness\"[/]",
            border_style="cyan",
            padding=(1, 2),
        ))

        console.print()
        feedback = Prompt.ask("  Feedback")
        if not feedback.strip():
            continue

        combined_priorities = user_priorities
        if combined_priorities:
            combined_priorities += (
                f"\n\nADDITIONAL FEEDBACK: {feedback}"
            )
        else:
            combined_priorities = f"FEEDBACK on previous generation: {feedback}"

        console.print()
        with console.status(
            "[bold blue]Regenerating metrics with your feedback...[/]",
            spinner="dots",
        ):
            try:
                from agent_eval.core.metric_generator import generate_metric_definitions
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
        if recommendations:
            _display_recommendations(recommendations)


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
    """Display AI-generated metrics in a Rich table."""
    table = Table(
        title="Evaluation Metrics",
        border_style="cyan",
        padding=(0, 2),
    )
    table.add_column("Metric", style="bold cyan")
    table.add_column("Type", style="dim", width=10)
    table.add_column("Description")
    table.add_column("Runs On", style="dim", justify="center")

    applies_labels = {"all": "all data", "scenarios": "scenarios", "golden_dataset": "golden data"}
    for name, defn in metrics.items():
        is_managed = defn.get("is_managed", False)
        metric_type = "managed" if is_managed else "custom"
        desc = defn.get("description", "") if is_managed else defn.get("score_range", {}).get("description", "")
        applies = applies_labels.get(defn.get("applies_to", "all"), "all data")
        table.add_row(name, metric_type, desc[:60], applies)

    console.print(table)

    if rationale and not rationale.startswith("\n"):
        console.print()
        console.print(Panel(
            rationale,
            title="[bold]Rationale[/]",
            border_style="dim",
            padding=(1, 2),
        ))


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
        console.print(Panel(
            "\n".join(strategy_parts),
            title="[bold]Recommendations[/]",
            border_style="green",
            padding=(1, 2),
        ))

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
            expected = g.get("expected_behavior", "")
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
) -> None:
    """Show what files will be created/kept, with descriptions of each file's purpose."""
    eval_dir = agent_dir / "eval"
    is_existing = eval_dir.exists()

    # Determine what will happen to each file
    existing_metrics = (eval_dir / "metrics" / "metric_definitions.json").exists()
    existing_scenarios = (eval_dir / "scenarios" / "conversation_scenarios.json").exists()
    existing_golden = (eval_dir / "eval_data" / "golden_dataset.json").exists()
    existing_session = (eval_dir / "scenarios" / "session_input.json").exists()
    has_ai = custom_metrics is not None

    console.print(f"  Creating eval files in [cyan]{eval_dir}/[/]")
    if is_existing and has_ai:
        console.print("  [dim]Existing files will be backed up to eval/.backup/ before updating.[/]")
    elif is_existing:
        console.print("  [dim]Existing files will not be overwritten.[/]")
    console.print()

    # Build file table with descriptions
    table = Table(show_header=True, border_style="blue", padding=(0, 2), expand=True)
    table.add_column("Status", width=10)
    table.add_column("File", style="cyan", ratio=2)
    table.add_column("Purpose", ratio=3)

    # Metrics
    if has_ai:
        if existing_metrics:
            table.add_row("[green]updated[/]", "metrics/metric_definitions.json", "AI-generated scoring rubrics (previous version backed up)")
        else:
            table.add_row("[green]new[/]", "metrics/metric_definitions.json", "AI-generated scoring rubrics for evaluating agent responses")
    elif existing_metrics:
        table.add_row("[yellow]kept[/]", "[dim]metrics/metric_definitions.json[/]", "[dim]Your current scoring rubrics (unchanged)[/]")
    else:
        table.add_row("[green]new[/]", "metrics/metric_definitions.json", "LLM-as-judge scoring rubrics for evaluating agent responses")

    # Scenarios
    if mode in ("user-sim", "both"):
        if has_ai:
            if existing_scenarios:
                table.add_row("[green]updated[/]", "scenarios/conversation_scenarios.json", "AI scenarios merged with existing (previous version backed up)")
            else:
                table.add_row("[green]new[/]", "scenarios/conversation_scenarios.json", "AI-generated multi-turn conversation scripts for ADK User Sim")
        elif existing_scenarios:
            table.add_row("[yellow]kept[/]", "[dim]scenarios/conversation_scenarios.json[/]", "[dim]Your current multi-turn scenario scripts (unchanged)[/]")
        else:
            table.add_row("[green]new[/]", "scenarios/conversation_scenarios.json", "Multi-turn conversation scripts for ADK User Sim")

    # Golden data
    if mode in ("diy", "both"):
        if has_ai:
            if existing_golden:
                table.add_row("[green]updated[/]", "eval_data/golden_dataset.json", "AI queries merged with existing (previous version backed up)")
            else:
                table.add_row("[green]new[/]", "eval_data/golden_dataset.json", "AI-generated test queries with expected behaviors")
        elif existing_golden:
            table.add_row("[yellow]kept[/]", "[dim]eval_data/golden_dataset.json[/]", "[dim]Your current test queries (unchanged)[/]")
        else:
            table.add_row("[green]new[/]", "eval_data/golden_dataset.json", "Single-turn test queries with expected behaviors")

    # Session input
    if not existing_session:
        table.add_row("[green]new[/]", "scenarios/session_input.json", "Agent name + user ID for trace collection")

    console.print(table)


def _display_next_steps(
    agent_name: str, agent_dir: Path, mode: str,
    custom_metrics: dict | None = None,
) -> None:
    eval_path = agent_dir / "eval"
    has_ai = custom_metrics is not None

    lines = []
    step = 1

    # Review files
    lines.append(f"[bold]{step}.[/] Review your metric definitions:")
    lines.append(f"   [cyan]{eval_path}/metrics/metric_definitions.json[/]")
    step += 1
    if mode in ("user-sim", "both"):
        lines.append(f"[bold]{step}.[/] Review your scenarios:")
        lines.append(f"   [cyan]{eval_path}/scenarios/conversation_scenarios.json[/]")
        step += 1
    if mode in ("diy", "both"):
        lines.append(f"[bold]{step}.[/] Review your golden dataset:")
        lines.append(f"   [cyan]{eval_path}/eval_data/golden_dataset.json[/]")
        step += 1

    lines.append("")
    lines.append(f"[bold]{step}.[/] Run the full evaluation pipeline:")
    lines.append(f"   [dim]$[/] uv run agent-eval run --agent-dir {agent_dir}")

    lines.append("")
    lines.append("   [dim]This runs: simulate + interact + evaluate + analyze[/]")
    lines.append("   [dim]in a single command with progress tracking.[/]")

    if has_ai and (eval_path / ".backup").exists():
        lines.append("")
        lines.append("[dim]Your previous eval files are backed up in eval/.backup/[/]")
        lines.append("[dim]Delete the backup when you're satisfied with the new files.[/]")

    lines.append("")
    lines.append("[dim]Note: The interact phase sends queries to a running agent.[/]")
    lines.append("[dim]Make sure your agent is serving (e.g. [bold]adk web[/bold]) before running.[/]")
    lines.append("[dim]If the agent isn't reachable, interact is skipped gracefully.[/]")
    lines.append("")
    lines.append("[dim]Or run individual steps — see: uv run agent-eval --help[/]")

    console.print(Panel("\n".join(lines), title="[bold]Next Steps[/]", border_style="green", padding=(1, 2)))


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

    custom_metrics = None
    recommendations = None

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

        if ai_metrics:
            console.print()
            with console.status("[bold blue]Generating tailored metrics with Gemini...[/]", spinner="dots"):
                try:
                    from agent_eval.core.metric_discovery import discover_managed_metrics, get_metric_definition_entry
                    from agent_eval.core.metric_generator import analyze_agent_data, generate_metric_definitions, generate_eval_data

                    # Auto-select general_quality + safety as managed metrics
                    managed = discover_managed_metrics()
                    selected_managed = {}
                    for key in ("general_quality", "safety"):
                        entry = get_metric_definition_entry(key, managed)
                        if entry:
                            selected_managed[key] = entry

                    # Run the 3-step pipeline
                    agent_analysis = analyze_agent_data(agent_dir, agent_name)
                    custom_metrics, rationale = generate_metric_definitions(
                        agent_dir=agent_dir,
                        agent_name=agent_name,
                        agent_analysis=agent_analysis,
                        selected_managed=selected_managed,
                    )
                    eval_data = generate_eval_data(
                        agent_dir=agent_dir,
                        agent_name=agent_name,
                        agent_analysis=agent_analysis,
                        metric_definitions=custom_metrics,
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
        agents = _find_agents(search_dir)

        if agents:
            agent_name_found, agent_dir = _prompt_agent_selection(agents, search_dir)
            agent_name = agent_name or agent_name_found
        else:
            agent_name, agent_dir = _prompt_agent_name_manual()

        mode = mode or _prompt_interaction_mode()
        metrics, custom_metrics, recommendations = _prompt_metrics_choice(agent_dir, agent_name)

    console.print()
    _display_summary(agent_dir, agent_name, mode, metrics, custom_metrics)

    console.print()
    scaffold_eval_structure(
        target_dir=agent_dir,
        agent_name=agent_name,
        mode=mode,
        metrics=metrics,
        custom_metric_definitions=custom_metrics,
        ai_recommendations=recommendations,
    )

    console.print()
    _display_next_steps(agent_name, agent_dir, mode, custom_metrics)
