"""Scaffolds the eval/ folder structure for a new agent project."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()


METRIC_TEMPLATES = {
    "general_quality": {
        "metric_type": "llm",
        "is_managed": True,
        "managed_metric_name": "GENERAL_QUALITY",
        "use_gemini_format": True,
        "score_range": {"min": 0, "max": 1, "description": "Passing rate for quality rubrics"},
    },
    "trajectory_accuracy": {
        "metric_type": "llm",
        "requires_multi_turn": True,
        "score_range": {"min": 0, "max": 5, "description": "0=Wrong, 5=Perfect trajectory"},
        "dataset_mapping": {
            "prompt": {"source_column": "user_inputs"},
            "response": {"source_column": "trace_summary"},
            "reference": {"source_column": "extracted_data:tool_declarations"},
        },
        "template": (
            "Evaluate the agent's execution trajectory.\n\n"
            "**User Request:**\n{prompt}\n\n"
            "**Agent Trajectory:**\n{response}\n\n"
            "**Available Tools:**\n{reference}\n\n"
            "CRITICAL: Only evaluate against tools that EXIST in the list above.\n\n"
            "**Scoring (0-5):**\n"
            "- 5: Optimal trajectory using available tools\n"
            "- 3: Acceptable with minor inefficiencies\n"
            "- 0: Completely wrong approach\n\n"
            "Score: [0-5]\nExplanation: [Your reasoning]"
        ),
    },
    "tool_use_quality": {
        "metric_type": "llm",
        "score_range": {"min": 0, "max": 5, "description": "0=Poor, 5=Excellent"},
        "dataset_mapping": {
            "prompt": {"source_column": "user_inputs"},
            "response": {"source_column": "final_response"},
            "reference": {
                "template": "Available Tools: {extracted_data_tool_declarations}\n\nTool Calls: {extracted_data_tool_interactions}",
                "source_columns": ["extracted_data:tool_declarations", "extracted_data:tool_interactions"],
            },
        },
        "template": (
            "Evaluate tool usage.\n\n"
            "**Request:** {prompt}\n"
            "**Response:** {response}\n\n"
            "{reference}\n\n"
            "**Criteria:**\n"
            "1. Tool Selection: Were appropriate tools chosen?\n"
            "2. Arguments: Were parameters correct?\n"
            "3. Efficiency: Were calls non-redundant?\n\n"
            "Score: [0-5]\nExplanation:"
        ),
    },
    "safety": {
        "metric_type": "llm",
        "is_managed": True,
        "managed_metric_name": "SAFETY",
        "use_gemini_format": True,
        "score_range": {"min": 0, "max": 1, "description": "Passing rate for safety rubrics"},
    },
}


def scaffold_eval_structure(
    target_dir: Path,
    agent_name: str = "app",
    mode: str = "both",
    metrics: list[str] | None = None,
    custom_metric_definitions: dict | None = None,
    ai_recommendations: dict | None = None,
) -> None:
    """Creates the eval/ folder structure with starter templates.

    Args:
        target_dir: Root directory of the agent project (eval/ is created here).
        agent_name: Agent module name (folder containing agent.py).
        mode: 'user-sim', 'diy', or 'both'.
        metrics: List of metric keys to include from METRIC_TEMPLATES.
        custom_metric_definitions: AI-generated metric definitions to merge in.
        ai_recommendations: Gemini's recommendations dict with scenarios/golden_data.
    """
    eval_dir = target_dir / "eval"
    has_ai = custom_metric_definitions is not None

    # Resolve which metrics to include
    metric_defs = {"metrics": {}}

    if custom_metric_definitions:
        # AI metrics provided — use ONLY what the AI generated (no forced defaults)
        for key, defn in custom_metric_definitions.items():
            if "agents" not in defn:
                defn["agents"] = [agent_name]
            metric_defs["metrics"][key] = defn
    else:
        # No AI metrics — use standard defaults
        if metrics is None:
            if mode == "diy":
                metrics = ["general_quality", "tool_use_quality", "safety"]
            else:
                metrics = ["general_quality", "trajectory_accuracy", "tool_use_quality", "safety"]

        for key in metrics:
            if key in METRIC_TEMPLATES:
                defn = dict(METRIC_TEMPLATES[key])
                if "agents" not in defn:
                    defn["agents"] = [agent_name]
                metric_defs["metrics"][key] = defn

    # Create directories
    for d in [eval_dir, eval_dir / "metrics", eval_dir / "scenarios", eval_dir / "results"]:
        d.mkdir(parents=True, exist_ok=True)

    # If AI content is provided and existing files exist, back them up
    backup_dir = None
    if has_ai:
        backed_up = _backup_existing_files(eval_dir, mode)
        if backed_up:
            backup_dir = backed_up
            console.print(f"  [dim]Previous files backed up to eval/.backup/[/]")

    display_prefix = str(eval_dir)

    _write_if_missing(eval_dir / "__init__.py", "")
    _write_if_missing(eval_dir / "results" / ".gitkeep", "")

    # ── Metrics ───────────────────────────────────────────────────────────
    metrics_path = eval_dir / "metrics" / "metric_definitions.json"
    if has_ai:
        # AI mode: always write (backup already taken if file existed)
        metrics_path.write_text(json.dumps(metric_defs, indent=2) + "\n")
        console.print(f"  [green]created[/]  {display_prefix}/metrics/metric_definitions.json")
    else:
        existed = metrics_path.exists()
        _write_json_if_missing(metrics_path, metric_defs)
        status = "[yellow]kept[/]" if existed else "[green]created[/]"
        console.print(f"  {status}     {display_prefix}/metrics/metric_definitions.json")

    # ── Session input ─────────────────────────────────────────────────────
    session_path = eval_dir / "scenarios" / "session_input.json"
    session_input = {"app_name": agent_name, "user_id": "eval_user"}
    if session_path.exists():
        console.print(f"  [yellow]kept[/]     {display_prefix}/scenarios/session_input.json")
    else:
        _write_json_if_missing(session_path, session_input)
        console.print(f"  [green]created[/]  {display_prefix}/scenarios/session_input.json")

    # ── Scenarios ─────────────────────────────────────────────────────────
    if mode in ("user-sim", "both"):
        scenarios_path = eval_dir / "scenarios" / "conversation_scenarios.json"
        if has_ai and ai_recommendations and ai_recommendations.get("scenarios"):
            # AI mode: write AI scenarios (backup already taken)
            ai_scenarios = _build_ai_scenarios(ai_recommendations["scenarios"])
            # If file didn't exist, start fresh; if it did, merge AI scenarios
            if scenarios_path.exists() and backup_dir:
                # Existing file was backed up — read old scenarios, append AI ones
                try:
                    old = json.loads(scenarios_path.read_text())
                    old_scenarios = old.get("scenarios", [])
                    merged = {"scenarios": old_scenarios + ai_scenarios["scenarios"]}
                    scenarios_path.write_text(json.dumps(merged, indent=2) + "\n")
                except Exception:
                    scenarios_path.write_text(json.dumps(ai_scenarios, indent=2) + "\n")
            else:
                scenarios_path.write_text(json.dumps(ai_scenarios, indent=2) + "\n")
            console.print(f"  [green]created[/]  {display_prefix}/scenarios/conversation_scenarios.json")
        elif not scenarios_path.exists():
            default_scenarios = {
                "scenarios": [
                    {
                        "starting_prompt": "Hello, I need help with something.",
                        "conversation_plan": "Ask the agent about its capabilities. Follow up with a specific request.",
                    }
                ]
            }
            _write_json_if_missing(scenarios_path, default_scenarios)
            console.print(f"  [green]created[/]  {display_prefix}/scenarios/conversation_scenarios.json")
        else:
            console.print(f"  [yellow]kept[/]     {display_prefix}/scenarios/conversation_scenarios.json")

    # ── Golden dataset ────────────────────────────────────────────────────
    if mode in ("diy", "both"):
        (eval_dir / "eval_data").mkdir(parents=True, exist_ok=True)
        golden_path = eval_dir / "eval_data" / "golden_dataset.json"
        if has_ai and ai_recommendations and ai_recommendations.get("golden_data"):
            # AI mode: write AI golden data (backup already taken)
            ai_golden = _build_ai_golden_data(ai_recommendations["golden_data"], agent_name)
            if golden_path.exists() and backup_dir:
                # Existing file was backed up — read old entries, append AI ones
                try:
                    old = json.loads(golden_path.read_text())
                    old_questions = old.get("golden_questions", [])
                    merged = {"golden_questions": old_questions + ai_golden["golden_questions"]}
                    golden_path.write_text(json.dumps(merged, indent=2) + "\n")
                except Exception:
                    golden_path.write_text(json.dumps(ai_golden, indent=2) + "\n")
            else:
                golden_path.write_text(json.dumps(ai_golden, indent=2) + "\n")
            console.print(f"  [green]created[/]  {display_prefix}/eval_data/golden_dataset.json")
        elif not golden_path.exists():
            default_golden = {
                "golden_questions": [
                    {
                        "id": "test_001",
                        "user_inputs": ["Hello, what can you help me with?"],
                        "agents_evaluated": [agent_name],
                        "metadata": {"description": "Basic capability check"},
                        "reference_data": {
                            "expected_behavior": "Agent should describe its capabilities"
                        },
                    }
                ]
            }
            _write_json_if_missing(golden_path, default_golden)
            console.print(f"  [green]created[/]  {display_prefix}/eval_data/golden_dataset.json")
        else:
            console.print(f"  [yellow]kept[/]     {display_prefix}/eval_data/golden_dataset.json")

    console.print(f"  [green]created[/]  {display_prefix}/results/.gitkeep")

    if backup_dir:
        console.print()
        console.print(f"  [dim]Your previous files are in:[/]  [cyan]{backup_dir}[/]")
        console.print(f"  [dim]Delete when satisfied:[/]       rm -rf {backup_dir}")


def _build_ai_scenarios(scenario_recs: list) -> dict:
    """Convert Gemini's scenario recommendations to conversation_scenarios.json format."""
    scenarios = []
    for s in scenario_recs:
        scenario = {}
        if s.get("starting_prompt"):
            scenario["starting_prompt"] = s["starting_prompt"]
        else:
            scenario["starting_prompt"] = s.get("description", "Hello")
        if s.get("conversation_plan"):
            scenario["conversation_plan"] = s["conversation_plan"]
        else:
            scenario["conversation_plan"] = s.get("description", "Follow the agent's lead.")
        scenarios.append(scenario)
    return {"scenarios": scenarios}


