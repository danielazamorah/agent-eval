"""agent-eval analyze — generate reports and AI-powered root cause analysis."""

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

from agent_eval.core.analyzer import Analyzer

console = Console()


def _display_analysis(results_dir: str) -> None:
    """Read and display the gemini_analysis.md in a formatted way."""
    analysis_path = Path(results_dir) / "gemini_analysis.md"
    if not analysis_path.exists():
        return

    content = analysis_path.read_text().strip()
    if not content:
        return

    console.print()
    console.print(Rule("  AI Analysis  ", style="bold magenta"))
    console.print()
    console.print(Markdown(content))
    console.print()
    console.print(Rule(style="magenta"))


@click.command()
@click.option("--results-dir", required=True, help="Directory containing evaluation results.")
@click.option("--agent-dir", default=None, help="Path to agent directory (for source code context).")
@click.option("--strategy-file", default=None, help="Path to optimization strategy Markdown file.")
@click.option("--report-audience", default=None, help="Target audience for the analysis report.")
@click.option("--report-tone", default=None, help="Tone of the analysis report.")
@click.option("--report-length", default=None, help="Length of the analysis report.")
@click.option("--model", default="gemini-3-pro-preview", help="Gemini model for analysis.")
@click.option("--location", default=None, help="Vertex AI location (e.g. us-central1, global).")
@click.option("--skip-gemini", is_flag=True, help="Skip AI-powered analysis.")
@click.option("--gcs-bucket", default=None, help="GCS bucket for upload.")
def analyze(results_dir, agent_dir, strategy_file, report_audience, report_tone,
            report_length, model, location, skip_gemini, gcs_bucket):
    """Analyze evaluation results and generate reports."""
    console.print("\n[bold blue]Analyzing Results[/]")

    config = {
        "results_dir": results_dir,
        "agent_dir": agent_dir,
        "model": model,
        "location": location,
        "skip_gemini": skip_gemini,
        "gcs_bucket": gcs_bucket,
        "strategy_file": strategy_file,
        "report_audience": report_audience,
        "report_tone": report_tone,
        "report_length": report_length,
    }

    analyzer = Analyzer(config)

    try:
        analyzer.run()
    except Exception as e:
        console.print(f"\n[bold red]Error during analysis:[/] {e}")
        sys.exit(1)

    # ── Display the analysis ───────────────────────────────────────────
    _display_analysis(results_dir)

    # ── Done ───────────────────────────────────────────────────────────
    cwd = Path.cwd()
    rel_results = os.path.relpath(results_dir, cwd)

    console.print(Panel(
        f"[bold green]Analysis complete![/]\n\n"
        f"[bold]Saved to:[/]  {rel_results}/gemini_analysis.md\n\n"
        "[bold]All result files:[/]\n"
        f"  {rel_results}/eval_summary.json         — Aggregated metrics\n"
        f"  {rel_results}/gemini_analysis.md         — AI diagnosis (shown above)\n"
        f"  {rel_results}/question_answer_log.md     — Per-question breakdown",
        title="[bold]Done[/]",
        border_style="green",
        padding=(1, 2),
    ))
