"""agent-eval simulate — run ADK User Sim and convert traces in one step."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()

# Base args for running ADK commands in the agent's project context.
# --with ensures google-adk[eval] is available even if the agent's own
# pyproject.toml only depends on google-adk (without the eval extra).
_UV_RUN_ADK = ["uv", "run", "--with", "google-adk[eval]"]


def _clean_env(project_root: Path) -> dict[str, str]:
    """Return a clean environment for running ADK commands.

    1. Strips VIRTUAL_ENV so uv resolves the agent's project venv (not root's)
    2. Loads the agent project's .env file so GCP vars are available
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    # Load .env from the agent's project root (where pyproject.toml lives)
    dotenv_path = project_root / ".env"
    if dotenv_path.is_file():
        for line in dotenv_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                # Don't override vars already set in the shell
                if key not in env:
                    env[key] = value

    return env


# Files ADK expects inside the agent module directory
_ADK_REQUIRED_FILES = ["session_input.json", "conversation_scenarios.json", "eval_config.json"]

# Default eval_config — empty criteria so ADK skips its built-in per-interaction
# LLM scoring (hallucination, safety). These are slow because ADK scores each
# interaction individually. agent-eval runs its own evaluation in batch via
# Vertex AI Evaluation, which is faster and more configurable.
_DEFAULT_EVAL_CONFIG = {
    "criteria": {}
}

TOTAL_STEPS = 5


def _step_header(n: int, title: str, description: str) -> None:
    """Print a formatted step header."""
    console.print()
    console.print(Rule(f"  Step {n}/{TOTAL_STEPS}: {title}  ", style="bold blue"))
    console.print(f"  [dim]{description}[/]")
    console.print()


def _find_eval_dir(agent_dir: Path) -> Path | None:
    """Find the eval/ directory — check inside agent_dir first, then parent."""
    if (agent_dir / "eval").is_dir():
        return agent_dir / "eval"
    if (agent_dir.parent / "eval").is_dir():
        return agent_dir.parent / "eval"
    return None


def _count_scenarios(scenarios_file: Path) -> int:
    """Count the number of scenarios in a scenarios JSON file."""
    try:
        data = json.loads(scenarios_file.read_text())
        return len(data.get("scenarios", []))
    except (json.JSONDecodeError, FileNotFoundError):
        return 0


def _step_symlinks(agent_dir: Path, eval_dir: Path) -> None:
    """Step 1: Create symlinks in the agent module dir pointing to eval/scenarios/.

    ADK requires session_input.json, conversation_scenarios.json, and
    eval_config.json to be inside the agent module directory (next to agent.py).
    We symlink them from eval/scenarios/ so there's a single source of truth.
    """
    _step_header(1, "Symlink scenario files",
                 "ADK needs scenario files next to agent.py. Creating symlinks\n"
                 "  from eval/scenarios/ so you only maintain files in one place.")

    scenarios_dir = eval_dir / "scenarios"

    for filename in _ADK_REQUIRED_FILES:
        target = agent_dir / filename
        source = scenarios_dir / filename

        # Create default eval_config.json if it doesn't exist
        if filename == "eval_config.json" and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(json.dumps(_DEFAULT_EVAL_CONFIG, indent=2) + "\n")
            console.print(f"    [green]+[/] Created {source}")
            console.print(f"      [dim]Empty criteria — ADK's built-in scoring is skipped (agent-eval runs its own batch evaluation)[/]")

        if not source.exists():
            console.print(f"    [yellow]![/] Skipping {filename} — not found in {scenarios_dir}")
            continue

        # Remove existing file/symlink at target
        action = "updated" if (target.is_symlink() or target.exists()) else "created"
        if target.is_symlink() or target.exists():
            target.unlink()

        # Create relative symlink
        rel_path = os.path.relpath(source, agent_dir)
        target.symlink_to(rel_path)
        console.print(f"    [green]+[/] {action.capitalize()} symlink: {agent_dir.name}/{filename} → {rel_path}")