def _build_ai_golden_data(golden_recs: list, agent_name: str) -> dict:
    """Convert Gemini's golden data recommendations to golden_dataset.json format."""
    questions = []
    for i, g in enumerate(golden_recs, 1):
        user_inputs = g.get("user_inputs", [])
        if not user_inputs and g.get("description"):
            user_inputs = [g["description"]]
        ref = g.get("reference_data", {})
        expected = ref.get("expected_behavior", "") if isinstance(ref, dict) else ""
        if not expected:
            expected = g.get("expected_behavior", g.get("description", ""))
        questions.append({
            "id": f"ai_generated_{i:03d}",
            "user_inputs": user_inputs,
            "agents_evaluated": [agent_name],
            "metadata": {"description": g.get("description", "")},
            "reference_data": {
                "expected_behavior": expected
            },
        })
    return {"golden_questions": questions}


def _backup_existing_files(eval_dir: Path, mode: str) -> Path | None:
    """Back up existing eval files before AI overwrites them.

    Returns the backup directory path if any files were backed up, else None.
    """
    files_to_backup = [eval_dir / "metrics" / "metric_definitions.json"]
    if mode in ("user-sim", "both"):
        files_to_backup.append(eval_dir / "scenarios" / "conversation_scenarios.json")
    if mode in ("diy", "both"):
        files_to_backup.append(eval_dir / "eval_data" / "golden_dataset.json")

    existing = [f for f in files_to_backup if f.exists()]
    if not existing:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = eval_dir / ".backup" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    for f in existing:
        rel = f.relative_to(eval_dir)
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)

    return backup_dir


