"""agent-eval interact — run interactions against a live agent."""

import asyncio
import json
import os
import sys
from datetime import datetime

import click
from rich.console import Console

from agent_eval.core.interactions import InteractionRunner
from agent_eval.core.processor import InteractionProcessor
from agent_eval.core.converters import write_jsonl

console = Console()


@click.command()
@click.option("--app-name", required=True, help="Name of the agent application.")
@click.option("--questions-file", required=True, help="Path to the Golden Dataset JSON.")
@click.option("--base-url", default="http://localhost:8080", help="Agent API URL.")
@click.option("--user-id", default="eval_user", help="Session User ID.")
@click.option("--results-dir", default="results", help="Directory for outputs.")
@click.option("--num-questions", type=int, default=-1, help="Limit number of questions (-1 = all).")
@click.option("--runs", type=int, default=1, help="Runs per question.")
@click.option("--skip-traces", is_flag=True, help="Skip trace retrieval (faster).")
@click.option("--filter", "metadata_filters", multiple=True, help="Metadata filters (key:val).")
@click.option("--state", "state_variables", multiple=True, help="State variables (key:val).")
@click.option("--user", default=os.environ.get("USER"), help="Operator username.")
def interact(app_name, questions_file, base_url, user_id, results_dir,
             num_questions, runs, skip_traces, metadata_filters, state_variables, user):
    """Run interactions against a live agent and process logs."""
    config = {
        "app_name": app_name,
        "questions_file": questions_file,
        "base_url": base_url,
        "user_id": user_id,
        "num_questions": num_questions,
        "results_dir": results_dir,
        "runs": runs,
        "metadata_filters": list(metadata_filters) if metadata_filters else None,
        "state_variables": list(state_variables) if state_variables else None,
        "skip_traces": skip_traces,
        "user": user,
    }

    console.print("\n[bold blue]Step 1:[/] Running Interactions")
    runner = InteractionRunner(config)

    try:
        raw_df = asyncio.run(runner.run())
    except Exception as e:
        console.print(f"[bold red]Error during interaction run:[/] {e}")
        sys.exit(1)

    if raw_df.empty:
        console.print("[yellow]No interactions were run.[/]")
        sys.exit(0)

    console.print("\n[bold blue]Step 2:[/] Processing & Enriching Logs")
    processor = InteractionProcessor(config)
    try:
        enriched_df = asyncio.run(processor.process(raw_df))
    except Exception as e:
        console.print(f"[bold red]Error during processing:[/] {e}")
        sys.exit(1)

    # Save output as JSONL in datetime-stamped folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(results_dir, timestamp)
    raw_dir = os.path.join(run_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    output_path = os.path.join(raw_dir, f"processed_interaction_{app_name}.jsonl")

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

    write_jsonl(records, output_path)
    console.print(f"\n[bold green]SUCCESS:[/] Enriched data saved to: {output_path}")
    console.print(f"Run folder: {run_dir}")
    console.print(f"\nTo evaluate, run:")
    console.print(f"  agent-eval evaluate --interaction-file {output_path} --metrics-files <metrics.json> --results-dir {run_dir}")
