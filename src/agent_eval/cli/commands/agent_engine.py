"""agent-eval agent-engine — streamlined Path A runner for Agent Engine deployments.

Wraps Vertex AI's ``client.evals.create_evaluation_run`` for agents already
deployed to Reasoning Engines (Agent Starter Pack ``make backend`` flow).
This is the **streamlined** path from the docs (``evaluation-agents-client``):
inference + scoring + GCS upload happen in a single managed call.

When to use this command instead of ``agent-eval evaluate``:

- Your agent is deployed to Agent Engine (env ``AGENT_ENGINE_RESOURCE_NAME``
  is set, or ``deployment_metadata.json`` contains a real resource name).
- You want managed inference (no local FastAPI server, no traces to capture
  yourself) — Vertex calls the agent for you.
- You want a single ``dashboard_url`` to share with stakeholders.

Per the SDK-aligned plan §4.4: the dataset only needs ``prompt`` (and
optionally ``session_inputs``); no ``reference`` is required because the
managed adaptive rubrics judge quality without it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_resource_name(explicit: Optional[str], cwd: Path) -> Optional[str]:
    """Resolve the Agent Engine resource name from CLI arg, env, or metadata file."""
    if explicit:
        return explicit
    env_value = os.getenv("AGENT_ENGINE_RESOURCE_NAME")
    if env_value and env_value not in {"None", ""}:
        return env_value
    from agent_eval.core.path_detector import detect_execution_path

    detection = detect_execution_path(cwd)
    if detection.path == "A" and detection.agent_engine_resource:
        return detection.agent_engine_resource
    return None


def _resolve_metrics_path(metrics_path: Path) -> Path:
    """Resolve the metrics file with backward-compat fallback to legacy layouts.

    Tries the explicit/default path first, then asks ``path_resolver`` to scan
    for the canonical ``tests/eval/metrics/`` layout or any legacy ``eval/``
    folder so projects scaffolded by older versions of ``init`` keep working.
    """
    if metrics_path.exists():
        return metrics_path

    from agent_eval.core.path_resolver import find_metrics_path

    discovered = find_metrics_path(Path.cwd())
    if discovered is not None:
        return discovered
    return metrics_path


def _load_metric_definitions(metrics_path: Path) -> Dict[str, Dict[str, Any]]:
    """Read metric definitions JSON, returning {} if file is missing."""
    resolved = _resolve_metrics_path(metrics_path)
    if not resolved.exists():
        return {}
    if resolved != metrics_path:
        console.print(f"  [dim]Metrics: [/] [cyan]{resolved}[/] [dim](resolved via fallback)[/]")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        console.print(f"  [yellow]![/] Could not read {resolved}: {exc}")
        return {}
    if isinstance(data, dict) and "metrics" in data and isinstance(data["metrics"], dict):
        return data["metrics"]
    return data


def _build_evaluation_run_metrics(
    metric_definitions: Dict[str, Dict[str, Any]],
) -> List[Any]:
    """Convert the scaffolded metric schema into EvaluationRunMetric objects.

    The schema produced by ``init`` uses ``metric_type`` + ``is_managed`` /
    ``managed_metric_name`` rather than the ``kind``-based unified schema,
    so we translate inline. Custom (non-managed) LLM metrics are skipped
    here with a warning — Path A only ships managed-rubric scoring today.
    """
    from vertexai._genai import types as vt

    run_metrics: List[Any] = []
    for name, spec in metric_definitions.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("is_managed") and spec.get("managed_metric_name"):
            managed_name = str(spec["managed_metric_name"]).upper()
            try:
                rubric = getattr(vt.RubricMetric, managed_name)
                run_metrics.append(vt.EvaluationRunMetric(metric=rubric.name))
                continue
            except AttributeError:
                console.print(
                    f"  [yellow]![/] Skipping [cyan]{name}[/]: managed rubric "
                    f"'{managed_name}' not found in this SDK version."
                )
                continue
        console.print(
            f"  [yellow]![/] Skipping [cyan]{name}[/]: "
            f"custom LLM metrics aren't yet supported on Path A. "
            f"Run [cyan]agent-eval evaluate[/] to score this one locally."
        )
    return run_metrics


def _sanitize_inference_responses(inference_dataset: Any) -> Any:
    """Coerce NaN string-typed cells to empty strings.

    When the dataset contains rows with mixed schemas (e.g. some have
    ``reference`` and others don't), pandas fills the missing cells with
    ``NaN``. Vertex AI's ``CandidateResponse`` pydantic validator then
    rejects those NaN values since they aren't strings, causing
    ``create_evaluation_run`` to fail. We swap NaN → "" in the columns the
    SDK feeds into string fields.
    """
    import math

    df = getattr(inference_dataset, "eval_dataset_df", None)
    if df is None or df.empty:
        return inference_dataset

    string_columns = ("reference", "id", "response", "system_instruction")
    fixed = 0
    for col in string_columns:
        if col not in df.columns:
            continue

        def _coerce(val: Any) -> Any:
            nonlocal fixed
            if val is None:
                fixed += 1
                return ""
            if isinstance(val, float) and math.isnan(val):
                fixed += 1
                return ""
            return val

        df[col] = df[col].apply(_coerce)

    inference_dataset.eval_dataset_df = df
    if fixed:
        console.print(
            f"  [dim]Coerced {fixed} NaN/None cell(s) → \"\" so the SDK validator accepts them.[/]"
        )
    return inference_dataset


def _default_destination(project: str) -> str:
    """Default GCS destination for evaluation results when --dest is not given."""
    bucket = os.getenv("AGENT_EVAL_DEST_BUCKET") or f"{project}-agent-eval"
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"gs://{bucket}/agent-eval/{timestamp}/"


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

@click.command(name="agent-engine")
@click.option(
    "--dataset",
    "dataset_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("tests/eval/dataset.jsonl"),
    show_default=True,
    help="Unified dataset JSONL with prompt/session_inputs rows.",
)
@click.option(
    "--metrics",
    "metrics_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=Path("tests/eval/metrics/metric_definitions.json"),
    show_default=True,
    help="Metric definitions file (unified schema).",
)
@click.option(
    "--resource-name",
    default=None,
    help="Agent Engine resource name. Defaults to AGENT_ENGINE_RESOURCE_NAME or auto-detection.",
)
@click.option(
    "--dest",
    default=None,
    help="GCS destination URI for results. Defaults to gs://<project>-agent-eval/<timestamp>/",
)
@click.option(
    "--project",
    default=None,
    help="GCP project ID. Defaults to GOOGLE_CLOUD_PROJECT.",
)
@click.option(
    "--location",
    default=None,
    help="GCP location. Defaults to GOOGLE_CLOUD_LOCATION or us-central1.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Show full SDK logs (otherwise suppressed for clean output).",
)
def agent_engine(
    dataset_path: Path,
    metrics_path: Path,
    resource_name: Optional[str],
    dest: Optional[str],
    project: Optional[str],
    location: Optional[str],
    debug: bool,
) -> None:
    """Run a streamlined evaluation against an Agent Engine deployment.

    Uses ``client.evals.create_evaluation_run()`` — Vertex handles inference,
    scoring, and GCS upload in one managed call. Prints the dashboard URL
    when complete.
    """
    from agent_eval.cli.main import _display_banner
    _display_banner()

    if not debug:
        import logging
        for noisy in ("google", "vertexai", "google.auth", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"

    if not project:
        console.print("  [red]GOOGLE_CLOUD_PROJECT is not set.[/] Run `agent-eval init` first.")
        raise click.Abort()

    resolved = _resolve_resource_name(resource_name, Path.cwd())
    if not resolved:
        console.print(
            "  [red]No Agent Engine resource name found.[/]\n"
            "  [dim]Set AGENT_ENGINE_RESOURCE_NAME, pass --resource-name, or deploy via[/]\n"
            "  [dim]  uvx agent-starter-pack enhance --adk -d agent_engine && make backend[/]"
        )
        raise click.Abort()

    console.print()
    console.print("  [bold]Path A — Agent Engine (streamlined)[/]")
    console.print(f"  [dim]Resource:[/] [cyan]{resolved}[/]")
    console.print(f"  [dim]Dataset: [/] [cyan]{dataset_path}[/]")
    console.print(f"  [dim]Project: [/] [cyan]{project}[/] [dim](location: {location})[/]")

    # Lazy imports — keep CLI startup snappy.
    try:
        import pandas as pd
        from vertexai import Client
        from vertexai._genai import types as vt
    except ImportError as exc:
        console.print(f"  [red]Missing dependency:[/] {exc}")
        raise click.Abort()

    dataset = pd.read_json(dataset_path, lines=True)
    if "prompt" not in dataset.columns:
        console.print(
            f"  [red]Dataset {dataset_path} is missing the required `prompt` column.[/]"
        )
        raise click.Abort()

    metric_defs = _load_metric_definitions(metrics_path)
    run_metrics = _build_evaluation_run_metrics(metric_defs)

    if not run_metrics:
        # Fall back to the docs-recommended starter set so the command
        # always does something useful even before the user defines metrics.
        console.print(
            "  [dim]No metric_definitions.json found — falling back to GENERAL_QUALITY default.[/]"
        )
        run_metrics = [
            vt.EvaluationRunMetric(metric=vt.RubricMetric.GENERAL_QUALITY.name),
        ]

    destination = dest or _default_destination(project)
    console.print(f"  [dim]Dest:    [/] [cyan]{destination}[/]")

    client = Client(project=project, location=location)

    console.print()
    console.print("  [bold]Running inference...[/]")
    try:
        inference_df = client.evals.run_inference(agent=resolved, src=dataset)
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]run_inference failed:[/] {exc}")
        raise click.Abort()

    # The SDK's CandidateResponse pydantic model rejects rows whose response
    # text isn't a string (None / non-text content like raw tool calls).
    # Coerce to empty string so create_evaluation_run can still score them.
    inference_df = _sanitize_inference_responses(inference_df)

    console.print("  [bold]Submitting evaluation run...[/]")
    try:
        run = client.evals.create_evaluation_run(
            dataset=inference_df,
            metrics=run_metrics,
            dest=destination,
        )
    except Exception as exc:  # noqa: BLE001 — surface SDK errors with context
        console.print(f"  [red]create_evaluation_run failed:[/] {exc}")
        raise click.Abort()

    console.print()
    console.print("  [green]>[/] Evaluation run submitted.")
    dashboard_url = getattr(run, "dashboard_url", None)
    if dashboard_url:
        console.print(f"  [bold]View results:[/] [cyan]{dashboard_url}[/]")
    else:
        console.print(f"  [dim]Run object:[/] {run!r}")
