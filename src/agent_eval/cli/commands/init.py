"""agent-eval init — scaffold the eval/ folder structure for a new agent project."""

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from agent_eval.core.scaffold import scaffold_eval_structure

console = Console()

# Directories to skip when searching for agent.py
_SKIP_DIRS = {".venv", "venv", "site-packages", "node_modules", "__pycache__",
              ".git", ".adk", "sub_agents", "app_env", "eval_history"}

INTERACTION_MODES = [
    ("user-sim", "ADK User Sim (multi-turn)",
     "An LLM plays the role of a user, following scenario scripts you define.\n"
     "       Best for: conversational agents with back-and-forth dialogue."),
    ("diy", "DIY Interactions (single-turn)",
     "You send specific queries from a golden dataset to a running agent.\n"
     "       Best for: pipeline agents, deployed endpoints, or regression testing."),
    ("both", "Both",
     "Generates files for both methods — pick whichever fits when you're ready."),
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
        "\n  [dim]Not sure? Pick [bold]Both[/bold] (3) — you can always delete files you don't need.[/]"
    )

    choice = IntPrompt.ask("\n  Select", default=3)
    while choice < 1 or choice > len(INTERACTION_MODES):
        console.print(f"  [red]Please enter a number between 1 and {len(INTERACTION_MODES)}[/]")
        choice = IntPrompt.ask("  Select", default=3)

    return INTERACTION_MODES[choice - 1][0]


# ── Step 3: Metrics ─────────────────────────────────────────────────────────


def _prompt_metrics() -> list[str]:
    selected = [key for key, _, _, default in STARTER_METRICS if default]

    console.print(Panel(
        "[bold]Step 3 of 3[/] — Select starter metrics\n\n"
        "These define how your agent's responses will be scored.\n"
        "[bold]Deterministic metrics[/] (latency, tokens, cost) are always included.\n"
        "Below are the [bold]LLM-as-judge metrics[/] — an LLM scores each response\n"
        "against the rubric you define. You can customize them later in\n"
        "[cyan]eval/metrics/metric_definitions.json[/].",
        border_style="blue",
        padding=(1, 2),
    ))

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


def _draw_metrics(selected: list[str]) -> None:
    for i, (key, label, desc, _) in enumerate(STARTER_METRICS, 1):
        marker = "[green]x[/]" if key in selected else " "
        console.print(f"    [{marker}] [bold]{i}.[/] {label:24s} [dim]{desc}[/]")


# ── Summary & Next Steps ───────────────────────────────────────────────────