def scaffold_metrics_only(
    target_dir: Path,
    agent_name: str = "app",
    metrics: list[str] | None = None,
    custom_metric_definitions: dict | None = None,
) -> None:
    """Scaffold only ``tests/eval/metrics/metric_definitions.json`` (Path A use).

    Path A doesn't need scenarios or golden datasets — ``agent-engine`` reads
    ``tests/eval/dataset.jsonl`` directly and only needs the metric file to
    know what to score against. Writes to the canonical unified layout.
    """
    eval_dir = target_dir / "tests" / "eval"
    metric_defs = {"metrics": {}}

    if custom_metric_definitions:
        for key, defn in custom_metric_definitions.items():
            if "agents" not in defn:
                defn["agents"] = [agent_name]
            metric_defs["metrics"][key] = defn
    else:
        if metrics is None:
            metrics = ["general_quality", "tool_use_quality", "safety"]
        for key in metrics:
            if key in METRIC_TEMPLATES:
                defn = dict(METRIC_TEMPLATES[key])
                if "agents" not in defn:
                    defn["agents"] = [agent_name]
                metric_defs["metrics"][key] = defn

    (eval_dir / "metrics").mkdir(parents=True, exist_ok=True)
    (eval_dir / "results").mkdir(parents=True, exist_ok=True)
    _write_if_missing(eval_dir / "results" / ".gitkeep", "")

    metrics_path = eval_dir / "metrics" / "metric_definitions.json"
    if metrics_path.exists() and custom_metric_definitions:
        backup = _backup_existing_files(eval_dir, mode="dataset-only")
        if backup:
            console.print(f"  [dim]Previous metrics backed up to tests/eval/.backup/[/]")
    if metrics_path.exists() and not custom_metric_definitions:
        console.print(f"  [yellow]kept[/]     {eval_dir}/metrics/metric_definitions.json")
    else:
        metrics_path.write_text(json.dumps(metric_defs, indent=2) + "\n")
        console.print(f"  [green]created[/]  {eval_dir}/metrics/metric_definitions.json")
    console.print(f"  [green]created[/]  {eval_dir}/results/.gitkeep")


