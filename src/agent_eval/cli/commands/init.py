"""agent-eval init — scaffold the eval/ folder structure for a new agent project."""

from pathlib import Path

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

    # AI generation path
    return _prompt_ai_metrics(agent_dir, agent_name)


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


def _prompt_ai_metrics(agent_dir: Path, agent_name: str) -> tuple[list[str], dict | None, dict | None]:
    """Generate metrics with AI, show results, and get user confirmation.

    Returns (starter_keys_for_managed, custom_definitions_or_None, recommendations_or_None).
    On failure or rejection, falls back to starter metrics.
    """
    # Ask what matters to them
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

    # Check for existing eval files and let the user choose which to include
    eval_dir = agent_dir / "eval"
    exclude_context: set[str] = set()

    found_files: list[tuple[str, str, str]] = []  # (key, label, detail)
    if (eval_dir / "metrics" / "metric_definitions.json").exists():
        found_files.append(("metrics", "Metric definitions", "eval/metrics/metric_definitions.json"))
    if (eval_dir / "scenarios" / "conversation_scenarios.json").exists():
        found_files.append(("scenarios", "Scenarios", "eval/scenarios/conversation_scenarios.json"))
    if (eval_dir / "eval_data" / "golden_dataset.json").exists():
        found_files.append(("golden_data", "Golden dataset", "eval/eval_data/golden_dataset.json"))

    # Only use the latest results folder
    results_dir = eval_dir / "results"
    latest_analysis: Path | None = None
    if results_dir.exists():
        run_folders = sorted(
            [d for d in results_dir.iterdir() if d.is_dir() and (d / "gemini_analysis.md").exists()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if run_folders:
            latest_analysis = run_folders[0] / "gemini_analysis.md"
            rel_path = latest_analysis.relative_to(agent_dir)
            found_files.append(("analysis", "Previous analysis (latest run)", str(rel_path)))

    if found_files:
        console.print()
        console.print("  [bold]Existing eval files found.[/] Gemini can use these as context")
        console.print("  [dim]to build on your current setup instead of starting from scratch.[/]")
        console.print()

        for i, (key, label, detail) in enumerate(found_files, 1):
            console.print(f"    [bold]{i}.[/] [cyan]{label}[/]  [dim]→ {detail}[/]")

        console.print()
        console.print("  [dim]Enter numbers to exclude from context (comma-separated),[/]")
        console.print("  [dim]or press Enter to include all.[/]")
        console.print()
        raw = Prompt.ask("  Exclude", default="")

        if raw.strip():
            for part in raw.split(","):
                try:
                    idx = int(part.strip()) - 1
                    if 0 <= idx < len(found_files):
                        key = found_files[idx][0]
                        exclude_context.add(key)
                        console.print(f"    [dim]Excluding: {found_files[idx][1]}[/]")
                except ValueError:
                    pass

        included = [f[1] for f in found_files if f[0] not in exclude_context]
        if included:
            console.print(f"\n  [dim]Using as context: {', '.join(included)}[/]")
        else:
            console.print(f"\n  [dim]Generating from agent source code only.[/]")

    # Show spinner while generating
    console.print()
    with console.status("[bold blue]Analyzing agent source code with Gemini...[/]", spinner="dots"):
        try:
            from agent_eval.core.metric_generator import generate_metrics_with_gemini
            metrics, rationale, recommendations = generate_metrics_with_gemini(
                agent_dir=agent_dir,
                agent_name=agent_name,
                user_priorities=user_priorities,
                exclude_context=exclude_context if exclude_context else None,
            )
        except Exception as e:
            console.print(f"\n  [yellow]AI generation failed:[/] {e}")
            console.print("  [dim]Falling back to starter metrics.[/]\n")
            return _prompt_starter_metrics(), None, None

    # Display generated metrics
    console.print()
    _display_generated_metrics(metrics, rationale)

    # Display recommendations
    if recommendations:
        _display_recommendations(recommendations)

    # Ask what to do next — loop allows feedback + regeneration
    while True:
        console.print()
        has_existing = (agent_dir / "eval").exists()
        if has_existing:
            console.print("  [dim]Existing eval files will be backed up before updating.[/]")
        else:
            console.print("  [dim]These metrics, scenarios, and test queries will be written to your eval/ folder.[/]")

        console.print()
        console.print("    [bold]1.[/] [green]Accept[/] — create the eval files with these metrics and recommendations")
        console.print("    [bold]2.[/] [cyan]Refine[/] — provide feedback and regenerate")
        console.print("    [bold]3.[/] [yellow]Skip[/]   — use starter metrics instead")

        console.print()
        action = IntPrompt.ask("  Select", default=1)
        while action not in (1, 2, 3):
            console.print("  [red]Please enter 1, 2, or 3[/]")
            action = IntPrompt.ask("  Select", default=1)

        if action == 1:
            # Always include general_quality and safety as managed metrics
            starter_keys = ["general_quality", "safety"]
            return starter_keys, metrics, recommendations

        if action == 3:
            console.print("  [dim]Switching to starter metrics.[/]\n")
            return _prompt_starter_metrics(), None, None

        # action == 2: Refine — get feedback and regenerate
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

        # Combine original priorities with feedback
        combined_priorities = user_priorities
        if combined_priorities:
            combined_priorities += f"\n\nADDITIONAL FEEDBACK (the user reviewed the previous generation and wants these changes): {feedback}"
        else:
            combined_priorities = f"FEEDBACK on previous generation: {feedback}"

        console.print()
        with console.status("[bold blue]Regenerating metrics with your feedback...[/]", spinner="dots"):
            try:
                from agent_eval.core.metric_generator import generate_metrics_with_gemini
                metrics, rationale, recommendations = generate_metrics_with_gemini(
                    agent_dir=agent_dir,
                    agent_name=agent_name,
                    user_priorities=combined_priorities,
                    exclude_context=exclude_context if exclude_context else None,
                )
            except Exception as e:
                console.print(f"\n  [yellow]Regeneration failed:[/] {e}")
                console.print("  [dim]Showing previous results.[/]")
                continue

        # Update priorities for next potential loop
        user_priorities = combined_priorities

        # Show new results
        console.print()
        _display_generated_metrics(metrics, rationale)
        if recommendations:
            _display_recommendations(recommendations)


def _display_generated_metrics(metrics: dict, rationale: str) -> None:
    """Display AI-generated metrics in a Rich table."""
    table = Table(
        title="AI-Generated Metrics",
        border_style="cyan",
        padding=(0, 2),
    )
    table.add_column("Metric", style="bold cyan")
    table.add_column("Description")
    table.add_column("Runs On", style="dim", justify="center")

    applies_labels = {"all": "all data", "scenarios": "scenarios", "golden_dataset": "golden data"}
    for name, defn in metrics.items():
        desc = defn.get("score_range", {}).get("description", "")
        applies = applies_labels.get(defn.get("applies_to", "all"), "all data")
        table.add_row(name, desc, applies)

    console.print(table)

    if rationale and not rationale.startswith("\n"):
        console.print()
        console.print(Panel(
            rationale,
            title="[bold]Rationale[/]",
            border_style="dim",
            padding=(1, 2),
        ))

    console.print()
    console.print("  [dim]+ general_quality and safety are always included automatically.[/]")


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
                    from agent_eval.core.metric_generator import generate_metrics_with_gemini
                    custom_metrics, rationale, recommendations = generate_metrics_with_gemini(
                        agent_dir=agent_dir,
                        agent_name=agent_name,
                    )
                    metrics = ["general_quality", "safety"]
                    console.print(f"  [green]Generated {len(custom_metrics)} custom metrics[/]")
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