def _display_summary(agent_dir: Path, agent_name: str, mode: str, metrics: list[str]) -> None:
    mode_label = next(label for key, label, _ in INTERACTION_MODES if key == mode)
    metrics_str = ", ".join(metrics) if metrics else "(none)"
    eval_dir = agent_dir / "eval"

    # Build file list with descriptions
    files = [("__init__.py", None)]
    files.append(("metrics/metric_definitions.json", _FILE_DESCRIPTIONS["metrics/metric_definitions.json"]))
    files.append(("scenarios/session_input.json", _FILE_DESCRIPTIONS["scenarios/session_input.json"]))
    if mode in ("user-sim", "both"):
        files.append(("scenarios/conversation_scenarios.json", _FILE_DESCRIPTIONS["scenarios/conversation_scenarios.json"]))
    if mode in ("diy", "both"):
        files.append(("eval_data/golden_dataset.json", _FILE_DESCRIPTIONS["eval_data/golden_dataset.json"]))
    files.append(("results/.gitkeep", _FILE_DESCRIPTIONS["results/.gitkeep"]))

    table = Table(show_header=False, show_edge=False, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Agent module:", f"[cyan]{agent_name}/[/]  [dim]({agent_dir})[/]")
    table.add_row("Eval folder:", f"[cyan]{eval_dir}/[/]")
    table.add_row("Mode:", mode_label)
    table.add_row("Metrics:", metrics_str)
    table.add_row("", "")
    table.add_row("Files:", "")
    for filename, desc in files:
        if desc:
            table.add_row("", f"  [cyan]{filename}[/]  [dim]{desc}[/]")
        else:
            table.add_row("", f"  [dim]{filename}[/]")

    console.print(Panel(table, title="[bold]Review[/]", border_style="blue", padding=(1, 2)))


def _display_next_steps(agent_name: str, agent_dir: Path, mode: str) -> None:
    eval_path = agent_dir / "eval"

    lines = []
    if mode in ("user-sim", "both"):
        lines.append("[bold]1.[/] Edit your scenarios:")
        lines.append(f"   [cyan]{eval_path}/scenarios/conversation_scenarios.json[/]")
        lines.append("")
        lines.append("[bold]2.[/] Run simulation + convert traces (one command):")
        lines.append(f"   [dim]$[/] uv run agent-eval simulate --agent-dir {agent_dir}")
        lines.append("")
        lines.append("   [dim]This creates symlinks, clears history, runs ADK User Sim,[/]")
        lines.append("   [dim]and converts traces to evaluation format automatically.[/]")
    elif mode == "diy":
        lines.append("[bold]1.[/] Edit your golden dataset:")
        lines.append(f"   [cyan]{eval_path}/eval_data/golden_dataset.json[/]")
        lines.append("")
        lines.append("[bold]2.[/] Start your agent, then run:")
        lines.append(f"   [dim]$[/] uv run agent-eval interact --app-name {agent_name} \\")
        lines.append(f"       --questions-file {eval_path}/eval_data/golden_dataset.json")

    lines.append("")
    lines.append("[bold]Then evaluate + analyze:[/]")
    lines.append(f"  [dim]$[/] uv run agent-eval evaluate \\")
    lines.append(f"      --interaction-file {eval_path}/results/<run>/raw/processed_interaction_*.jsonl \\")
    lines.append(f"      --metrics-files {eval_path}/metrics/metric_definitions.json \\")
    lines.append(f"      --results-dir {eval_path}/results/<run>")
    lines.append(f"  [dim]$[/] uv run agent-eval analyze \\")
    lines.append(f"      --results-dir {eval_path}/results/<run> --agent-dir {agent_dir}")
    lines.append("")
    lines.append("[dim]Full reference: uv run agent-eval --help[/]")

    console.print(Panel("\n".join(lines), title="[bold]Next Steps[/]", border_style="green", padding=(1, 2)))


# ── Command ─────────────────────────────────────────────────────────────────


@click.command()
@click.option("--target-dir", default=None, help="Directory containing agent.py (eval/ will be created here).")
@click.option("--agent-name", default=None, help="Agent module name (auto-detected from target-dir if omitted).")
@click.option("--mode", type=click.Choice(["user-sim", "diy", "both"]), default=None,
              help="Interaction mode.")
@click.option("--auto-approve", "-y", is_flag=True, help="Skip interactive prompts, use defaults.")
def init(target_dir, agent_name, mode, auto_approve):
    """Scaffold the eval/ folder structure for an ADK agent.

    Searches for agent.py files in the current directory tree and lets you
    select which agent to add evaluation to. The eval/ folder is created
    inside the agent module directory, as a sibling to agent.py.
    """
    from agent_eval.cli.main import _display_banner
    _display_banner()

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
        metrics = _prompt_metrics()

    console.print()
    _display_summary(agent_dir, agent_name, mode, metrics)

    if not auto_approve:
        if not Confirm.ask("\n  Create these files?", default=True):
            console.print("\n  [yellow]Cancelled.[/]")
            return

    console.print()
    scaffold_eval_structure(
        target_dir=agent_dir,
        agent_name=agent_name,
        mode=mode,
        metrics=metrics,
    )

    console.print()
    _display_next_steps(agent_name, agent_dir, mode)