def _rows_from_recommendations(
    recommendations: dict | None,
    session_inputs: dict,
) -> list[dict]:
    """Convert Gemini's recommendations dict into unified dataset.jsonl rows.

    Maps the same shape that ``_build_ai_scenarios`` / ``_build_ai_golden_data``
    produce for the legacy files, but emits canonical SDK columns instead:
    - ``starting_prompt`` → ``prompt``; ``conversation_plan`` kept verbatim
    - ``user_inputs[-1]`` → ``prompt``; earlier turns → ``conversation_history``
    - ``reference_data.expected_behavior`` → ``reference``; other
      ``reference_data.*`` keys flatten to top-level ``expected_*`` columns
    Every row gets the supplied ``session_inputs``.
    """
    rows: list[dict] = []
    if not recommendations:
        return rows

    for scen in recommendations.get("scenarios") or []:
        prompt = scen.get("starting_prompt") or scen.get("description") or ""
        if not prompt:
            continue
        row: dict = {"prompt": prompt, "session_inputs": session_inputs}
        plan = scen.get("conversation_plan")
        if plan:
            row["conversation_plan"] = plan
        rows.append(row)

    for i, g in enumerate(recommendations.get("golden_data") or [], 1):
        user_inputs = g.get("user_inputs") or []
        if not user_inputs and g.get("description"):
            user_inputs = [g["description"]]
        if not user_inputs:
            continue
        row = {"prompt": user_inputs[-1], "session_inputs": session_inputs}
        if len(user_inputs) > 1:
            row["conversation_history"] = [
                {"role": "user", "parts": [{"text": t}]} for t in user_inputs[:-1]
            ]
        ref_data = g.get("reference_data") or {}
        for key, value in ref_data.items():
            if not value:
                continue
            if key == "expected_behavior":
                row["reference"] = value
            else:
                row[key] = value
        if g.get("id"):
            row["id"] = g["id"]
        else:
            row["id"] = f"ai_generated_{i:03d}"
        rows.append(row)

    return rows


def scaffold_dataset_jsonl(
    target_dir: Path,
    agent_name: str = "app",
    *,
    recommendations: dict | None = None,
) -> None:
    """Scaffold ``tests/eval/dataset.jsonl`` for Path A (Agent Engine) usage.

    When ``recommendations`` carries Gemini-generated ``scenarios`` and/or
    ``golden_data``, those are converted into rows so Path A evaluates against
    the user's actual agent (not generic "Hello" prompts) — the existing file
    is backed up and replaced so re-running ``init --ai-metrics`` actually
    refreshes content. Without recommendations, an existing file is preserved
    and only fresh projects get the 2-row starter.
    """
    dataset_path = target_dir / "tests" / "eval" / "dataset.jsonl"

    session_inputs = {"app_name": agent_name, "user_id": "eval_user", "state": {}}
    ai_rows = _rows_from_recommendations(recommendations, session_inputs)

    if dataset_path.exists() and not ai_rows:
        console.print(f"  [yellow]kept[/]     {dataset_path}")
        return

    if dataset_path.exists() and ai_rows:
        backup_root = target_dir / "tests" / "eval" / ".backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dataset_path, backup_root / "dataset.jsonl")
        console.print(f"  [dim]Previous dataset backed up to {backup_root}[/]")

    rows = ai_rows or [
        {"prompt": "Hello, what can you help me with?", "session_inputs": session_inputs},
        {"prompt": "Walk me through one of your most common tasks.", "session_inputs": session_inputs},
    ]

    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    console.print(f"  [green]created[/]  {dataset_path} [dim]({len(rows)} rows)[/]")


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _write_json_if_missing(path: Path, data: dict) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
