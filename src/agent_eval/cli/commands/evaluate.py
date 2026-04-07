"""agent-eval evaluate — run metrics on processed interaction data."""

import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_eval.core.evaluator import Evaluator

console = Console()


def _display_metrics_summary(results_dir: str) -> None:
    """Read eval_summary.json and display a metrics overview table."""
    summary_path = Path(results_dir) / "eval_summary.json"
    if not summary_path.exists():
        return

    try:
        data = json.loads(summary_path.read_text())
        overall = data.get("overall_summary", {})
    except (json.JSONDecodeError, KeyError):
        return

    # ── LLM-as-Judge metrics table ─────────────────────────────────────
    llm_metrics = overall.get("llm_based_metrics", {})
    if llm_metrics:
        table = Table(title="LLM-as-Judge Metrics", border_style="blue", padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Range", justify="center", style="dim")
        table.add_column("", justify="center")

        for name, info in llm_metrics.items():
            avg = info.get("average", 0)
            sr = info.get("score_range", {})
            max_val = sr.get("max", 5)
            min_val = sr.get("min", 0)
            range_str = f"{min_val}–{max_val}"

            # Color based on how good the score is relative to range
            ratio = (avg - min_val) / (max_val - min_val) if max_val > min_val else 0
            if ratio >= 0.7:
                color = "green"
                indicator = "OK"
            elif ratio >= 0.4:
                color = "yellow"
                indicator = "Review"
            else:
                color = "red"
                indicator = "Check mapping"

            table.add_row(name, f"[{color}]{avg:.1f}[/]", range_str, f"[{color}]{indicator}[/]")

        # Show metrics that failed all retries
        failed = overall.get("failed_metrics", [])
        for name in failed:
            table.add_row(name, "[red]FAILED[/]", "—", "[red]Retry later[/]")

        console.print()
        console.print(table)

        if failed:
            console.print(
                f"  [yellow]Warning:[/] {len(failed)} metric(s) failed due to API rate limits."
            )
            console.print(
                "  [dim]Try again later or reduce the number of metrics/eval cases.[/]"
            )

    # ── Key deterministic metrics ──────────────────────────────────────
    det = overall.get("deterministic_metrics", {})
    if det:
        table = Table(title="Key Deterministic Metrics", border_style="blue", padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Avg Value", justify="right")

        # Pick the most useful metrics to show
        highlights = [
            ("Total tokens", "token_usage.total_tokens", "{:.0f}"),
            ("Prompt tokens", "token_usage.prompt_tokens", "{:.0f}"),
            ("Completion tokens", "token_usage.completion_tokens", "{:.0f}"),
            ("Estimated cost", "token_usage.estimated_cost_usd", "${:.4f}"),
            ("Total latency", "latency_metrics.total_latency_seconds", "{:.2f}s"),
            ("LLM latency", "latency_metrics.llm_latency_seconds", "{:.2f}s"),
            ("Cache hit rate", "cache_efficiency.cache_hit_rate", "{:.0%}"),
            ("Tool calls", "tool_utilization.total_tool_calls", "{:.0f}"),
            ("Tool success rate", "tool_success_rate.tool_success_rate", "{:.0%}"),
        ]

        for label, key, fmt in highlights:
            val = det.get(key)
            if val is not None:
                table.add_row(label, fmt.format(val))

        console.print()
        console.print(table)


@click.command()
@click.option("--interaction-file", required=True, multiple=True, help="Path(s) to processed interaction JSONL or CSV. Can be specified multiple times.")
@click.option("--metrics-files", required=True, multiple=True, help="Paths to metric definition JSONs.")
@click.option("--results-dir", required=True, help="Directory for outputs.")
@click.option("--input-label", default="manual", help="Label for this run (e.g. 'baseline').")
@click.option("--test-description", default="Automated evaluation", help="Description of this evaluation run.")
@click.option("--filter", "metric_filter", multiple=True, help="Metric filters (key:val).")
@click.option("--debug", is_flag=True, help="Show detailed logs from Vertex AI SDK and other services.")
def evaluate(interaction_file, metrics_files, results_dir, input_label, test_description, metric_filter, debug):
    """Run evaluation metrics on processed interaction data."""
    from agent_eval.core.evaluator import configure_logging
    configure_logging(debug=debug)

    console.print("\n[bold blue]Running Evaluation[/]")
    if len(interaction_file) > 1:
        console.print(f"  [dim]Combining {len(interaction_file)} interaction files[/]")
        for f in interaction_file:
            console.print(f"    [dim]- {f}[/]")

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
            interaction_files=[Path(f) for f in interaction_file],
            metrics_files=list(metrics_files),
            results_dir=Path(results_dir),
        )

        cwd = Path.cwd()
        rel_results = os.path.relpath(results_dir, cwd)
        rel_metrics = os.path.relpath(metrics_files[0], cwd) if metrics_files else "<metrics.json>"

        # ── Display metrics overview ───────────────────────────────────
        _display_metrics_summary(results_dir)

        console.print()
        console.print(Panel(
            f"[bold green]Evaluation complete![/]\n\n"
            f"[bold]Results:[/]  {rel_results}/\n\n"
            "[bold]Deep dive into the files:[/]\n"
            f"  eval_summary.json        — Full aggregated scores\n"
            f"  question_answer_log.md   — Per-question breakdown with scores\n\n"
            "[bold]Scores look wrong?[/] Low scores often mean a [bold]metric mapping[/]\n"
            "issue, not an agent problem. Each metric's `dataset_mapping`\n"
            f"controls which trace fields the LLM judge sees. Edit:\n"
            f"  {rel_metrics}\n\n"
            "[dim]See docs/reference.md > Custom Metrics for mapping options.[/]",
            title="[bold]Done[/]",
            border_style="green",
            padding=(1, 2),
        ))

        console.print()
        console.print("[bold]Next step — copy and paste:[/]")
        console.print()
        console.print(f"uv run agent-eval analyze \\")
        console.print(f"  --results-dir {rel_results}")
        console.print()

    except Exception as e:
        import traceback
        traceback.print_exc()
        console.print(f"[bold red]Error during evaluation:[/] {e}")
        sys.exit(1)
