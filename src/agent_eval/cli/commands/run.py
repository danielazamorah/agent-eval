"""agent-eval run — orchestrate simulate, interact, and evaluate in one command."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()


def _find_eval_dir(agent_dir: Path) -> Path | None:
    """Find the eval/ directory — check inside agent_dir first, then parent."""
    if (agent_dir / "eval").is_dir():
        return agent_dir / "eval"
    if (agent_dir.parent / "eval").is_dir():
        return agent_dir.parent / "eval"
    return None


@click.command()
@click.option("--agent-dir", required=True,
              help="Path to the agent module directory (containing agent.py).")
@click.option("--eval-dir", default=None,
              help="Path to eval/ directory (auto-detected if omitted).")
@click.option("--run-id", default=None,
              help="Name for the results folder (e.g., 'baseline'). Defaults to a timestamp.")
@click.option("--simulate/--no-simulate", "run_simulate", default=True,
              help="Run ADK User Sim scenarios (default: yes).")
@click.option("--interact/--no-interact", "run_interact", default=True,
              help="Run DIY interactions against a live agent (default: yes). Skipped gracefully if agent is unreachable.")
@click.option("--base-url", default="http://localhost:8501",
              help="Agent API URL for interact mode.")
@click.option("--evaluate/--no-evaluate", "run_evaluate", default=True,
              help="Run evaluation after collecting interactions (default: yes).")
@click.option("--app-name", default=None,
              help="Agent app name for interact (defaults to agent dir name).")
@click.option("--questions-file", default=None,
              help="Path to golden dataset JSON for interact mode.")
@click.option("--num-questions", type=int, default=-1,
              help="Limit number of questions for interact (-1 = all).")
@click.option("--skip-traces", is_flag=True,
              help="Skip trace retrieval in interact mode (faster).")
@click.option("--analyze/--no-analyze", "run_analyze", default=True,
              help="Run AI-powered analysis after evaluation (default: yes).")
@click.option("--focus", default=None,
              help="Developer focus for analysis: metric names to highlight (e.g., 'latency, cache').")
@click.option("--skip-gemini", is_flag=True,
              help="Skip AI-powered analysis in the analyze phase.")
@click.option("--dashboard/--no-dashboard", "run_dashboard", default=None,
              help="Launch interactive dashboard after pipeline (default: prompt if gradio installed).")
@click.option("--debug", is_flag=True,
              help="Show detailed logs from all phases (ADK, Vertex AI SDK, etc.).")
def run(agent_dir, eval_dir, run_id, run_simulate, run_interact, base_url,
        run_evaluate, app_name, questions_file, num_questions, skip_traces,
        run_analyze, focus, skip_gemini, run_dashboard, debug):
    """Run the full evaluation pipeline: simulate, interact, evaluate, and analyze.

    \b
    This command orchestrates the full workflow in a single step:
      1. Run ADK User Sim scenarios              → simulation JSONL
      2. Run DIY interactions against live agent  → interaction JSONL
      3. Run evaluation metrics on all collected interaction files
      4. Generate AI-powered analysis + comparison tables

    \b
    By default, all four phases run. If the agent is not reachable at
    --base-url, the interact phase is skipped gracefully and evaluation
    proceeds with simulation data only.

    \b
    Examples:
      # Full pipeline (simulate + interact + evaluate + analyze)
      uv run agent-eval run --agent-dir agents/my-agent/app

    \b
      # Skip interact (simulation only)
      uv run agent-eval run --agent-dir agents/my-agent/app --no-interact

    \b
      # With focus highlighting in analysis
      uv run agent-eval run --agent-dir agents/my-agent/app --focus "latency, cache"
    """
    from agent_eval.cli.main import _display_banner
    from agent_eval.core.evaluator import configure_logging
    _display_banner()

    # ── Logging ─────────────────────────────────────────────────────────────
    configure_logging(debug=debug)

    # ── Validation ──────────────────────────────────────────────────────────

    if not run_simulate and not run_interact:
        console.print("\n  [red]Error:[/] Nothing to do. Use --simulate and/or --interact.")
        sys.exit(1)

    agent_path = Path(agent_dir).resolve()

    if not (agent_path / "agent.py").exists():
        console.print(f"\n  [red]Error:[/] No agent.py found in {agent_path}")
        console.print(f"  [dim]The --agent-dir should point to the folder containing agent.py[/]")
        sys.exit(1)

    agent_name = agent_path.name
    if not app_name:
        app_name = agent_name

    # Find eval directory
    if eval_dir:
        eval_path = Path(eval_dir).resolve()
    else:
        eval_path = _find_eval_dir(agent_path)
        if not eval_path:
            console.print(f"\n  [red]Error:[/] No eval/ directory found near {agent_path}")
            console.print(f"  [dim]Run `uv run agent-eval init` first to scaffold one.[/]")
            sys.exit(1)

    # Discover eval files dynamically
    from agent_eval.core.config import find_eval_files
    discovered = find_eval_files(eval_path)

    # Validate simulate prerequisites
    if run_simulate:
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

    # Validate interact prerequisites
    if run_interact:
        if not questions_file:
            if discovered["golden_data"]:
                questions_file = str(discovered["golden_data"][0])
            else:
                console.print(f"\n  [yellow]Warning:[/] No golden dataset found in {eval_path / 'eval_data'}")
                console.print(f"  [dim]Skipping interact phase. Add .json files to eval/eval_data/ or use --questions-file.[/]")
                run_interact = False
        elif not Path(questions_file).exists():
            console.print(f"\n  [red]Error:[/] Questions file not found: {questions_file}")
            sys.exit(1)

        # Check if agent is reachable before committing to interact phase
        if run_interact:
            import urllib.request
            from rich.prompt import Prompt

            def _check_url(url):
                try:
                    urllib.request.urlopen(url, timeout=3)
                    return True
                except Exception:
                    return False

            if not _check_url(base_url):
                console.print(f"\n  [yellow]Warning:[/] Agent not reachable at {base_url}")
                alt = Prompt.ask(
                    "  Enter agent URL (or press Enter to skip interact)",
                    default="",
                ).strip()
                if alt and _check_url(alt):
                    base_url = alt
                    console.print(f"  [green]Connected to {base_url}[/]")
                elif alt:
                    console.print(f"  [yellow]Warning:[/] Agent not reachable at {alt} either. Skipping interact.")
                    run_interact = False
                else:
                    console.print(f"  [dim]Skipping interact phase.[/]")
                    run_interact = False

    # Metrics file for evaluation
    if run_evaluate:
        if discovered["metrics"]:
            metrics_file = discovered["metrics"][0]
        else:
            console.print(f"\n  [yellow]Warning:[/] No metrics files found in {eval_path / 'metrics'}")
            console.print(f"  [dim]Evaluation will be skipped. Add .json files to eval/metrics/ to enable it.[/]")
            run_evaluate = False

    # Final check after graceful fallbacks
    if not run_simulate and not run_interact:
        console.print("\n  [red]Error:[/] Nothing to do — both simulate and interact were skipped.")
        console.print(f"  [dim]Start your agent at {base_url} and try again, or create a golden dataset.[/]")
        sys.exit(1)

    # ── Build step list ────────────────────────────────────────────────────

    # Analyze requires evaluate to have run
    if run_analyze and not run_evaluate:
        run_analyze = False

    phases = []
    if run_simulate:
        phases.append("Simulate")
    if run_interact:
        phases.append("Interact")
    if run_evaluate:
        phases.append("Evaluate")
    if run_analyze:
        phases.append("Analyze")
    total_phases = len(phases)

    def _phase_header(phase_name: str, description: str) -> None:
        """Print a numbered phase header."""
        idx = phases.index(phase_name) + 1
        console.print()
        console.print(Rule(f"  Phase {idx}/{total_phases}: {phase_name}  ", style="bold cyan"))
        console.print(f"  [dim]{description}[/]")
        console.print()

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
        run_id = Prompt.ask("  Run ID", default=default_ts).strip().replace(" ", "-")

    # ── Overview ────────────────────────────────────────────────────────────

    overview_lines = [
        f"[bold]Agent:[/]      [cyan]{agent_name}[/]  [dim]({agent_path})[/]",
        f"[bold]Eval dir:[/]   {eval_path}",
        f"[bold]Run ID:[/]     [cyan]{run_id}[/]  [dim](results → eval/results/{run_id}/)[/]",
        f"[bold]Pipeline:[/]   {' → '.join(phases)}",
    ]
    if run_interact:
        overview_lines.append(f"[bold]Base URL:[/]   {base_url}")

    console.print(Panel(
        "\n".join(overview_lines),
        title="[bold]Run[/]",
        border_style="blue",
        padding=(1, 2),
    ))

    # ── Set up results directory ───────────────────────────────────────────

    results_dir = eval_path / "results"
    run_dir = results_dir / run_id
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    interaction_files = []

    # ── Phase: Simulate ────────────────────────────────────────────────────

    if run_simulate:
        from agent_eval.cli.commands.simulate import _count_scenarios
        from agent_eval.core.converters import AdkHistoryConverter, write_jsonl

        n_scenarios = _count_scenarios(scenarios_file)

        _phase_header("Simulate",
                      f"Running ADK User Sim with {n_scenarios} scenario{'s' if n_scenarios != 1 else ''}.\n"
                      "  Creates symlinks, clears history, runs the sim, and converts traces.")

        # Import the simulate internals — but we drive the steps ourselves
        # to avoid the nested "Step X/5" headers from simulate.py
        _simulate_ok = _run_simulate_phase(agent_name, agent_path, eval_path, raw_dir, debug=debug)

        if _simulate_ok:
            sim_output = raw_dir / "processed_interaction_sim.jsonl"
            if sim_output.exists():
                interaction_files.append(sim_output)
        else:
            if not run_interact:
                sys.exit(1)
            console.print(f"  [yellow]Continuing with interact only...[/]")

    # ── Phase: Interact ────────────────────────────────────────────────────

    if run_interact:
        _phase_header("Interact",
                      f"Sending queries from golden dataset to your agent at {base_url}.\n"
                      "  Make sure your agent is running before this step.")

        interact_output = _run_interact_phase(
            app_name, agent_path, questions_file, base_url,
            num_questions, skip_traces, raw_dir, str(results_dir),
            debug=debug,
        )

        if interact_output:
            interaction_files.append(interact_output)
        elif not interaction_files:
            console.print(f"\n  [red]Error:[/] No interaction files were produced.")
            sys.exit(1)

    # ── Phase: Evaluate ────────────────────────────────────────────────────

    if not interaction_files:
        console.print(f"\n  [red]Error:[/] No interaction files were produced. Nothing to evaluate.")
        sys.exit(1)

    if run_evaluate:
        _phase_header("Evaluate",
                      f"Running metrics on {len(interaction_files)} interaction file{'s' if len(interaction_files) != 1 else ''}.\n"
                      f"  Metrics: {metrics_file.name}")

        for f in interaction_files:
            console.print(f"    [dim]-[/] {f.name}")

        _run_evaluate_phase(interaction_files, metrics_file, run_dir, run_id, debug=debug)

    # ── Phase: Analyze ─────────────────────────────────────────────────────

    analysis_result = None
    if run_analyze:
        _phase_header("Analyze",
                      "Generating AI-powered analysis, comparison tables, and optimization log.")

        # Prompt for focus if not provided via CLI
        if not focus:
            from rich.prompt import Prompt
            console.print(Panel(
                "[bold]Do you want to highlight specific metrics?[/]\n\n"
                "Enter metric keywords to focus the analysis on (comma-separated).\n"
                "Matching metrics will be highlighted in the comparison table.\n\n"
                "Examples: [cyan]latency, cache[/] · [cyan]token, cost[/] · [cyan]tool, quality[/]\n\n"
                "[dim]Press Enter to skip — all metrics will be weighted equally.[/]",
                title="[bold]Analysis Focus[/]",
                border_style="blue",
                padding=(1, 2),
            ))
            focus_input = Prompt.ask("  Focus", default="").strip()
            if focus_input:
                focus = focus_input

        analysis_result = _run_analyze_phase(
            run_dir, agent_path, focus, skip_gemini, debug=debug,
        )

    # ── Done ────────────────────────────────────────────────────────────────

    cwd = Path.cwd()
    rel_run = os.path.relpath(run_dir, cwd)
    rel_agent = os.path.relpath(agent_path, cwd)

    console.print()
    completed = []
    if run_simulate and any("sim" in f.name for f in interaction_files):
        completed.append("Simulate")
    if run_interact and any("sim" not in f.name for f in interaction_files):
        completed.append("Interact")
    if run_evaluate:
        completed.append("Evaluate")
    if run_analyze and analysis_result:
        completed.append("Analyze")

    output_files = [f"  - {f.name}" for f in interaction_files]
    if run_evaluate:
        output_files.append("  - eval_summary.json")
    if analysis_result:
        output_files.append("  - gemini_analysis.md")
        output_files.append("  - question_answer_log.md")
        if analysis_result.get("optimization_log_path"):
            rel_log = os.path.relpath(analysis_result["optimization_log_path"], run_dir)
            output_files.append(f"  - {rel_log}")

    comparison_info = ""
    if analysis_result and analysis_result.get("comparison_data"):
        baseline_id = analysis_result["comparison_data"].get("baseline_id", "previous")
        comparison_info = f"\n[bold]Compared to:[/]  {baseline_id}\n"

    console.print(Panel(
        f"[bold green]Pipeline complete![/]  ({' + '.join(completed)})\n"
        f"{comparison_info}\n"
        f"[bold]Results:[/]  {rel_run}/\n"
        f"[bold]Files:[/]\n"
        + "\n".join(output_files),
        title="[bold]Done[/]",
        border_style="green",
        padding=(1, 2),
    ))

    if not run_evaluate:
        rel_files = " \\\n  ".join(f"--interaction-file {os.path.relpath(f, cwd)}" for f in interaction_files)
        rel_metrics = os.path.relpath(metrics_file, cwd)
        console.print()
        console.print("[bold]Next step — run evaluation:[/]")
        console.print()
        console.print(f"uv run agent-eval evaluate \\")
        console.print(f"  {rel_files} \\")
        console.print(f"  --metrics-files {rel_metrics} \\")
        console.print(f"  --results-dir {rel_run}")
        console.print()
    elif not run_analyze:
        console.print()
        console.print("[bold]Next step — generate analysis:[/]")
        console.print()
        console.print(f"uv run agent-eval analyze \\")
        console.print(f"  --results-dir {rel_run} \\")
        console.print(f"  --agent-dir {rel_agent}")
        console.print()

    # ── Phase 5: Dashboard (optional) ──────────────────────────────────────

    if run_evaluate and run_dashboard is not False:
        _offer_dashboard(results_dir, run_dashboard)


def _offer_dashboard(results_dir: Path, run_dashboard: bool | None) -> None:
    """Offer to launch the interactive dashboard after the pipeline completes."""
    try:
        import gradio  # noqa: F401
    except ImportError:
        if run_dashboard is True:
            # User explicitly asked for --dashboard but gradio is missing
            console.print()
            console.print("  [yellow]Dashboard requires optional dependencies.[/]")
            console.print("  Install them with:  [cyan]pip install agent-eval\\[dashboard][/]")
            console.print()
        else:
            # Not installed and not explicitly requested — just show a tip
            console.print("  [dim]Tip: Install dashboard extras for interactive visualization:[/]")
            console.print("    [cyan]pip install agent-eval\\[dashboard][/]")
            console.print()
        return

    # Gradio is available — decide whether to launch
    if run_dashboard is True:
        should_launch = True
    elif run_dashboard is False:
        return
    else:
        # run_dashboard is None — prompt the user
        from rich.prompt import Confirm
        console.print()
        should_launch = Confirm.ask(
            "  Launch the interactive dashboard to compare all runs?",
            default=False,
        )

    if should_launch:
        console.print()
        console.print(Rule("  Phase 5: Dashboard  ", style="bold cyan"))
        console.print("  [dim]Starting interactive dashboard with all evaluation runs.[/]")
        console.print()

        from agent_eval.dashboard.app import launch
        launch(str(results_dir), port=7860, share=False)


# ── Phase implementations ─────────────────────────────────────────────────
# Extracted to keep the main function readable. These do NOT use simulate.py's
# _step_* functions directly (which print their own "Step X/5" headers) —
# instead they call the underlying logic with consistent formatting.


def _run_simulate_phase(agent_name: str, agent_path: Path, eval_path: Path, raw_dir: Path, debug: bool = False) -> bool:
    """Run the simulate workflow. Returns True on success."""
    import shutil
    import subprocess

    from agent_eval.cli.commands.simulate import _clean_env, _ADK_REQUIRED_FILES, _DEFAULT_EVAL_CONFIG
    from agent_eval.core.converters import AdkHistoryConverter, write_jsonl

    project_root = agent_path.parent
    scenarios_dir = eval_path / "scenarios"

    # 1. Symlink scenario files
    console.print("  [bold]1.[/] Symlinking scenario files into agent directory...")
    for filename in _ADK_REQUIRED_FILES:
        target = agent_path / filename
        source = scenarios_dir / filename

        if filename == "eval_config.json" and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(json.dumps(_DEFAULT_EVAL_CONFIG, indent=2) + "\n")
            console.print(f"     [green]+[/] Created default {filename}")

        if not source.exists():
            console.print(f"     [yellow]![/] Skipping {filename} — not found")
            continue

        if target.is_symlink() or target.exists():
            target.unlink()
        rel_path = os.path.relpath(source, agent_path)
        target.symlink_to(rel_path)
        console.print(f"     [green]+[/] {agent_path.name}/{filename} → {rel_path}")

    # 2. Clear eval history
    console.print("  [bold]2.[/] Clearing previous eval history...")
    eval_history = agent_path / ".adk" / "eval_history"
    if eval_history.exists():
        n_files = sum(1 for _ in eval_history.rglob("*") if _.is_file())
        shutil.rmtree(eval_history)
        console.print(f"     [green]+[/] Cleared {n_files} file{'s' if n_files != 1 else ''}")
    else:
        console.print(f"     [dim]Nothing to clear.[/]")

    # 3. Create eval set
    console.print("  [bold]3.[/] Creating fresh eval set...")
    eval_set_name = "eval_set"

    # Remove existing eval_set
    evalset_file = agent_path / f"{eval_set_name}.evalset.json"
    if evalset_file.exists():
        evalset_file.unlink()
    eval_set_dir = agent_path / ".adk" / "eval_sets" / eval_set_name
    if eval_set_dir.exists():
        shutil.rmtree(eval_set_dir)

    _UV_RUN_ADK = ["uv", "run", "--with", "google-adk[eval]"]

    result = subprocess.run(
        [*_UV_RUN_ADK, "adk", "eval_set", "create", agent_name, eval_set_name],
        cwd=str(project_root), env=_clean_env(project_root),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"     [red]Failed to create eval_set[/]")
        if result.stderr.strip():
            console.print(f"     [red]{result.stderr.strip()}[/]")
        return False
    console.print(f"     [green]+[/] Created eval_set")

    # Add eval cases
    scenarios_file = agent_path / "conversation_scenarios.json"
    session_file = agent_path / "session_input.json"

    result = subprocess.run(
        [
            *_UV_RUN_ADK, "adk", "eval_set", "add_eval_case",
            agent_name, eval_set_name,
            "--scenarios_file", str(scenarios_file),
            "--session_input_file", str(session_file),
        ],
        cwd=str(project_root), env=_clean_env(project_root),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"     [red]Failed to add eval cases[/]")
        if result.stderr.strip():
            console.print(f"     [red]{result.stderr.strip()}[/]")
        return False
    console.print(f"     [green]+[/] Loaded scenarios into eval set")

    # 4. Run ADK User Sim
    console.print("  [bold]4.[/] Running ADK User Sim...")
    console.print(f"     [dim]An LLM simulates users following your scenario scripts.[/]")
    console.print(f"     [dim]This may take a few minutes.[/]")
    console.print()

    eval_config = agent_path / "eval_config.json"
    adk_cmd = [*_UV_RUN_ADK, "adk", "eval", agent_name]
    if eval_config.exists():
        adk_cmd += ["--config_file_path", str(eval_config)]
    adk_cmd.append(eval_set_name)

    # In debug mode, stream ADK output so the user can see everything.
    # In normal mode, capture it — ADK is extremely verbose (EXPERIMENTAL
    # warnings, plugin registrations, every LLM request/response).
    if debug:
        console.print("     [dim]Debug: streaming ADK output...[/]")
        result = subprocess.run(
            adk_cmd, cwd=str(project_root), env=_clean_env(project_root),
            text=True,
        )
    else:
        with console.status("     [bold blue]Simulating conversations...[/]", spinner="dots"):
            result = subprocess.run(
                adk_cmd, cwd=str(project_root), env=_clean_env(project_root),
                capture_output=True, text=True,
            )

    eval_history = agent_path / ".adk" / "eval_history"
    has_traces = eval_history.exists() and any(eval_history.rglob("*.json"))

    if result.returncode != 0 and not has_traces:
        console.print(f"     [red]ADK eval failed — no traces generated.[/]")
        if result.stderr.strip():
            # Show last few lines of error for debugging
            last_lines = result.stderr.strip().split("\n")[-3:]
            for line in last_lines:
                console.print(f"     [dim]{line}[/]")
        return False
    if result.returncode != 0 and has_traces:
        console.print(f"     [yellow]![/] ADK eval finished with warnings, but traces were captured.")
        console.print(f"     [dim]Warnings are from ADK's built-in scoring, not the simulation.[/]")

    if has_traces:
        n_traces = sum(1 for _ in eval_history.rglob("*.json"))
        console.print(f"     [green]+[/] Simulation complete — {n_traces} trace file{'s' if n_traces != 1 else ''} generated")

    # 5. Convert traces
    console.print()
    console.print("  [bold]5.[/] Converting traces to evaluation format...")
    try:
        converter = AdkHistoryConverter(str(agent_path), None)
        records = converter.run()
        if not records:
            console.print(f"     [yellow]![/] No traces found to convert.")
            return False

        sim_output = raw_dir / "processed_interaction_sim.jsonl"
        write_jsonl(records, str(sim_output))
        console.print(f"     [green]+[/] Converted [cyan]{len(records)}[/] simulation interaction{'s' if len(records) != 1 else ''}")
        return True

    except Exception as e:
        console.print(f"     [red]Error converting traces:[/] {e}")
        return False


def _run_interact_phase(
    app_name: str, agent_path: Path, questions_file: str,
    base_url: str, num_questions: int, skip_traces: bool,
    raw_dir: Path, results_dir: str, debug: bool = False,
) -> Path | None:
    """Run the interact workflow. Returns the output path on success, None on failure."""
    import asyncio
    from agent_eval.core.interactions import InteractionRunner
    from agent_eval.core.processor import InteractionProcessor
    from agent_eval.core.converters import write_jsonl

    config = {
        "app_name": app_name,
        "questions_file": questions_file,
        "base_url": base_url,
        "user_id": "eval_user",
        "num_questions": num_questions,
        "results_dir": results_dir,
        "runs": 1,
        "metadata_filters": None,
        "state_variables": None,
        "skip_traces": skip_traces,
        "user": os.environ.get("USER"),
    }

    runner = InteractionRunner(config)

    try:
        raw_df = asyncio.run(runner.run())
    except Exception as e:
        console.print(f"    [red]Error during interactions:[/] {e}")
        console.print(f"    [dim]Make sure your agent is running at {base_url}[/]")
        return None

    if raw_df is None or raw_df.empty:
        console.print(f"    [yellow]![/] No interactions were captured.")
        return None

    console.print(f"    [green]+[/] Captured [cyan]{len(raw_df)}[/] interaction{'s' if len(raw_df) != 1 else ''}")
    console.print(f"    Processing and enriching traces...")

    processor = InteractionProcessor(config)
    try:
        enriched_df = asyncio.run(processor.process(raw_df))
    except Exception as e:
        console.print(f"    [red]Error during processing:[/] {e}")
        return None

    interact_output = raw_dir / f"processed_interaction_{app_name}.jsonl"

    records = enriched_df.to_dict(orient="records")
    for record in records:
        for key, value in record.items():
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, (dict, list)):
                        record[key] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

    write_jsonl(records, str(interact_output))
    console.print(f"    [green]+[/] Saved [cyan]{len(records)}[/] enriched interaction{'s' if len(records) != 1 else ''}")
    return interact_output


def _run_evaluate_phase(
    interaction_files: list[Path], metrics_file: Path,
    run_dir: Path, run_id: str, debug: bool = False,
) -> None:
    """Run the evaluate workflow."""
    from agent_eval.core.evaluator import Evaluator
    from agent_eval.cli.commands.evaluate import _display_metrics_summary

    eval_config = {
        "metric_filters": None,
        "input_label": "run",
        "test_description": f"Combined evaluation run: {run_id}",
    }

    evaluator = Evaluator(eval_config)
    try:
        evaluator.evaluate(
            interaction_files=interaction_files,
            metrics_files=[str(metrics_file)],
            results_dir=run_dir,
        )
        _display_metrics_summary(str(run_dir))

    except Exception as e:
        import traceback
        traceback.print_exc()
        console.print(f"\n  [red]Evaluation error:[/] {e}")
        console.print(f"  [dim]Interaction files were saved. You can re-run evaluate manually.[/]")


def _run_analyze_phase(
    run_dir: Path, agent_path: Path,
    focus: str = None, skip_gemini: bool = False, debug: bool = False,
) -> dict:
    """Run the analyze workflow. Returns the analysis result dict or None."""
    from agent_eval.core.analyzer import Analyzer
    from agent_eval.cli.commands.analyze import _display_metrics_table, _display_analysis

    config = {
        "results_dir": str(run_dir),
        "agent_dir": str(agent_path),
        "focus": focus,
        "skip_gemini": skip_gemini,
        "model": "gemini-3.1-pro-preview",
    }

    analyzer = Analyzer(config)

    try:
        analysis_result = analyzer.run()
    except Exception as e:
        console.print(f"\n  [red]Analysis error:[/] {e}")
        console.print(f"  [dim]Evaluation results were saved. You can run analyze manually.[/]")
        return None

    # Display metrics table
    if analysis_result and analysis_result.get("current_summary"):
        _display_metrics_table(
            analysis_result["current_summary"],
            analysis_result.get("comparison_data"),
            focus,
        )

    # Display AI analysis
    _display_analysis(str(run_dir))

    return analysis_result