def _step_clear_history(agent_dir: Path) -> None:
    """Step 2: Clear ADK eval_history to avoid stale traces."""
    _step_header(2, "Clear eval history",
                 "Removing previous ADK traces so this run starts fresh.\n"
                 "  Stale traces would mix with new results and corrupt metrics.")

    eval_history = agent_dir / ".adk" / "eval_history"
    if eval_history.exists():
        n_files = sum(1 for _ in eval_history.rglob("*") if _.is_file())
        shutil.rmtree(eval_history)
        console.print(f"    [green]+[/] Cleared {n_files} file{'s' if n_files != 1 else ''} from {eval_history}")
    else:
        console.print(f"    [dim]Nothing to clear — no previous eval_history found.[/]")


def _step_create_eval_set(agent_name: str, agent_dir: Path) -> bool:
    """Step 3: Create a fresh eval_set and add scenarios."""
    _step_header(3, "Create eval set",
                 "Creating a fresh ADK eval_set and loading your scenarios.\n"
                 "  The eval_set is recreated from scratch each time to avoid\n"
                 "  duplicate scenarios (adk add_eval_case appends, not replaces).")

    eval_set_name = "eval_set"
    project_root = agent_dir.parent

    # Remove existing eval_set — ADK stores it in two places:
    # 1. <agent_dir>/<name>.evalset.json (the main file ADK checks)
    # 2. <agent_dir>/.adk/eval_sets/<name>/ (eval case data)
    removed = False
    evalset_file = agent_dir / f"{eval_set_name}.evalset.json"
    if evalset_file.exists():
        evalset_file.unlink()
        removed = True
    eval_set_dir = agent_dir / ".adk" / "eval_sets" / eval_set_name
    if eval_set_dir.exists():
        shutil.rmtree(eval_set_dir)
        removed = True
    if removed:
        console.print(f"    [green]+[/] Removed existing eval_set (prevents duplicates)")
    else:
        console.print(f"    [dim]No existing eval_set to remove.[/]")

    # Create eval_set
    cmd = f"uv run adk eval_set create {agent_name} {eval_set_name}"
    console.print(f"    [dim]$ {cmd}[/]")
    result = subprocess.run(
        [*_UV_RUN_ADK, "adk", "eval_set", "create", agent_name, eval_set_name],
        cwd=str(project_root),
        env=_clean_env(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"    [red]Failed to create eval_set[/]")
        if result.stderr.strip():
            console.print(f"    [red]{result.stderr.strip()}[/]")
        return False
    console.print(f"    [green]+[/] Created eval_set: {eval_set_name}")

    # Add eval cases from scenarios
    scenarios_file = agent_dir / "conversation_scenarios.json"
    session_file = agent_dir / "session_input.json"
    n_scenarios = _count_scenarios(scenarios_file)

    cmd = f"uv run adk eval_set add_eval_case {agent_name} {eval_set_name} --scenarios_file ... --session_input_file ..."
    console.print(f"    [dim]$ {cmd}[/]")
    result = subprocess.run(
        [
            *_UV_RUN_ADK, "adk", "eval_set", "add_eval_case",
            agent_name, eval_set_name,
            "--scenarios_file", str(scenarios_file),
            "--session_input_file", str(session_file),
        ],
        cwd=str(project_root),
        env=_clean_env(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"    [red]Failed to add eval cases[/]")
        if result.stderr.strip():
            console.print(f"    [red]{result.stderr.strip()}[/]")
        return False
    console.print(f"    [green]+[/] Added [cyan]{n_scenarios}[/] scenario{'s' if n_scenarios != 1 else ''} to eval_set")

    return True


def _step_run_sim(agent_name: str, agent_dir: Path, debug: bool = False) -> bool:
    """Step 4: Run adk eval (the actual User Sim)."""
    _step_header(4, "Run ADK User Sim",
                 "An LLM will now play the role of a user, following each scenario.\n"
                 "  This generates OpenTelemetry traces that capture every tool call,\n"
                 "  response, and token count. This step may take a few minutes.\n\n"
                 "  After the simulation, ADK runs its own built-in evaluation\n"
                 "  (hallucination + safety checks). These are a useful starting point,\n"
                 "  but agent-eval's evaluate command adds much deeper analysis:\n"
                 "  deterministic metrics (latency, tokens, cost, cache efficiency)\n"
                 "  and your custom LLM-as-judge metrics via Vertex AI.")

    eval_set_name = "eval_set"
    project_root = agent_dir.parent
    eval_config = agent_dir / "eval_config.json"

    cmd = f"uv run adk eval {agent_name} --config_file_path {agent_name}/eval_config.json {eval_set_name}"
    console.print(f"    [dim]$ {cmd}[/]")
    console.print()

    adk_cmd = [*_UV_RUN_ADK, "adk", "eval", agent_name]
    if eval_config.exists():
        adk_cmd += ["--config_file_path", str(eval_config)]
    adk_cmd.append(eval_set_name)

    # In debug mode, stream ADK output so the user sees everything.
    # In normal mode, capture it — ADK's "Tests passed/failed" summary refers
    # to its built-in scoring, not the simulation quality, which confuses users.
    if debug:
        console.print(f"    [dim]Debug: streaming ADK output...[/]")
        result = subprocess.run(
            adk_cmd,
            cwd=str(project_root),
            env=_clean_env(project_root),
            text=True,
        )
    else:
        result = subprocess.run(
            adk_cmd,
            cwd=str(project_root),
            env=_clean_env(project_root),
            capture_output=True,
            text=True,
        )

    # Check if traces were generated, regardless of exit code.
    # ADK's built-in scoring can fail (e.g., missing expected_invocations)
    # even when the simulations ran fine and traces were captured.
    eval_history = agent_dir / ".adk" / "eval_history"
    has_traces = eval_history.exists() and any(eval_history.rglob("*.json"))

    if result.returncode != 0 and has_traces:
        console.print(f"\n    [yellow]![/] ADK simulation completed, but ADK's built-in scoring had errors.")
        console.print(f"    [dim]This is expected — agent-eval runs its own evaluation separately.[/]")
        return True

    if result.returncode != 0:
        # Show captured output only on real failures
        if result.stderr:
            console.print(f"\n    [dim]{result.stderr.strip()}[/]")
        console.print(f"\n    [red]ADK eval failed with exit code {result.returncode}[/]")
        console.print(f"    [dim]No traces were generated. Common issues:[/]")
        console.print(f"    [dim]  - Missing GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_LOCATION[/]")
        console.print(f"    [dim]  - Agent module not found (app_name mismatch)[/]")
        console.print(f"    [dim]  - Missing dependencies (run uv sync in agent project)[/]")
        return False

    console.print(f"\n    [green]+[/] ADK User Sim completed successfully")
    return True


def _step_convert(agent_dir: Path, eval_dir: Path, run_id: str | None = None) -> str | None:
    """Step 5: Convert ADK traces to evaluation format."""
    _step_header(5, "Convert traces",
                 "Converting ADK's OpenTelemetry traces into agent-eval's JSONL format.\n"
                 "  This extracts tool calls, responses, token counts, and timing data\n"
                 "  so they can be scored by the evaluate command.")

    from agent_eval.core.converters import AdkHistoryConverter, write_jsonl

    try:
        converter = AdkHistoryConverter(str(agent_dir), None)
        records = converter.run()

        if not records:
            console.print("    [yellow]![/] No traces found to convert.")
            console.print("    [dim]This usually means ADK eval didn't produce any output.[/]")
            console.print("    [dim]Check that eval_history exists in {agent_dir}/.adk/[/]")
            return None

        folder_name = run_id if run_id else datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = eval_dir / "results"
        run_dir = results_dir / folder_name
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        output_path = raw_dir / "processed_interaction_sim.jsonl"
        write_jsonl(records, str(output_path))

        console.print(f"    [green]+[/] Converted [cyan]{len(records)}[/] interaction{'s' if len(records) != 1 else ''}")
        console.print(f"    [green]+[/] Output: {output_path}")
        console.print(f"    [green]+[/] Run directory: {run_dir}")

        return str(run_dir)

    except Exception as e:
        console.print(f"    [red]Error converting traces:[/] {e}")
        return None


@click.command()
@click.option("--agent-dir", required=True,
              help="Path to the agent module directory (containing agent.py).")
@click.option("--eval-dir", default=None,
              help="Path to eval/ directory (auto-detected if omitted).")
@click.option("--run-id", default=None,
              help="Name for the results folder (e.g., 'baseline', 'tool-hardening'). "
                   "Defaults to a timestamp like 20260319_060430. Use meaningful names "
                   "to keep track of optimization iterations.")
@click.option("--debug", is_flag=True, help="Show detailed logs from ADK, Vertex AI SDK, and other services.")
def simulate(agent_dir, eval_dir, run_id, debug):
    """Run ADK User Sim scenarios and convert traces to evaluation format.

    This command wraps the full ADK User Sim workflow into a single step:

    \b
    1. Creates symlinks so ADK can find scenario files
    2. Clears previous eval_history to avoid stale traces
    3. Creates a fresh eval_set (avoids duplicate scenarios)
    4. Runs adk eval with your scenarios
    5. Converts the resulting traces to agent-eval format

    After this, run `agent-eval evaluate` on the output.

    \b
    Note: ADK's built-in eval runs a limited set of metrics (hallucination,
    safety). agent-eval adds deterministic metrics (latency, tokens, cost)
    and custom LLM-as-judge metrics via the Vertex AI Evaluation service.
    This also means agent-eval is not locked to ADK — you can run evaluate
    and analyze on traces from any agent framework.
    """
    from agent_eval.cli.main import _display_banner
    from agent_eval.core.evaluator import configure_logging
    _display_banner()
    configure_logging(debug=debug)

    agent_path = Path(agent_dir).resolve()

    # ── Validation ──────────────────────────────────────────────────────────

    if not (agent_path / "agent.py").exists():
        console.print(f"\n  [red]Error:[/] No agent.py found in {agent_path}")
        console.print(f"  [dim]The --agent-dir should point to the folder containing agent.py[/]")
        sys.exit(1)

    agent_name = agent_path.name

    # Find eval directory
    if eval_dir:
        eval_path = Path(eval_dir).resolve()
    else:
        eval_path = _find_eval_dir(agent_path)
        if not eval_path:
            console.print(f"\n  [red]Error:[/] No eval/ directory found near {agent_path}")
            console.print(f"  [dim]Run `uv run agent-eval init` first to scaffold one.[/]")
            sys.exit(1)

    from agent_eval.core.config import find_eval_files
    discovered = find_eval_files(eval_path)
    if discovered["scenarios"]:
        scenarios_file = discovered["scenarios"][0]
    else:
        console.print(f"\n  [red]Error:[/] No scenario files found in {eval_path / 'scenarios'}")
        console.print(f"  [dim]Create your scenarios as .json files in eval/scenarios/[/]")
        sys.exit(1)

    session_file = eval_path / "scenarios" / "session_input.json"
    if not session_file.exists():
        console.print(f"\n  [red]Error:[/] No session input file at {session_file}")
        console.print(f"  [dim]Create session_input.json with your app_name and user_id[/]")
        sys.exit(1)

    n_scenarios = _count_scenarios(scenarios_file)

    # ── Run ID ─────────────────────────────────────────────────────────────

    if not run_id:
        from rich.prompt import Prompt
        console.print()
        console.print(Panel(
            "[bold]Give this run a name[/] so you can easily find it later.\n\n"
            "Examples: [cyan]baseline[/], [cyan]v2-tool-hardening[/], [cyan]cache-optimization[/]\n\n"
            "[dim]Results will be saved to eval/results/<run-id>/.\n"
            "Press Enter to use an auto-generated timestamp instead.[/]",
            title="[bold]Run ID[/]",
            border_style="blue",
            padding=(1, 2),
        ))
        default_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = Prompt.ask(
            "  Run ID",
            default=default_ts,
        ).strip()
        # Sanitize: replace spaces with hyphens, remove problematic chars
        run_id = run_id.replace(" ", "-")

    # ── Overview ────────────────────────────────────────────────────────────

    console.print(Panel(
        f"[bold]Agent:[/]      [cyan]{agent_name}[/]  [dim]({agent_path})[/]\n"
        f"[bold]Eval dir:[/]   {eval_path}\n"
        f"[bold]Scenarios:[/]  [cyan]{n_scenarios}[/] scenario{'s' if n_scenarios != 1 else ''}"
        f" in conversation_scenarios.json\n"
        f"[bold]Run ID:[/]     [cyan]{run_id}[/]"
        f"  [dim](results saved to eval/results/{run_id}/)[/]\n\n"
        f"[bold]What will happen:[/]\n"
        f"  [dim]1.[/] Symlink scenario files into agent directory (for ADK)\n"
        f"  [dim]2.[/] Clear previous eval_history (avoid stale traces)\n"
        f"  [dim]3.[/] Create fresh eval_set + load scenarios (avoid duplicates)\n"
        f"  [dim]4.[/] Run ADK User Sim (LLM simulates users from your scenarios)\n"
        f"  [dim]5.[/] Convert traces to agent-eval JSONL format",
        title="[bold]Simulate[/]",
        border_style="blue",
        padding=(1, 2),
    ))

    # ── Execute steps ───────────────────────────────────────────────────────

    _step_symlinks(agent_path, eval_path)

    _step_clear_history(agent_path)

    if not _step_create_eval_set(agent_name, agent_path):
        sys.exit(1)

    if not _step_run_sim(agent_name, agent_path, debug=debug):
        sys.exit(1)

    run_dir = _step_convert(agent_path, eval_path, run_id)
    if not run_dir:
        sys.exit(1)

    # ── Done ────────────────────────────────────────────────────────────────

    # Use relative paths for clean copy-pasteable commands
    cwd = Path.cwd()
    rel_run = os.path.relpath(run_dir, cwd)
    rel_metrics = os.path.relpath(eval_path / "metrics" / "metric_definitions.json", cwd)
    rel_agent = os.path.relpath(agent_path, cwd)

    console.print()
    console.print(Panel(
        f"[bold green]Simulation complete![/]\n\n"
        f"[bold]Results:[/]  {rel_run}/\n\n"
        "[dim]ADK's built-in eval covers hallucination + safety checks.\n"
        "agent-eval evaluate adds: latency, tokens, cost, cache efficiency,\n"
        "and your custom LLM-as-judge metrics from metric_definitions.json.[/]",
        title="[bold]Done[/]",
        border_style="green",
        padding=(1, 2),
    ))

    console.print()
    console.print("[bold]Next steps — copy and paste:[/]")
    console.print()
    console.print("[bold]1.[/] Run deterministic + LLM-as-judge metrics:")
    console.print()
    console.print(f"uv run agent-eval evaluate \\")
    console.print(f"  --interaction-file {rel_run}/raw/processed_interaction_sim.jsonl \\")
    console.print(f"  --metrics-files {rel_metrics} \\")
    console.print(f"  --results-dir {rel_run}")
    console.print()
    console.print("[bold]2.[/] Generate AI-powered analysis:")
    console.print()
    console.print(f"uv run agent-eval analyze \\")
    console.print(f"  --results-dir {rel_run} \\")
    console.print(f"  --agent-dir {rel_agent}")
    console.print()
