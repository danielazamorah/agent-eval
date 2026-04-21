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
    so we translate inline:

    - **Managed rubric** (``is_managed: true``) → ``RubricMetric.<NAME>`` →
      ``EvaluationRunMetric(metric=...)``.
    - **Custom LLM judge** (``template`` + ``score_range``) →
      ``vt.LLMMetric`` via ``metric_factory.custom_llm_judge`` →
      ``EvaluationRunMetric(metric_config=UnifiedMetric(llm_based_metric_spec=...))``
      via ``metric_factory.to_evaluation_run_metric``.
    """
    from vertexai._genai import types as vt
    from agent_eval.core import metric_factory

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

        template = spec.get("template")
        score_range = spec.get("score_range") or {}
        if template and score_range:
            try:
                smin = int(score_range.get("min", 0))
                smax = int(score_range.get("max", 5))
            except (TypeError, ValueError):
                smin, smax = 0, 5
            description = str(score_range.get("description") or "")
            criteria = {"evaluation": template}
            rating_scores = {
                str(i): description if (i in (smin, smax) and description) else f"Score {i}"
                for i in range(smin, smax + 1)
            }
            try:
                llm_metric = metric_factory.custom_llm_judge(
                    name=name,
                    criteria=criteria,
                    rating_scores=rating_scores,
                )
                run_metrics.append(metric_factory.to_evaluation_run_metric(llm_metric))
                continue
            except Exception as exc:  # noqa: BLE001
                console.print(
                    f"  [yellow]![/] Skipping [cyan]{name}[/]: failed to build "
                    f"custom LLM metric ({exc})."
                )
                continue

        console.print(
            f"  [yellow]![/] Skipping [cyan]{name}[/]: not a managed rubric and "
            f"missing ``template`` + ``score_range`` for a custom LLM judge."
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
    return f"gs://{bucket}/agent-eval/{timestamp}"


def _bucket_name_from_uri(uri: str) -> Optional[str]:
    """Extract the bucket name from a ``gs://bucket/path`` URI."""
    if not uri.startswith("gs://"):
        return None
    rest = uri[len("gs://"):]
    return rest.split("/", 1)[0] or None


def _ensure_bucket_exists(uri: str, project: str, location: str) -> None:
    """Create the destination bucket if it doesn't already exist.

    First-time users get ``BucketNotFoundException`` from
    ``create_evaluation_run`` because the SDK doesn't auto-provision the
    bucket. We do it here so the command works end-to-end on the first run.
    """
    bucket_name = _bucket_name_from_uri(uri)
    if not bucket_name:
        return

    try:
        from google.cloud import storage
        from google.api_core.exceptions import Forbidden, GoogleAPICallError
    except ImportError:
        return  # storage not installed — let the SDK error speak for itself.

    storage_client = storage.Client(project=project)
    try:
        existing = storage_client.lookup_bucket(bucket_name)
    except Forbidden as exc:
        console.print(
            f"  [yellow]![/] Cannot check bucket [cyan]gs://{bucket_name}[/]: "
            f"{exc.message if hasattr(exc, 'message') else exc}. "
            f"Continuing — the SDK will fail loudly if the bucket isn't usable."
        )
        return

    if existing is not None:
        console.print(f"  [green]>[/] Using bucket [cyan]gs://{bucket_name}[/]")
        return

    console.print(
        f"  [dim]Bucket [cyan]gs://{bucket_name}[/] not found — creating in {location}...[/]"
    )
    try:
        storage_client.create_bucket(bucket_name, location=location)
    except Forbidden as exc:
        console.print(
            f"  [red]Cannot create bucket [cyan]gs://{bucket_name}[/]:[/] {exc}\n"
            f"  [dim]Grant your account [cyan]roles/storage.admin[/] on project "
            f"[cyan]{project}[/], or pass [cyan]--dest gs://<existing-bucket>/path[/].[/]"
        )
        raise click.Abort()
    except GoogleAPICallError as exc:
        console.print(f"  [red]create_bucket failed:[/] {exc}")
        raise click.Abort()
    console.print(f"  [green]>[/] Created bucket [cyan]gs://{bucket_name}[/]")


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
    "--timeout",
    type=int,
    default=900,
    show_default=True,
    help="Seconds to wait for the run to finish before giving up (use --no-wait to skip).",
)
@click.option(
    "--no-wait",
    is_flag=True,
    help="Submit the run and exit immediately. Print the resource name + dashboard URL.",
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
    timeout: int,
    no_wait: bool,
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

    _ensure_bucket_exists(destination, project, location)

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
    run_name = getattr(run, "name", None)
    if run_name:
        console.print(f"  [dim]Run:     [/] [cyan]{run_name}[/]")

    if no_wait:
        _print_dashboard_url(run, project, location)
        console.print(f"  [dim]GCS:     [/] [cyan]{destination}[/]")
        return

    final_run = _wait_for_run(client, run, timeout=timeout)
    state = getattr(final_run, "state", None)
    state_value = getattr(state, "value", state)

    if str(state_value).upper() == "SUCCEEDED":
        console.print(f"  [green]>[/] Run [bold]SUCCEEDED[/].")
    elif str(state_value).upper() in {"FAILED", "CANCELLED"}:
        console.print(f"  [red]Run finished with state [bold]{state_value}[/].[/]")
        error = getattr(final_run, "error", None)
        if error:
            console.print(f"  [dim]Error:[/] {error}")
    else:
        console.print(
            f"  [yellow]![/] Timed out after {timeout}s — last state: [bold]{state_value}[/]. "
            f"Re-run with [cyan]--timeout <seconds>[/] or check the dashboard."
        )

    _print_dashboard_url(final_run, project, location)
    console.print(f"  [dim]GCS:     [/] [cyan]{destination}[/]")


def _print_dashboard_url(run: Any, project: str, location: str) -> None:
    """Print the dashboard URL, falling back to a constructed console URL."""
    dashboard_url = getattr(run, "dashboard_url", None)
    if not dashboard_url:
        run_name = getattr(run, "name", None)
        if run_name:
            short = run_name.split("/")[-1]
            dashboard_url = (
                f"https://console.cloud.google.com/vertex-ai/evaluations/"
                f"evaluation-runs/{short};location={location}?project={project}"
            )
    if dashboard_url:
        console.print(f"  [bold]View results:[/] [cyan]{dashboard_url}[/]")


def _wait_for_run(client: Any, run: Any, *, timeout: int) -> Any:
    """Poll get_evaluation_run until terminal state or timeout."""
    import time
    from vertexai._genai.types import EvaluationRunState

    terminal = {
        EvaluationRunState.SUCCEEDED,
        EvaluationRunState.FAILED,
        EvaluationRunState.CANCELLED,
    }
    name = getattr(run, "name", None)
    if not name:
        return run

    console.print(f"  [bold]Waiting for evaluation to finish[/] [dim](timeout {timeout}s)...[/]")
    deadline = time.time() + timeout
    last_state: Any = None
    while time.time() < deadline:
        try:
            run = client.evals.get_evaluation_run(name=name)
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [yellow]![/] get_evaluation_run failed (will retry): {exc}")
            time.sleep(10)
            continue

        state = getattr(run, "state", None)
        if state != last_state:
            console.print(f"  [dim]state = {getattr(state, 'value', state)}[/]")
            last_state = state
        if state in terminal:
            return run
        time.sleep(10)
    return run
