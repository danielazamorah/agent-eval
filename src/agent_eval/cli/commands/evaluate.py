"""agent-eval evaluate — run metrics on processed interaction data."""

import sys
from pathlib import Path

import click
from rich.console import Console

from agent_eval.core.evaluator import Evaluator

console = Console()


@click.command()
@click.option("--interaction-file", required=True, help="Path to processed interaction JSONL or CSV.")
@click.option("--metrics-files", required=True, multiple=True, help="Paths to metric definition JSONs.")
@click.option("--results-dir", required=True, help="Directory for outputs.")
@click.option("--input-label", default="manual", help="Label for this run (e.g. 'baseline').")
@click.option("--test-description", default="Automated evaluation", help="Description of this evaluation run.")
@click.option("--filter", "metric_filter", multiple=True, help="Metric filters (key:val).")
def evaluate(interaction_file, metrics_files, results_dir, input_label, test_description, metric_filter):
    """Run evaluation metrics on processed interaction data."""
    console.print("\n[bold blue]Running Evaluation[/]")

    config = {
        "metric_filters": None,
        "input_label": input_label,
        "test_description": test_description,
    }

    if metric_filter:
        filters = {}
        for f in metric_filter:
            k, v = f.split(":", 1)
            filters[k] = v.split(",")
        config["metric_filters"] = filters

    evaluator = Evaluator(config)

    try:
        evaluator.evaluate(
            interaction_file=Path(interaction_file),
            metrics_files=list(metrics_files),
            results_dir=Path(results_dir),
        )
        console.print(f"\n[bold green]Evaluation complete.[/]")
        console.print(f"\nTo analyze results, run:")
        console.print(f"  agent-eval analyze --results-dir {results_dir}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        console.print(f"[bold red]Error during evaluation:[/] {e}")
        sys.exit(1)
