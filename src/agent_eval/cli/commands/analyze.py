"""agent-eval analyze — generate reports and AI-powered root cause analysis."""

import click
from rich.console import Console

from agent_eval.core.analyzer import Analyzer

console = Console()


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
    analyzer.run()
