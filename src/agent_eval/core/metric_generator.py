# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""AI-powered metric generation and evaluation advisory using Gemini.

Analyzes agent source code, existing eval files, and developer priorities
to generate tailored evaluation metrics and provide recommendations on
scenarios, golden datasets, and evaluation strategy.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_eval.core.adk_optimization_patterns import ADK_OPTIMIZATION_PATTERNS
from agent_eval.core.scaffold import METRIC_TEMPLATES
from agent_eval.core.utils import discover_agent_context


class MetricGenerationError(Exception):
    """Raised when metric generation fails."""
    pass


# All valid source_column values that dataset_mapping can reference.
VALID_SOURCE_COLUMNS = {
    "user_inputs",
    "final_response",
    "trace_summary",
    "extracted_data:tool_interactions",
    "extracted_data:tool_declarations",
    "extracted_data:state_variables",
    "extracted_data:conversation_history",
    "extracted_data:system_instruction",
    "extracted_data:thinking_trace",
    "extracted_data:grounding_chunks",
    "extracted_data:per_turn_tokens",
    "extracted_data:sub_agent_trace",
    "extracted_data:stop_reasons",
}

METRIC_GENERATION_PROMPT = """You are a Senior Evaluation Architect specializing in ADK (Agent Development Kit) agents. You design evaluation strategies that catch real issues before they reach production.

Your task: analyze the agent source code and any existing evaluation files, then:
1. Generate 2-4 custom LLM-as-judge metrics tailored to this agent
2. Provide actionable recommendations for scenarios, golden data, and evaluation strategy

{user_priorities_section}

---

## Agent Source Code

{agent_source_code}

---

{existing_eval_section}

## Metric Format Reference

**CRITICAL SDK CONSTRAINT:** The Vertex AI Evaluation SDK ONLY accepts three column names in dataset_mapping: `prompt`, `response`, and `reference`. Using ANY other column name will crash the SDK. You MUST combine all data into these three columns.

Each metric must follow this exact JSON structure:

```json
{{
    "metric_name_snake_case": {{
        "metric_type": "llm",
        "applies_to": "all",
        "score_range": {{
            "min": 0,
            "max": 5,
            "description": "0=Completely wrong, 5=Perfect"
        }},
        "dataset_mapping": {{
            "prompt": {{"source_column": "user_inputs"}},
            "response": {{"source_column": "final_response"}},
            "reference": {{"source_column": "trace_summary"}}
        }},
        "template": "Evaluate...\\n\\n**User Request:** {{prompt}}\\n**Response:** {{response}}\\n**Context:** {{reference}}\\n\\nScore: [0-5]\\nExplanation: [Your reasoning]"
    }}
}}
```

### `applies_to` — which data a metric runs on

The evaluation framework has TWO distinct data sources, and each metric must declare which source(s) it applies to. Getting this wrong means metrics run on incompatible data and produce meaningless scores.

| Value | Data source | Key characteristics |
|---|---|---|
| `"all"` (default) | Both sources | Use for metrics that evaluate ANY agent response (e.g., tool usage quality, response completeness). |
| `"scenarios"` | Multi-turn ADK User Sim data only | This data has conversation_history and trajectory but **NO reference/expected answers**. Use for: conversation flow, trajectory accuracy, turn-by-turn coherence, multi-turn context handling. API Predefined multi-turn metrics (e.g., MULTI_TURN_GENERAL_QUALITY) MUST use this. |
| `"golden_dataset"` | Single-turn golden dataset data only (from interact) | This data **HAS reference_data with expected answers**. Use for: correctness vs ground truth, factual accuracy, expected tool calls. Metrics that use `reference_data` fields in their mapping MUST use this. |

**Decision rules for `applies_to`:**
- Does the metric use `reference_data.*` fields (expected answers, expected tools)? → `"golden_dataset"` (this data is only available from golden datasets)
- Does it evaluate multi-turn conversation flow, trajectory, or turn coherence? → `"scenarios"` (only multi-turn data has meaningful conversation_history)
- Does it evaluate the response quality in a way that works for both? → `"all"`

### Available Managed (Predefined) Metrics

In addition to custom LLM metrics, you can include **managed metrics** — Google's built-in evaluation rubrics that require no custom template. Include them in your output alongside custom metrics when appropriate.

**Format for managed metrics** (no template or dataset_mapping needed):
```json
"metric_name": {{
    "is_managed": true,
    "managed_metric_name": "METRIC_NAME",
    "use_gemini_format": true,
    "applies_to": "all"
}}
```

| Managed Metric | applies_to | What it evaluates |
|---|---|---|
| `GENERAL_QUALITY` | all | Overall response quality (rubric, 0-1 pass rate) |
| `TEXT_QUALITY` | all | Writing quality: grammar, clarity, structure (1-5) |
| `INSTRUCTION_FOLLOWING` | all | Adherence to user instructions (1-5) |
| `FLUENCY` | all | Language fluency and naturalness (1-5) |
| `COHERENCE` | all | Logical flow and consistency (1-5) |
| `GROUNDEDNESS` | all | Whether claims are supported by context (1-5) |
| `SAFETY` | all | Freedom from harmful content (rubric, 0-1 pass rate) |
| `VERBOSITY` | all | Response length appropriateness (-2 to 2) |
| `SUMMARIZATION_QUALITY` | all | Summarization coverage/accuracy (1-5) |
| `QUESTION_ANSWERING_QUALITY` | all | QA accuracy and completeness (1-5) |
| `MULTI_TURN_CHAT_QUALITY` | **scenarios** | Multi-turn conversation quality (rubric, 0-1 pass rate) |
| `MULTI_TURN_SAFETY` | **scenarios** | Safety across multi-turn conversations (rubric, 0-1 pass rate) |

**When to use managed vs custom metrics:**
- Use **managed metrics** for standard quality dimensions (quality, safety, fluency) — they're well-calibrated and free
- Use **custom metrics** for agent-specific behaviors (tool usage patterns, domain logic, capability boundaries) — these need tailored rubrics
- You can mix both in one output — include managed metrics as-is plus custom metrics with full template/mapping

### ONLY these three placeholder names are allowed:

| Placeholder | Typical mapping | Usage |
|---|---|---|
| `prompt` | User input — usually `user_inputs` | The user's request or question |
| `response` | Agent output — usually `final_response` or `trace_summary` | What the agent did or said |
| `reference` | Context/evidence — tool data, declarations, state, etc. | Supporting data for evaluation |

### Combining multiple data sources into `reference`:

When you need multiple data sources (e.g., tool interactions AND tool declarations), use the combined template syntax:

```json
"reference": {{
    "template": "Available Tools: {{extracted_data_tool_declarations}}\\n\\nTool Calls: {{extracted_data_tool_interactions}}",
    "source_columns": ["extracted_data:tool_declarations", "extracted_data:tool_interactions"]
}}
```

Note: In the `template` field inside `source_columns`, colons are replaced with underscores (e.g., `extracted_data:tool_interactions` → `{{extracted_data_tool_interactions}}`).

### Valid `source_column` values:

| source_column | Description |
|---|---|
| `user_inputs` | User messages (JSON list of strings) |
| `final_response` | Agent's final text response to the user |
| `trace_summary` | Execution trajectory summary (tool calls + results) |
| `extracted_data:tool_interactions` | Tool calls with input arguments and output results |
| `extracted_data:tool_declarations` | Available tools and their descriptions |
| `extracted_data:state_variables` | Session state variables (dict of all state) |
| `extracted_data:conversation_history` | Full multi-turn conversation |
| `extracted_data:system_instruction` | Agent's system prompt / instruction |
| `extracted_data:sub_agent_trace` | Agent's step-by-step reasoning trace |
| `extracted_data:<state_var_name>` | Any agent-specific state variable (e.g., `extracted_data:cart`, `extracted_data:user_preferences`). Look at the agent's `state` usage in the source code to find custom variables. |

### Example metrics (for format reference only):

**trajectory_accuracy** (uses `reference` for tool declarations):
```json
{example_trajectory}
```

**tool_use_quality** (uses combined `reference` for tools + interactions):
```json
{example_tool_use}
```

---

## ADK Evaluation Best Practices

### Scenario Design (for User Sim multi-turn evaluation)
- Each scenario has a `starting_prompt` (first user message) and `conversation_plan` (how the simulated user behaves)
- Good scenarios test: happy paths, edge cases, error handling, multi-step workflows, ambiguous requests
- Scenarios should cover each tool the agent has, including combinations
- Include scenarios where the agent should refuse or clarify (capability boundaries)
- Scenarios do NOT have reference data — the simulator evaluates conversation flow, not exact answers

### Golden Dataset Design (for single-turn / regression testing)
- Each entry has `user_inputs` (list of queries), `agents_evaluated`, and optional `reference_data`
- `reference_data` can include `expected_behavior`, `expected_tools`, or any field your metrics reference
- Golden datasets are for testing against known-good answers — the agent's response is compared to reference data
- Good golden datasets cover: typical queries, edge cases, out-of-scope requests, multi-tool queries

### ADK Design Patterns (what to look for in agent behavior)

{adk_patterns}

---

## Instructions

**Part 1 — Metrics:**
1. Analyze the agent's tools, instruction/prompt, sub-agents, state usage, and domain
2. If existing metrics are provided: **preserve and improve them**. Include every existing metric in your output (improved or as-is). Only remove a metric if you provide a clear reason in the rationale (e.g., "removed X because it duplicates Y" or "removed X because its mapping was broken"). Never silently drop existing metrics.
3. Generate additional metrics to fill gaps — target 3-5 total metrics (fewer focused metrics are better than many vague ones — each metric costs API calls per eval case)
4. You can include both **managed metrics** (predefined, no template needed) and **custom LLM metrics** (with template + dataset_mapping). Use managed metrics for standard dimensions (quality, safety, fluency) and custom metrics for agent-specific behaviors.
5. Each metric should target a distinct quality dimension
6. Set `applies_to` correctly: use `"golden_dataset"` for metrics that need reference data, `"scenarios"` for metrics that evaluate multi-turn conversation flow, `"all"` for general metrics
7. Reference the agent's actual tool names, state variables, and capabilities in custom metric templates

**Part 2 — Recommendations:**
Provide expert recommendations for the developer's evaluation strategy:
- **Scenarios to add:** Specific multi-turn conversation scenarios (with starting_prompt and conversation_plan). These are for ADK User Sim — no reference data needed, the simulator follows the plan and evaluates the conversation flow.
- **Golden data suggestions:** Single-turn test queries with expected behavior. These include reference data so the evaluator can check if the agent's response matches expectations.
- **Evaluation strategy:** What to focus on first, what metrics matter most for this agent type
- **Existing file improvements:** If existing scenarios/golden data were provided, suggest what to keep, remove, or modify

**IMPORTANT constraints:**
- Only generate metrics the user actually needs — do NOT add generic metrics like `safety` or `general_quality` unless the user specifically asks for them or they are already in the existing metrics file
- Metric names must be `snake_case`
- Every template MUST end with a scoring line using `Score: [X]` format (e.g., `Score: [0-5]` or `Score: [0-1]`) followed by `\\nExplanation: [Your reasoning]` — the evaluation parser relies on this pattern
- dataset_mapping keys MUST ONLY be `prompt`, `response`, and/or `reference` — the SDK crashes with any other name
- The template placeholders `{{prompt}}`, `{{response}}`, `{{reference}}` must match the dataset_mapping keys
- Score range should be 0-5 for consistency, but 0-1 (binary pass/fail) or 0-3 (checklist) are valid if they match the metric's evaluation style
- Only use valid source_columns from the table above
- Set `applies_to` to `"all"`, `"scenarios"`, or `"golden_dataset"` — see table above for guidance

**Respond with ONLY a JSON object** (no markdown fences, no extra text):

{{
    "metrics": {{
        "metric_name": {{ ... }},
        ...
    }},
    "rationale": "Brief explanation of why these metrics were chosen for this agent.",
    "recommendations": {{
        "scenarios": [
            {{
                "description": "What this scenario tests",
                "starting_prompt": "Example starting prompt",
                "conversation_plan": "Example conversation plan"
            }}
        ],
        "golden_data": [
            {{
                "description": "What this test case covers",
                "user_inputs": ["Example query"],
                "expected_behavior": "What the agent should do"
            }}
        ],
        "strategy": "Overall evaluation strategy advice for this agent.",
        "existing_file_feedback": "Feedback on existing eval files (if any were provided)."
    }}
}}
"""


