"""agent-eval init — scaffold the eval/ folder structure for a new agent project."""

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from agent_eval.core.scaffold import scaffold_eval_structure

console = Console()

INTERACTION_MODES = [
    ("user-sim", "ADK User Sim", "LLM simulates users from scenario definitions (multi-turn)"),
    ("diy", "DIY Interactions", "Run queries against a live agent endpoint (single-turn)"),
    ("both", "Both", "Generate both scenario and golden dataset files"),
]

STARTER_METRICS = [
    ("general_quality", "General Quality", "API Predefined — overall response quality", True),
    ("trajectory_accuracy", "Trajectory Accuracy", "Custom LLM — evaluates tool call sequences", True),
    ("tool_use_quality", "Tool Use Quality", "Custom LLM — evaluates tool argument correctness", False),
    ("safety", "Safety", "API Predefined — safety compliance", False),
]


def _prompt_agent_name() -> str:
    return Prompt.ask(
        "\n  Agent name [dim](used in session_input.json)[/]",
        default="my_agent",
    )


def _prompt_interaction_mode() -> str:
    console.print("\n  How do you generate agent interactions?\n")
    for i, (_, label, desc) in enumerate(INTERACTION_MODES, 1):
        console.print(f"    [bold]{i}.[/] {label:20s} [dim]{desc}[/]")

    choice = IntPrompt.ask("\n  Select", default=3)
    while choice < 1 or choice > len(INTERACTION_MODES):
        console.print(f"  [red]Please enter a number between 1 and {len(INTERACTION_MODES)}[/]")
        choice = IntPrompt.ask("  Select", default=3)

    return INTERACTION_MODES[choice - 1][0]


def _prompt_metrics() -> list[str]:
    selected = [key for key, _, _, default in STARTER_METRICS if default]

    console.print("\n  Which starter metrics do you want?\n")
    for i, (key, label, desc, default) in enumerate(STARTER_METRICS, 1):
        marker = "[green]x[/]" if key in selected else " "
        console.print(f"    [{marker}] [bold]{i}.[/] {label:24s} [dim]{desc}[/]")

    console.print("\n  [dim]Enter numbers to toggle (e.g. 3), or press Enter to continue.[/]")

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
                # Redraw
                console.print()
                for i, (k, label, desc, _) in enumerate(STARTER_METRICS, 1):
                    marker = "[green]x[/]" if k in selected else " "
                    console.print(f"    [{marker}] [bold]{i}.[/] {label:24s} [dim]{desc}[/]")
                console.print()
        except ValueError:
            console.print("  [red]Enter a number or press Enter to continue.[/]")

    return selected


def _display_summary(target_dir: Path, agent_name: str, mode: str, metrics: list[str]) -> None:
    mode_label = next(label for key, label, _ in INTERACTION_MODES if key == mode)
    metrics_str = ", ".join(metrics) if metrics else "(none)"

    files = ["eval/__init__.py", "eval/metrics/metric_definitions.json",
             "eval/scenarios/session_input.json", "eval/results/.gitkeep"]
    if mode in ("user-sim", "both"):
        files.append("eval/scenarios/conversation_scenarios.json")
    if mode in ("diy", "both"):
        files.append("eval/eval_data/golden_dataset.json")

    table = Table(show_header=False, show_edge=False, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Agent:", agent_name)
    table.add_row("Mode:", mode_label)
    table.add_row("Metrics:", metrics_str)
    table.add_row("", "")
    table.add_row("Files:", "")
    for f in files:
        table.add_row("", f"  {f}")

    console.print(Panel(table, title="Summary", border_style="blue", padding=(1, 2)))


def _display_next_steps(mode: str) -> None:
    lines = []
    if mode in ("user-sim", "both"):
        lines.append("1. Edit your scenarios:")
        lines.append("   eval/scenarios/conversation_scenarios.json")
        lines.append("")
        lines.append("2. Run ADK simulation:")
        lines.append("   uv run adk eval <agent_module> <eval_set>")
        lines.append("")
        lines.append("3. Convert traces:")
        lines.append("   agent-eval convert --agent-dir <module>")
    elif mode == "diy":
        lines.append("1. Edit your golden dataset:")
        lines.append("   eval/eval_data/golden_dataset.json")
        lines.append("")
        lines.append("2. Start your agent, then run:")
        lines.append("   agent-eval interact --app-name <name> --questions-file eval/eval_data/golden_dataset.json")

    lines.append("")
    lines.append("Then evaluate:")
    lines.append("  agent-eval evaluate --interaction-file <file> --metrics-files eval/metrics/metric_definitions.json --results-dir eval/results")
    lines.append("")
    lines.append("Docs: agent-eval --help")

    console.print(Panel("\n".join(lines), title="Next Steps", border_style="green", padding=(1, 2)))


@click.command()
@click.option("--target-dir", default=".", help="Root directory of your agent project.")
@click.option("--agent-name", default=None, help="Agent application name.")
@click.option("--mode", type=click.Choice(["user-sim", "diy", "both"]), default=None,
              help="Interaction mode.")
@click.option("--auto-approve", "-y", is_flag=True, help="Skip interactive prompts, use defaults.")
def init(target_dir, agent_name, mode, auto_approve):
    """Scaffold the eval/ folder structure for a new agent project."""
    from agent_eval.cli.main import _display_banner
    _display_banner()

    console.print("  Setting up evaluation for your agent project.\n")

    target = Path(target_dir)

    if auto_approve:
        agent_name = agent_name or "my_agent"
        mode = mode or "both"
        metrics = [key for key, _, _, default in STARTER_METRICS if default]
    else:
        agent_name = agent_name or _prompt_agent_name()
        mode = mode or _prompt_interaction_mode()
        metrics = _prompt_metrics()

    _display_summary(target, agent_name, mode, metrics)

    if not auto_approve:
        if not Confirm.ask("\n  Create these files?", default=True):
            console.print("\n  [yellow]Cancelled.[/]")
            return

    scaffold_eval_structure(
        target_dir=target,
        agent_name=agent_name,
        mode=mode,
        metrics=metrics,
    )

    console.print()
    _display_next_steps(mode)
