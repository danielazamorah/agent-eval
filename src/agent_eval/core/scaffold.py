"""Scaffolds the eval/ folder structure for a new agent project."""

import json
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
        "score_range": {"min": 0, "max": 5, "description": "0=Wrong, 5=Perfect trajectory"},
        "dataset_mapping": {
            "prompt": {"source_column": "user_inputs"},
            "response": {"source_column": "trace_summary"},
            "available_tools": {"source_column": "extracted_data:tool_declarations"},
        },
        "template": (
            "Evaluate the agent's execution trajectory.\n\n"
            "**User Request:**\n{prompt}\n\n"
            "**Agent Trajectory:**\n{response}\n\n"
            "**Available Tools:**\n{available_tools}\n\n"
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
            "tool_interactions": {"source_column": "extracted_data:tool_interactions"},
            "available_tools": {"source_column": "extracted_data:tool_declarations"},
        },
        "template": (
            "Evaluate tool usage.\n\n"
            "**Request:** {prompt}\n"
            "**Available Tools:** {available_tools}\n"
            "**Tool Calls:** {tool_interactions}\n"
            "**Response:** {response}\n\n"
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
    agent_name: str = "my_agent",
    mode: str = "both",
    metrics: list[str] | None = None,
) -> None:
    """Creates the eval/ folder structure with starter templates.

    Args:
        target_dir: Root directory of the agent project.
        agent_name: Agent application name.
        mode: 'user-sim', 'diy', or 'both'.
        metrics: List of metric keys to include.
    """
    eval_dir = target_dir / "eval"

    if eval_dir.exists():
        console.print(f"  [yellow]Warning:[/] '{eval_dir}' already exists. Skipping existing files.")

    # Resolve which metrics to include
    if metrics is None:
        metrics = ["general_quality", "trajectory_accuracy"]

    # Build metric definitions
    metric_defs = {"metrics": {}}
    for key in metrics:
        if key in METRIC_TEMPLATES:
            defn = dict(METRIC_TEMPLATES[key])
            # Add agents field with actual agent name
            if "agents" not in defn:
                defn["agents"] = [agent_name]
            metric_defs["metrics"][key] = defn

    # Create directories
    for d in [eval_dir, eval_dir / "metrics", eval_dir / "scenarios", eval_dir / "results"]:
        d.mkdir(parents=True, exist_ok=True)

    _write_if_missing(eval_dir / "__init__.py", "")
    _write_if_missing(eval_dir / "results" / ".gitkeep", "")

    _write_json_if_missing(eval_dir / "metrics" / "metric_definitions.json", metric_defs)
    console.print(f"  [green]ok[/] eval/metrics/metric_definitions.json")

    session_input = {"app_name": agent_name, "user_id": "eval_user"}
    _write_json_if_missing(eval_dir / "scenarios" / "session_input.json", session_input)
    console.print(f"  [green]ok[/] eval/scenarios/session_input.json")

    if mode in ("user-sim", "both"):
        scenarios = {
            "scenarios": [
                {
                    "starting_prompt": "Hello, I need help with something.",
                    "conversation_plan": "Ask the agent about its capabilities. Follow up with a specific request.",
                }
            ]
        }
        _write_json_if_missing(eval_dir / "scenarios" / "conversation_scenarios.json", scenarios)
        console.print(f"  [green]ok[/] eval/scenarios/conversation_scenarios.json")

    if mode in ("diy", "both"):
        golden = {
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
        (eval_dir / "eval_data").mkdir(parents=True, exist_ok=True)
        _write_json_if_missing(eval_dir / "eval_data" / "golden_dataset.json", golden)
        console.print(f"  [green]ok[/] eval/eval_data/golden_dataset.json")

    console.print(f"  [green]ok[/] eval/results/.gitkeep")


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _write_json_if_missing(path: Path, data: dict) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