def generate_metrics_with_gemini(
    agent_dir: Path,
    agent_name: str,
    user_priorities: str = "",
    model: str = "gemini-3.1-pro-preview",
    exclude_context: set[str] | None = None,
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    """Analyze agent source code and generate tailored evaluation metrics.

    Args:
        agent_dir: Path to the agent module directory.
        agent_name: Name of the agent module.
        user_priorities: Free-text description of what the user considers
            important to evaluate.
        model: Gemini model to use.
        exclude_context: Set of context keys to exclude from the Gemini prompt.
            Valid keys: 'metrics', 'scenarios', 'golden_data', 'analysis'.

    Returns:
        Tuple of (metrics_dict, rationale_string, recommendations_dict).

    Raises:
        MetricGenerationError: If generation fails at any stage.
    """
    # 1. Discover agent source code
    agent_context = discover_agent_context(agent_dir, quiet=True)
    if not agent_context:
        raise MetricGenerationError(
            f"No agent source code found in {agent_dir}. "
            "Make sure the directory contains agent.py."
        )

    # 2. Discover existing eval files
    existing_eval = _discover_existing_eval_files(agent_dir)

    # Remove excluded context
    if exclude_context:
        key_map = {"analysis": "gemini_analysis"}
        for key in exclude_context:
            mapped = key_map.get(key, key)
            existing_eval.pop(mapped, None)

    # 3. Build prompt
    prompt = _build_prompt(agent_context, user_priorities, existing_eval)

    # 4. Call Gemini
    raw_response = _call_gemini(prompt, model)

    # 5. Parse and validate
    metrics, warnings = _parse_and_validate_metrics(raw_response, agent_name)

    if not metrics:
        raise MetricGenerationError(
            "Gemini generated metrics but none passed validation. "
            "Falling back to starter metrics."
        )

    # Extract rationale and recommendations
    rationale = ""
    recommendations = {}
    try:
        parsed = _extract_json(raw_response)
        if parsed:
            rationale = parsed.get("rationale", "")
            recommendations = parsed.get("recommendations", {})
    except Exception:
        pass

    if warnings:
        rationale += "\n\nWarnings:\n" + "\n".join(f"  - {w}" for w in warnings)

    return metrics, rationale, recommendations


def _discover_existing_eval_files(agent_dir: Path) -> Dict[str, str]:
    """Read existing eval files (metrics, scenarios, golden data) if present.

    Returns a dict with keys like 'metrics', 'scenarios', 'golden_data'
    mapped to their file contents (truncated for prompt efficiency).
    """
    existing: Dict[str, str] = {}
    eval_dir = agent_dir / "eval"

    if not eval_dir.exists():
        return existing

    # Discover eval files dynamically
    from agent_eval.core.config import find_eval_files
    discovered = find_eval_files(eval_dir)

    # Existing metric definitions (use first found)
    for metrics_file in discovered["metrics"]:
        try:
            existing["metrics"] = metrics_file.read_text()
            break
        except Exception:
            pass

    # Existing scenarios (show first 3 for context, from all discovered files)
    all_scenarios = []
    for scenarios_file in discovered["scenarios"]:
        try:
            content = json.loads(scenarios_file.read_text())
            all_scenarios.extend(content.get("scenarios", []))
        except Exception:
            pass
    if all_scenarios:
        preview = {"scenarios": all_scenarios[:3]}
        if len(all_scenarios) > 3:
            preview["_note"] = f"Showing 3 of {len(all_scenarios)} scenarios"
        existing["scenarios"] = json.dumps(preview, indent=2)

    # Existing golden dataset (show first 3 entries, from all discovered files)
    all_questions = []
    for golden_file in discovered["golden_data"]:
        try:
            content = json.loads(golden_file.read_text())
            all_questions.extend(content.get("golden_questions", content.get("questions", [])))
        except Exception:
            pass
    if all_questions:
        preview = {"golden_questions": all_questions[:3]}
        if len(all_questions) > 3:
            preview["_note"] = f"Showing 3 of {len(all_questions)} questions"
        existing["golden_data"] = json.dumps(preview, indent=2)

    # Session input (for agent name context)
    session_file = eval_dir / "scenarios" / "session_input.json"
    if session_file.exists():
        try:
            existing["session_input"] = session_file.read_text()
        except Exception:
            pass

    # Previous evaluation results — find the most recent run with a Gemini analysis
    results_dir = eval_dir / "results"
    if results_dir.exists():
        run_folders = sorted(
            [d for d in results_dir.iterdir() if d.is_dir() and (d / "gemini_analysis.md").exists()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if run_folders:
            analysis_file = run_folders[0] / "gemini_analysis.md"
            try:
                analysis_content = analysis_file.read_text()
                # Truncate to ~6000 chars to keep prompt manageable
                if len(analysis_content) > 6000:
                    analysis_content = analysis_content[:6000] + "\n\n[... truncated for brevity ...]"
                existing["gemini_analysis"] = analysis_content
            except Exception:
                pass

    return existing


def _build_prompt(
    agent_context: Dict[str, str],
    user_priorities: str = "",
    existing_eval: Optional[Dict[str, str]] = None,
) -> str:
    """Build the Gemini prompt with agent code, existing files, and constraints."""
    # Format agent source code
    source_parts = []
    for filepath, content in agent_context.items():
        if filepath.endswith(".py"):
            source_parts.append(f"**File: `{filepath}`**\n```python\n{content}\n```")
        elif "GEMINI.md" in filepath:
            source_parts.append(f"**{filepath}**\n```markdown\n{content[:5000]}\n```")

    agent_source = "\n\n".join(source_parts) if source_parts else "No source code available."

    # Format example metrics
    example_trajectory = json.dumps(METRIC_TEMPLATES["trajectory_accuracy"], indent=2)
    example_tool_use = json.dumps(METRIC_TEMPLATES["tool_use_quality"], indent=2)

    # User priorities section
    if user_priorities:
        user_priorities_section = (
            "**DEVELOPER PRIORITIES:**\n"
            "The developer has indicated the following aspects are important to evaluate:\n"
            f"> {user_priorities}\n\n"
            "Prioritize generating metrics that address these concerns. "
            "Design rubrics that specifically test the behaviors the developer cares about."
        )
    else:
        user_priorities_section = ""

    # Existing eval files section
    existing_eval_section = ""
    if existing_eval:
        parts = ["## Existing Evaluation Files\n"]
        parts.append(
            "The agent already has evaluation files. You MUST:\n"
            "- **Keep** ALL existing metrics in your output (include them as-is or improved)\n"
            "- **Improve** existing metrics that have issues (fix mappings, sharpen rubrics, adjust scores)\n"
            "- **Add** new metrics for uncovered dimensions\n"
            "- **Remove** a metric ONLY if you explain why in the `rationale` field (e.g., broken mapping, exact duplicate of another metric)\n"
            "Your output replaces the existing metrics file, so include ALL metrics you recommend — both preserved originals and new ones. "
            "Do NOT silently drop metrics.\n"
        )

        if "metrics" in existing_eval:
            parts.append(f"**Existing metric definitions:**\n```json\n{existing_eval['metrics']}\n```\n")

        if "scenarios" in existing_eval:
            parts.append(f"**Existing conversation scenarios (preview):**\n```json\n{existing_eval['scenarios']}\n```\n")

        if "golden_data" in existing_eval:
            parts.append(f"**Existing golden dataset (preview):**\n```json\n{existing_eval['golden_data']}\n```\n")

        if "session_input" in existing_eval:
            parts.append(f"**Session input:**\n```json\n{existing_eval['session_input']}\n```\n")

        if "gemini_analysis" in existing_eval:
            parts.append(
                "**Previous evaluation analysis (AI-generated insights from the most recent run):**\n"
                "Use these findings to design metrics that catch the issues identified here.\n"
                f"```markdown\n{existing_eval['gemini_analysis']}\n```\n"
            )

        parts.append("---\n")
        existing_eval_section = "\n".join(parts)

    return METRIC_GENERATION_PROMPT.format(
        agent_source_code=agent_source,
        user_priorities_section=user_priorities_section,
        existing_eval_section=existing_eval_section,
        example_trajectory=example_trajectory,
        example_tool_use=example_tool_use,
        adk_patterns=ADK_OPTIMIZATION_PATTERNS[:4000],
    )


def _call_gemini(prompt: str, model: str) -> str:
    """Call the Gemini API and return the response text."""
    try:
        from google import genai
        from google.genai.types import HttpOptions
    except ImportError:
        raise MetricGenerationError(
            "google-genai package not installed. "
            "Install it with: pip install google-genai"
        )

    from agent_eval.core.config import get_project_id, get_location

    project = get_project_id()
    location = get_location(model)

    if not project:
        raise MetricGenerationError(
            "GOOGLE_CLOUD_PROJECT environment variable not set. "
            "Set it with: export GOOGLE_CLOUD_PROJECT=your-project-id"
        )

    try:
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=HttpOptions(api_version="v1"),
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        raise MetricGenerationError(f"Gemini API call failed: {e}")


def _extract_json(text: str) -> Optional[Dict]:
    """Extract JSON from Gemini's response, handling markdown fences."""
    # Try to find JSON in code fences first
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try parsing the whole response as JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try finding a JSON object in the text
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _parse_and_validate_metrics(
    raw_response: str,
    agent_name: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """Parse Gemini's response and validate each metric definition.

    Returns:
        Tuple of (valid_metrics_dict, warning_messages).
    """
    warnings: List[str] = []

    parsed = _extract_json(raw_response)
    if not parsed:
        return {}, ["Could not parse JSON from Gemini response."]

    raw_metrics = parsed.get("metrics", {})
    if not raw_metrics:
        return {}, ["No 'metrics' key found in response."]

    valid_metrics: Dict[str, Any] = {}

    for name, defn in raw_metrics.items():
        metric_warnings = _validate_single_metric(name, defn)
        if metric_warnings:
            warnings.extend(metric_warnings)
            continue

        # Ensure agents list is set
        if "agents" not in defn:
            defn["agents"] = [agent_name]

        # Ensure metric_type is set (managed metrics keep their type)
        if not defn.get("is_managed"):
            defn["metric_type"] = "llm"
        else:
            defn.setdefault("metric_type", "llm")

        valid_metrics[name] = defn

    return valid_metrics, warnings


ALLOWED_PLACEHOLDER_NAMES = {"prompt", "response", "reference"}


def _validate_single_metric(name: str, defn: Dict) -> List[str]:
    """Validate a single metric definition. Returns list of errors (empty = valid)."""
    errors: List[str] = []

    if not isinstance(defn, dict):
        return [f"'{name}': not a dict"]

    # Managed/predefined metrics (e.g., GENERAL_QUALITY, SAFETY) don't need
    # template or dataset_mapping — the SDK provides the evaluation logic.
    if defn.get("is_managed"):
        if not defn.get("managed_metric_name"):
            errors.append(f"'{name}': managed metric missing 'managed_metric_name'")
        applies_to = defn.get("applies_to", "all")
        if applies_to not in ("all", "scenarios", "golden_dataset"):
            errors.append(
                f"'{name}': applies_to must be 'all', 'scenarios', or 'golden_dataset', got '{applies_to}'"
            )
        return errors

    # Validate applies_to
    applies_to = defn.get("applies_to", "all")
    if applies_to not in ("all", "scenarios", "golden_dataset"):
        errors.append(
            f"'{name}': applies_to must be 'all', 'scenarios', or 'golden_dataset', got '{applies_to}'"
        )

    # Check required fields
    if "score_range" not in defn:
        errors.append(f"'{name}': missing score_range")
    elif not isinstance(defn["score_range"], dict):
        errors.append(f"'{name}': score_range must be a dict")
    else:
        sr = defn["score_range"]
        if "min" not in sr or "max" not in sr:
            errors.append(f"'{name}': score_range missing min/max")

    if "template" not in defn:
        errors.append(f"'{name}': missing template")
        return errors  # Can't validate placeholders without template

    if "dataset_mapping" not in defn:
        errors.append(f"'{name}': missing dataset_mapping")
        return errors

    template = defn["template"]
    mapping = defn["dataset_mapping"]

    # Validate placeholder names — SDK only accepts prompt, response, reference
    invalid_placeholders = set(mapping.keys()) - ALLOWED_PLACEHOLDER_NAMES
    if invalid_placeholders:
        errors.append(
            f"'{name}': dataset_mapping uses invalid keys {invalid_placeholders}. "
            f"The Vertex AI SDK only accepts: prompt, response, reference"
        )

    # Validate source_columns
    for placeholder, config in mapping.items():
        if not isinstance(config, dict):
            errors.append(f"'{name}.{placeholder}': must be a dict")
            continue

        # Support both simple source_column and combined template syntax
        if "source_column" in config:
            col = config["source_column"]
            if col not in VALID_SOURCE_COLUMNS and not col.startswith("extracted_data:"):
                errors.append(
                    f"'{name}.{placeholder}': invalid source_column '{col}'. "
                    f"Must be one of: {', '.join(sorted(VALID_SOURCE_COLUMNS))}"
                )
        elif "source_columns" in config and "template" in config:
            # Combined template syntax — validate each source column
            for col in config["source_columns"]:
                if col not in VALID_SOURCE_COLUMNS and not col.startswith("extracted_data:"):
                    errors.append(
                        f"'{name}.{placeholder}': invalid source_column '{col}' in source_columns"
                    )
        else:
            errors.append(f"'{name}.{placeholder}': must have 'source_column' or 'source_columns' + 'template'")

    # Validate template placeholders match mapping keys
    template_placeholders = set(re.findall(r'\{(\w+)\}', template))
    mapping_keys = set(mapping.keys())

    missing_in_mapping = template_placeholders - mapping_keys
    if missing_in_mapping:
        errors.append(
            f"'{name}': template uses {missing_in_mapping} but they're not in dataset_mapping"
        )

    # Check template has a score pattern (warning, not fatal — alternative patterns may work)
    if not re.search(r'Score:\s*\[', template):
        import logging
        logging.getLogger("agent_eval.metric_generator").warning(
            "Metric '%s': template does not contain 'Score: [' pattern — "
            "the evaluation parser may not extract scores reliably.", name
        )

    return errors
