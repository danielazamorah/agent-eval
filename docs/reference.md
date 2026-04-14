# Reference Guide

Complete documentation for every `agent-eval` command, option, metric type, data format, and customization point.

For installation and getting started, see the [README](../README.md).

---

## Table of Contents

1. [CLI Reference](#cli-reference)
   - [init](#init)
   - [run](#run)
   - [simulate](#simulate)
   - [interact](#interact)
   - [evaluate](#evaluate)
   - [analyze](#analyze)
   - [convert](#convert)
   - [create-dataset](#create-dataset)
   - [dashboard](#dashboard)
2. [Metrics](#metrics)
   - [Deterministic Metrics](#deterministic-metrics)
   - [Managed Metrics (Vertex AI)](#managed-metrics-vertex-ai)
   - [Custom LLM-as-Judge Metrics](#custom-llm-as-judge-metrics)
3. [Creating Custom Metrics](#creating-custom-metrics)
   - [Basic Structure](#basic-structure)
   - [Dataset Mapping Constraint](#dataset-mapping-constraint)
   - [Available Source Columns](#available-source-columns)
   - [Metric Routing with applies_to](#metric-routing-with-applies_to)
   - [Combining Multiple Sources](#combining-multiple-sources)
   - [Structured Response Evaluation](#structured-response-evaluation)
   - [Binary Decomposition](#binary-decomposition)
   - [Example: Trajectory Accuracy](#example-trajectory-accuracy)
   - [Example: Tool Usage Quality](#example-tool-usage-quality)
4. [Interaction Modes](#interaction-modes)
   - [ADK User Sim](#adk-user-sim)
   - [DIY Interactions](#diy-interactions)
5. [Data Formats](#data-formats)
   - [Golden Dataset](#golden-dataset)
   - [Conversation Scenarios](#conversation-scenarios)
   - [Session Input](#session-input)
   - [Processed JSONL Fields](#processed-jsonl-fields)
6. [Output Files](#output-files)
   - [eval_summary.json](#eval_summaryjson)
   - [gemini_analysis.md](#gemini_analysismd)
   - [OPTIMIZATION_LOG.md](#optimization_logmd)
7. [Run Comparison](#run-comparison)
8. [Managed Metrics Catalog](#managed-metrics-catalog)
9. [Models and Pricing](#models-and-pricing)
10. [ADK Optimization Patterns](#adk-optimization-patterns)
11. [AI Assistant Integration](#ai-assistant-integration)
12. [Troubleshooting](#troubleshooting)

---

## CLI Reference

### init

Scaffolds the `eval/` folder structure for an ADK agent. Discovers `agent.py` files in the current directory tree and lets you select which agent to evaluate.

```bash
uv run agent-eval init
```

| Option | Default | Description |
|--------|---------|-------------|
| `--target-dir` | auto-detected | Directory containing agent.py (eval/ created here) |
| `--agent-name` | auto-detected | Agent module name |
| `--mode` | `both` | Interaction mode: `user-sim`, `diy`, or `both` |
| `--auto-approve`, `-y` | `false` | Skip interactive prompts, use defaults |
| `--ai-metrics` | `false` | Generate tailored metrics with AI (multi-step Gemini pipeline) |

#### AI-Powered Metric Generation

When you select "Generate with AI" in Step 3 (the default), or use `--ai-metrics` with `-y`, the CLI runs a multi-step pipeline:

1. **Managed metrics selection** — Discovers all available metrics from the Vertex AI SDK at runtime, displays them in a table, and lets you select which to include. Metrics are classified as server-side (API Predefined) or client-side (GCS YAML) with correct `use_gemini_format` settings applied automatically.

2. **Agent analysis** (Gemini Call 1) — Analyzes your agent's source code to identify tools, state variables, sub-agents, and key behaviors. This is a factual extraction step with minimal hallucination risk.

3. **Metric generation** (Gemini Call 2) — Generates custom LLM-as-judge metric definitions tailored to your agent, combining the analysis results with your evaluation priorities and selected managed metrics.

4. **Evaluation data generation** (Gemini Call 3) — Generates conversation scenarios and golden dataset entries based on your agent's capabilities and the metric definitions.

After each step you can accept, refine (re-run with updated priorities), or skip.

**Non-destructive updates:** If eval files already exist, they are backed up to `eval/.backup/<timestamp>/` before AI content is written. Scenarios and golden data are merged with existing entries.

```bash
# Interactive — choose AI generation in Step 3
uv run agent-eval init

# Non-interactive with AI metrics
uv run agent-eval init -y --ai-metrics
```

---

### run

Orchestrates the full evaluation pipeline in a single command: simulate, interact, evaluate, and analyze. Each phase can be toggled on/off.

```bash
uv run agent-eval run --agent-dir path/to/agent_module
```

| Option | Default | Description |
|--------|---------|-------------|
| `--agent-dir` | required | Path to agent module directory (containing agent.py) |
| `--eval-dir` | auto-detected | Path to eval/ directory |
| `--run-id` | prompted or timestamp | Name for the results folder |
| `--simulate/--no-simulate` | `--simulate` | Run ADK User Sim scenarios |
| `--interact/--no-interact` | `--interact` | Run DIY interactions (skipped if agent unreachable) |
| `--base-url` | `http://localhost:8501` | Agent API URL for interact mode |
| `--evaluate/--no-evaluate` | `--evaluate` | Run evaluation metrics |
| `--analyze/--no-analyze` | `--analyze` | Run AI-powered analysis |
| `--focus` | none | Metric names to highlight in analysis (e.g., `"latency, cache"`) |
| `--skip-gemini` | `false` | Skip AI-powered analysis in the analyze phase |
| `--app-name` | directory name | Agent app name for interact |
| `--questions-file` | auto-detected | Golden dataset JSON for interact mode |
| `--num-questions` | `-1` (all) | Limit number of questions for interact |
| `--skip-traces` | `false` | Skip trace retrieval in interact mode |
| `--dashboard/--no-dashboard` | prompt | Launch interactive dashboard after pipeline (prompts if gradio installed) |
| `--debug` | `false` | Show detailed logs from all phases |

**Graceful fallback:** If the agent is not reachable at `--base-url`, interact is skipped and the pipeline continues with simulation data.

**Dashboard integration:** After the pipeline completes, `run` checks if Gradio is installed. If so, it prompts to launch the interactive dashboard showing all runs in the results directory. Use `--dashboard` to auto-launch or `--no-dashboard` to skip.

---

### simulate

Runs the full ADK User Sim workflow: symlinks scenario files, clears stale traces, creates a fresh eval set, runs the simulation, and converts traces.

```bash
uv run agent-eval simulate --agent-dir path/to/agent_module
```

| Option | Default | Description |
|--------|---------|-------------|
| `--agent-dir` | required | Path to agent module directory |
| `--eval-dir` | auto-detected | Path to eval/ directory |
| `--run-id` | prompted or timestamp | Name for the results folder |
| `--debug` | `false` | Show ADK subprocess output and internal logs |

**What it does (5 steps):**

1. **Symlinks scenario files** — Creates symlinks for `session_input.json`, `conversation_scenarios.json`, and `eval_config.json` from `eval/scenarios/` into the agent module directory (ADK requires these next to `agent.py`)
2. **Clears eval history** — Removes `.adk/eval_history/` to avoid mixing stale traces
3. **Creates eval set** — Recreates the eval set from scratch (ADK's `add_eval_case` appends, so recreating avoids duplicates)
4. **Runs ADK User Sim** — Runs `adk eval` with an LLM simulating users following your scenarios
5. **Converts traces** — Converts OpenTelemetry traces to agent-eval's JSONL format

**Output:** `eval/results/<run-id>/raw/processed_interaction_sim.jsonl`

> ADK runs its own built-in LLM scoring during `adk eval`. The `simulate` command defaults to an empty `eval_config.json` (`{"criteria": {}}`) to skip this — `agent-eval` handles all scoring via the `evaluate` command instead.

---

### interact

Runs interactions against a live agent endpoint. Prompts interactively for any missing configuration.

```bash
uv run agent-eval interact --agent-dir path/to/agent_module
```

Before running, start your agent in a separate terminal:
- **ADK Starter Pack:** `cd path/to/agent && make playground` (port 8501)
- **Custom agents:** start your server on any port

| Option | Default | Description |
|--------|---------|-------------|
| `--agent-dir` | prompted | Agent module directory |
| `--app-name` | directory name | Agent application name |
| `--questions-file` | auto-detected | Golden dataset JSON (prompted if not found) |
| `--base-url` | prompted | Agent API URL |
| `--results-dir` | auto-detected | Output directory |
| `--run-id` | prompted | Name for results folder |
| `--user-id` | `eval_user` | User ID for session |
| `--runs` | `1` | Number of runs per question |
| `--debug` | `false` | Show detailed interaction and trace logs |

**Output:** `<results-dir>/<run-id>/raw/processed_interaction_<app_name>.jsonl`

---

### evaluate

Runs metrics on processed interaction data.

```bash
uv run agent-eval evaluate \
  --interaction-file path/to/interactions.jsonl \
  --metrics-files path/to/metric_definitions.json \
  --results-dir path/to/results
```

| Option | Default | Description |
|--------|---------|-------------|
| `--interaction-file` | required | Processed JSONL or CSV (can specify multiple times) |
| `--metrics-files` | required | Metric definition JSON (can specify multiple) |
| `--results-dir` | required | Output directory |
| `--input-label` | none | Run label (e.g., "baseline") |
| `--test-description` | none | Description for this run |
| `--debug` | `false` | Show Vertex AI SDK logs (retries, errors) |

**Combining data sources:** Specify `--interaction-file` multiple times to evaluate both simulation and DIY data together:

```bash
uv run agent-eval evaluate \
  --interaction-file results/run1/raw/processed_interaction_sim.jsonl \
  --interaction-file results/run1/raw/processed_interaction_app.jsonl \
  --metrics-files eval/metrics/metric_definitions.json \
  --results-dir results/run1
```

**Output:** `eval_summary.json`, `evaluation_results_*.csv`

> Both `simulate` and `interact` print the exact `evaluate` and `analyze` commands with correct paths at the end of their output. Just copy and paste them.

---

### analyze

Generates reports and AI-powered root cause analysis. Automatically compares against the previous evaluation run.

```bash
uv run agent-eval analyze \
  --results-dir eval/results/baseline \
  --agent-dir ./my_agent
```

| Option | Default | Description |
|--------|---------|-------------|
| `--results-dir` | required | Directory with eval results |
| `--agent-dir` | none | Agent source (adds context to AI analysis) |
| `--compare-to` | auto-detected | Previous run's results dir for comparison |
| `--focus` | none | Metric names to highlight (e.g., `"latency, cache"`) |
| `--strategy-file` | none | Optimization strategy markdown |
| `--report-audience` | none | Target audience for the report |
| `--report-tone` | none | Tone of the report |
| `--report-length` | none | Length of the report |
| `--model` | `gemini-3.1-pro-preview` | Gemini model for analysis |
| `--location` | `global` | Vertex AI region (use `global` for Gemini 3+ models) |
| `--skip-gemini` | `false` | Skip AI analysis, still generate metrics table |
| `--gcs-bucket` | none | GCS bucket for uploading results |
| `--debug` | `false` | Show Gemini API logs |

**Output:** `question_answer_log.md`, `gemini_analysis.md`, `OPTIMIZATION_LOG.md` (in parent results dir)

See [Run Comparison](#run-comparison) for details on how comparison works.

---

### convert

Converts ADK simulator history (`.adk/eval_history/`) to evaluation JSONL. Called automatically by `simulate` — only needed if you ran ADK manually.

```bash
uv run agent-eval convert \
  --agent-dir path/to/agent_module \
  --output-dir path/to/results
```

| Option | Default | Description |
|--------|---------|-------------|
| `--agent-dir` | required | Agent module containing `.adk/eval_history/` |
| `--output-dir` | `results/` | Output directory |
| `--questions-file` | none | Golden dataset for merging reference data |

---

### create-dataset

Converts ADK test files to golden dataset format.

```bash
uv run agent-eval create-dataset \
  --input path/to/test.json \
  --output path/to/golden.json \
  --agent-name my_agent
```

| Option | Default | Description |
|--------|---------|-------------|
| `--input` | required | Path to ADK test JSON |
| `--output` | required | Path for output golden dataset |
| `--agent-name` | required | Agent name for metadata |
| `--metadata` | none | Tags in `key:value` format |

---

### dashboard

Launches an interactive Gradio dashboard for comparing evaluation runs. Auto-discovers all runs in the results directory.

```bash
uv run agent-eval dashboard --results-dir eval/results/
```

| Option | Default | Description |
|--------|---------|-------------|
| `--results-dir` | required | Path to results directory containing run sub-folders |
| `--port` | `7860` | Port for the dashboard server |
| `--share` | `false` | Create a public Gradio share link |

**Requires optional dependencies:**

```bash
pip install agent-eval[dashboard]
# or: uv pip install gradio plotly
```

**Tabs:**

| Tab | Description |
|-----|-------------|
| Overview | Scorecards with delta % (Cost, Latency, Quality) + full metrics comparison table |
| Metrics Comparison | Grouped bar chart with run/metric selection and normalize toggle |
| Per-Question Drilldown | Score table with question_id rows and run columns, filtered by metric |
| Analysis | Renders gemini_analysis.md for any selected run |
| Raw Data | Full flattened DataFrame with all metrics and metadata |

Auto-selects the oldest run as baseline and the newest as compare target. All scorecards and tables update reactively when you change the baseline or compare run.

---

## Metrics

### Deterministic Metrics

Automatically calculated from OpenTelemetry session traces. No configuration needed.

| Metric Group | Key Fields | Description |
|-------------|------------|-------------|
| `token_usage` | `total_tokens`, `llm_calls`, `prompt_tokens`, `completion_tokens`, `estimated_cost_usd` | Token consumption and cost |
| `latency_metrics` | `total_seconds`, `llm_latency_seconds`, `tool_latency_seconds`, `first_response_seconds`, `avg_turn_latency` | Where time is spent |
| `cache_efficiency` | `hit_rate`, `cached_tokens`, `fresh_prompt_tokens` | KV-cache performance |
| `tool_success_rate` | `rate`, `failed_calls`, `failed_list` | Tool reliability |
| `thinking_metrics` | `reasoning_ratio`, `thinking_tokens` | Model reasoning analysis |
| `tool_utilization` | `total_calls`, `unique_tools`, `tool_counts` | Tool usage patterns |
| `grounding_utilization` | `chunks_used` | RAG grounding usage |
| `context_saturation` | `max_tokens`, `peak_span` | Context window utilization |
| `agent_handoffs` | `total`, `unique_agents`, `agents_list` | Sub-agent delegation |
| `output_density` | `avg_output_tokens` | Output verbosity |

### Managed Metrics (Vertex AI)

Built into the Vertex AI SDK, discovered at runtime by `agent-eval`. These require `is_managed: true` in the metric definition. The `init` command configures them automatically.

Managed metrics resolve via two distinct paths:

**Server-side (API Predefined)** — Evaluated on Google's servers. Use `use_gemini_format: true`. The SDK sends raw `request`/`response` Content objects; the server auto-extracts what it needs.

| Metric | Score | Description |
|--------|-------|-------------|
| `GENERAL_QUALITY` | 0-1 rubric | Overall response quality |
| `SAFETY` | 0-1 rubric | Safety and harmlessness |
| `HALLUCINATION` | 0-1 rubric | False claims detection |
| `TOOL_USE_QUALITY` | 0-1 rubric | Tool selection and arguments |
| `GROUNDING` | 0-1 rubric | Claims supported by context |
| `INSTRUCTION_FOLLOWING` | 1-5 pointwise | Adherence to instructions |
| `TEXT_QUALITY` | 1-5 pointwise | Writing quality and clarity |
| `FINAL_RESPONSE_MATCH` | 0-1 similarity | Response matches reference |
| `FINAL_RESPONSE_QUALITY` | 0-1 rubric | Final response quality (ADK) |
| `FINAL_RESPONSE_REFERENCE_FREE` | 0-1 rubric | Quality without reference (ADK) |
| `MULTI_TURN_GENERAL_QUALITY` | 0-1 rubric | Multi-turn conversation quality |
| `MULTI_TURN_TEXT_QUALITY` | 1-5 pointwise | Multi-turn text quality |

**Client-side (GCS YAML)** — Evaluated locally using an LLM-as-judge with templates downloaded from GCS. Use `use_gemini_format: false`. These need standard `prompt`/`response`/`reference` column mapping.

| Metric | Score | Description |
|--------|-------|-------------|
| `COHERENCE` | 1-5 pointwise | Logical flow and consistency |
| `FLUENCY` | 1-5 pointwise | Language fluency and naturalness |
| `GROUNDEDNESS` | 1-5 pointwise | Claims supported by context |
| `VERBOSITY` | -2 to 2 | Response length appropriateness |
| `SUMMARIZATION_QUALITY` | 1-5 pointwise | Summary coverage and accuracy |
| `QUESTION_ANSWERING_QUALITY` | 1-5 pointwise | QA accuracy and completeness |
| `MULTI_TURN_CHAT_QUALITY` | 0-1 rubric | Multi-turn conversation quality |
| `MULTI_TURN_SAFETY` | 0-1 rubric | Multi-turn safety |

> `agent-eval` automatically detects which resolution path each metric uses and applies the correct format. You don't need to worry about this when using `init` — it's handled for you.

**Choosing single-turn vs multi-turn:**

| Agent Pattern | Metrics to Use |
|---------------|----------------|
| User -> Agent (pipeline, single request) | `GENERAL_QUALITY`, `TEXT_QUALITY`, `INSTRUCTION_FOLLOWING` |
| User <-> Agent <-> User (back-and-forth) | `MULTI_TURN_GENERAL_QUALITY`, `MULTI_TURN_TEXT_QUALITY` |

> Using `MULTI_TURN_*` metrics on a single-turn agent causes: `"Variable conversation_history is required but not provided"`

### Custom LLM-as-Judge Metrics

Your own scoring rubrics, defined in `metric_definitions.json`. These use `metric_type: "llm"` and include a `template` with the evaluation prompt. See [Creating Custom Metrics](#creating-custom-metrics) below.

---

## Creating Custom Metrics

### Basic Structure

```json
{
  "metrics": {
    "my_metric": {
      "metric_type": "llm",
      "agents": ["my_agent"],
      "applies_to": "all",
      "score_range": {"min": 0, "max": 5, "description": "0=Fail, 5=Perfect"},
      "dataset_mapping": {
        "prompt": {"source_column": "user_inputs"},
        "response": {"source_column": "final_response"}
      },
      "template": "Evaluate the response.\n\n{prompt}\n{response}\n\nScore: [0-5]"
    }
  }
}
```

### Dataset Mapping Constraint

```
+------------------------------------------------------------------+
|  The Vertex AI Evaluation SDK only accepts three column names     |
|  in dataset_mapping:                                              |
|                                                                    |
|    prompt    — the user's request                                 |
|    response  — the agent's output                                 |
|    reference — supporting context (tools, state, etc.)            |
|                                                                    |
|  Using any other name will crash the SDK.                         |
|  Combine multiple data sources into these three columns.          |
+------------------------------------------------------------------+
```

> `prompt` and `response` are auto-populated from `user_inputs` and `final_response` if omitted from `dataset_mapping`. `reference` must be explicitly mapped when needed.

### Available Source Columns

These are the values you can use in `source_column`:

| Source | Description |
|--------|-------------|
| `user_inputs` | User messages (JSON list) |
| `final_response` | Agent's final text response (or structured JSON) |
| `trace_summary` | Execution trajectory |
| `extracted_data:tool_interactions` | Tool calls with inputs/outputs |
| `extracted_data:tool_declarations` | Available tools with descriptions |
| `extracted_data:state_variables` | Session state variables |
| `extracted_data:conversation_history` | Full multi-turn conversation |
| `extracted_data:sub_agent_trace` | Agent reasoning steps |
| `extracted_data:thinking_trace` | Detailed reasoning trace |
| `extracted_data:grounding_chunks` | Supporting context chunks |
| `extracted_data:<any_key>` | Any agent-specific state variable |

**Nested field access:** Use `:` to access nested fields:

```json
"response": {"source_column": "final_response:top_recommendation"}
```

### Metric Routing with applies_to

Controls which interaction data a metric runs on:

| `applies_to` | Runs on | Use when |
|---|---|---|
| `"all"` (default) | All data | Metric evaluates the response itself (safety, quality, tool use) |
| `"scenarios"` | Multi-turn data from `simulate` | Metric evaluates conversation flow or trajectory. No reference answers available. |
| `"golden_dataset"` | Single-turn data from `interact` | Metric compares against expected behavior. Reference answers available. |

**Why this matters:**
- **Scenarios** test conversational behavior (turn-by-turn coherence, trajectory). There's no "right answer" — metrics evaluate the agent's approach.
- **Golden dataset** queries include expected behavior, so metrics can check correctness.

**Recommendation:** Assign metrics that need reference data to `"golden_dataset"`, trajectory metrics to `"scenarios"`, and general quality/safety metrics to `"all"`.

### Combining Multiple Sources

When you need to evaluate against multiple data sources, combine them into the `reference` column using `template` + `source_columns`:

```json
"dataset_mapping": {
  "prompt": {"source_column": "user_inputs"},
  "response": {"source_column": "final_response"},
  "reference": {
    "template": "Available Tools: {extracted_data_tool_declarations}\n\nTool Calls: {extracted_data_tool_interactions}",
    "source_columns": ["extracted_data:tool_declarations", "extracted_data:tool_interactions"]
  }
}
```

**Rules:**
- `source_columns` lists the data sources to pull from
- `template` is a Python format string with `{variable}` placeholders
- Colons in source column names become underscores in template variables (e.g., `extracted_data:search_results` -> `{extracted_data_search_results}`)

### Structured Response Evaluation

When your agent returns structured JSON, access specific fields with `:` notation:

```json
"dataset_mapping": {
  "prompt": {"source_column": "user_inputs"},
  "response": {"source_column": "final_response:top_recommendation"}
}
```

This evaluates just the `top_recommendation` field from the JSON response, enabling fine-grained scoring of individual response components.

### Binary Decomposition

Instead of vague quality scores, break requirements into specific True/False assertions:

```json
"my_checklist_metric": {
  "metric_type": "llm",
  "score_range": {"min": 0, "max": 3, "description": "Sum of 3 binary checks"},
  "dataset_mapping": {
    "prompt": {"source_column": "user_inputs"},
    "response": {"source_column": "final_response"}
  },
  "template": "Evaluate the response.\n\nUser: {prompt}\nAgent: {response}\n\nChecklist:\n1. [_] Direct answer provided?\n2. [_] Solution offered?\n3. [_] Closing statement?\n\nMark [x] for each Yes. Sum the total.\n\nScore: [0-3]\nExplanation: [Show your checklist]"
}
```

This makes results auditable — the LLM shows its work.

### Example: Trajectory Accuracy

Evaluates whether the agent took the right execution path:

```json
{
  "trajectory_accuracy": {
    "metric_type": "llm",
    "agents": ["my_agent"],
    "applies_to": "scenarios",
    "score_range": {"min": 0, "max": 5, "description": "0=Wrong, 5=Perfect"},
    "dataset_mapping": {
      "prompt": {"source_column": "user_inputs"},
      "response": {"source_column": "trace_summary"},
      "reference": {"source_column": "extracted_data:tool_declarations"}
    },
    "template": "Evaluate the agent's execution trajectory.\n\n**User Request:**\n{prompt}\n\n**Agent Trajectory:**\n{response}\n\n**Available Tools:**\n{reference}\n\n**Scoring:**\n- 5: Perfect execution path\n- 3: Mostly correct with minor issues\n- 0: Completely wrong path\n\nCRITICAL: Only evaluate against tools that exist.\n\nScore: [0-5]\nExplanation: [Your reasoning]"
  }
}
```

### Example: Tool Usage Quality

Evaluates tool selection and argument quality using combined reference data:

```json
{
  "tool_use_quality": {
    "metric_type": "llm",
    "agents": ["my_agent"],
    "score_range": {"min": 0, "max": 5, "description": "0=Poor, 5=Excellent"},
    "dataset_mapping": {
      "prompt": {"source_column": "user_inputs"},
      "response": {"source_column": "final_response"},
      "reference": {
        "template": "Available Tools: {extracted_data_tool_declarations}\n\nTool Calls: {extracted_data_tool_interactions}",
        "source_columns": ["extracted_data:tool_declarations", "extracted_data:tool_interactions"]
      }
    },
    "template": "Evaluate tool usage.\n\n**Request:** {prompt}\n**Response:** {response}\n\n{reference}\n\n**Criteria:**\n1. Tool Selection: Were appropriate tools chosen?\n2. Arguments: Were parameters correct?\n3. Efficiency: Were calls non-redundant?\n\nScore: [0-5]\nExplanation:"
  }
}
```

### Tips for Custom Metrics

1. **Be specific** — Define exactly what each score level means
2. **Request structured output** — Use `Score: [X]` format for reliable parsing
3. **Include available_tools** — Prevents penalizing for non-existent tools
4. **Handle mock data** — Add "Do NOT penalize for mock data in test environments" to templates
5. **Use compound mapping** — For large state objects, select specific fields via `extracted_data:<key>`

---

## Interaction Modes

### ADK User Sim

Generates multi-turn conversations from scenario definitions. An LLM simulates realistic users following your conversation scripts.

**When to use:** Multi-turn conversational agents, rapid prototyping (no golden dataset needed), exploring agent behavior across many scenarios.

**Files needed:**

```
eval/scenarios/
├── conversation_scenarios.json   # Scenario definitions
├── session_input.json            # Session config (app_name, user_id)
└── eval_config.json              # ADK eval criteria (auto-created)
```

**Run it:**

```bash
uv run agent-eval simulate --agent-dir path/to/agent_module
```

The `simulate` command handles the full ADK workflow automatically.

### DIY Interactions

Sends queries from a golden dataset to a live agent endpoint. Responses and traces are captured as JSONL.

**When to use:** Single-turn pipeline agents, deployed/remote agents, regression testing with known-good responses.

**Run it:**

```bash
# Interactive — prompts for missing config
uv run agent-eval interact --agent-dir path/to/agent_module

# Non-interactive
uv run agent-eval interact \
  --agent-dir path/to/agent_module \
  --questions-file eval/eval_data/golden_dataset.json \
  --base-url http://localhost:8501 \
  --run-id baseline
```

---

## Data Formats

### Golden Dataset

For DIY interactions. Defines test queries with optional expected behavior:

```json
{
  "golden_questions": [
    {
      "id": "test_001",
      "user_inputs": ["I want to open a coffee shop in Seattle"],
      "agents_evaluated": ["app"],
      "reference_data": {
        "reference_tool_interactions": [
          {"tool_name": "IntakeAgent", "input_arguments": {"target_location": "Seattle"}}
        ],
        "reference_trajectory": ["app", "IntakeAgent", "LocationStrategyPipeline"],
        "expected_behavior": "Should run full location analysis pipeline"
      }
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique test case identifier |
| `user_inputs` | Yes | List of user messages (usually one for single-turn) |
| `agents_evaluated` | Yes | Which agents this test applies to |
| `reference_data` | No | Ground truth for comparison |

> Use `uv run agent-eval create-dataset` to convert ADK test files to this format.

### Conversation Scenarios

For ADK User Sim. Defines multi-turn conversation scripts:

```json
{
  "scenarios": [
    {
      "starting_prompt": "I need help with my order.",
      "conversation_plan": "Ask about order status. If asked for order ID, provide '12345'. Then ask about return policy."
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `starting_prompt` | First message the simulated user sends |
| `conversation_plan` | Natural language instructions for the conversation arc |

**Tips:** Be specific about user intent. Include conditional logic ("If asked for X, provide Y"). Cover edge cases.

### Session Input

```json
{
  "app_name": "my_agent_folder_name",
  "user_id": "eval_user"
}
```

**Critical:** `app_name` must match the **folder name** containing `agent.py`, not the agent's internal display name.

### Processed JSONL Fields

The evaluation pipeline produces JSONL with these fields:

| Field | Description | Used By |
|-------|-------------|---------|
| `question_id` | Unique test case ID | All metrics |
| `source_type` | `"simulation"` or `"interaction"` | Per-source summaries |
| `user_inputs` | User messages (JSON list) | LLM metrics |
| `final_response` | Agent's final response (text or JSON) | LLM metrics |
| `reference_data` | Ground truth (DIY mode only) | Reference metrics |
| `session_id` | Session UUID | Debugging |
| `extracted_data` | State, tools, traces, etc. | Custom metrics |
| `session_trace` | Full execution trace | Deterministic metrics |
| `trace_summary` | Simplified trajectory | Trajectory analysis |
| `request` | Gemini batch format request | Managed metrics (API Predefined) |
| `response` | Gemini batch format response | Managed metrics (API Predefined) |

---

## Output Files

Results are saved to `eval/results/<run-id>/`:

```
eval/results/<run-id>/
├── eval_summary.json           # START HERE — aggregated metrics
├── question_answer_log.md      # Per-question transcript with scores
├── gemini_analysis.md          # AI root cause analysis
└── raw/
    ├── processed_interaction_*.jsonl  # Converted traces
    ├── evaluation_results_*.csv       # Full results spreadsheet
    ├── gemini_prompt.txt              # Prompt sent to Gemini (debug)
    ├── session_*.json                 # Session state dumps
    └── trace_*.json                   # Execution trace dumps
```

### eval_summary.json

Primary output with aggregated metrics:

```json
{
  "experiment_id": "eval-20260127_143022",
  "run_type": "baseline",
  "test_description": "Baseline evaluation",
  "interaction_datetime": "2026-01-27T14:30:22.123456",
  "git_info": {
    "commit": "a1b2c3d4...",
    "branch": "main",
    "dirty": false
  },
  "overall_summary": {
    "deterministic_metrics": {
      "token_usage.total_tokens": 15420,
      "latency_metrics.total_seconds": 12.5,
      "tool_success_rate.rate": 1.0
    },
    "llm_based_metrics": {
      "trajectory_accuracy": 4.2,
      "general_quality": 0.85
    }
  },
  "per_question_summary": [...],
  "per_source_summary": {...}
}
```

**`git_info`:** Captured automatically during `evaluate`. Records the commit hash, branch, and whether there were uncommitted changes. The `analyze` command uses this to diff commits between runs and explain what code changes caused metric movements. For best results, commit your agent changes before each evaluation run.

**`per_source_summary`:** Generated when evaluating multiple data sources together. Shows per-source metric averages alongside the overall summary.

### gemini_analysis.md

AI-generated root cause analysis with:
- Critical issues ranked by impact
- File and line number references
- Optimization recommendations mapped to ADK design patterns
- Comparison analysis (when a previous run exists)

### OPTIMIZATION_LOG.md

Cumulative log maintained in the parent results directory (`eval/results/`). Each `analyze` run appends an iteration with metric deltas, git info, and comparison summary. Uses emoji indicators: improvement, regression, neutral.

---

## Run Comparison

The `analyze` command automatically compares against the most recent previous run. This powers:

1. **Terminal metrics table** — Shows baseline, current, and change columns. Metrics matching `--focus` keywords are highlighted with a marker.

2. **Two Gemini calls** — Call 1 diagnoses the current run. Call 2 analyzes what changed between runs using `git diff`. Both are combined into `gemini_analysis.md`.

3. **OPTIMIZATION_LOG.md** — Cumulative log with iteration history.

**Direction classification:** Metrics are classified as "lower is better" (tokens, latency, cost, failed calls) or "higher is better" (quality scores, cache hit rate). Changes under 1% are marked neutral.

**Smart comparison skip:** If both runs share the same git commit and no code diff is detected, the comparison Gemini call is skipped to avoid wasting API calls analyzing LLM non-determinism.

**Override auto-detection:**

```bash
uv run agent-eval analyze --results-dir eval/results/v3 --compare-to eval/results/v1
```

---

## Managed Metrics Catalog

`agent-eval` discovers managed metrics from the installed Vertex AI SDK at runtime via the `metric_discovery` module. This ensures you always have access to the latest metrics without manual updates.

The discovery process:
1. Reads all attributes from `vertexai.types.RubricMetric` (20+ `LazyLoadedPrebuiltMetric` objects)
2. Checks each against `SUPPORTED_PREDEFINED_METRICS` to classify as server-side (API Predefined) or client-side (GCS YAML)
3. Applies the correct `use_gemini_format` setting automatically

A static fallback catalog (`src/agent_eval/managed_metrics_catalog.json`) is included as reference but is deprecated in favor of runtime discovery.

---

## Models and Pricing

### Analysis Models

The `analyze` command uses Gemini for AI-powered analysis. Default: `gemini-3.1-pro-preview` (requires `global` region, auto-configured).

| Model | Region | Status |
|-------|--------|--------|
| `gemini-3.1-pro-preview` | `global` | **Default** |
| `gemini-3-flash-preview` | `global` | Active (faster, lower cost) |
| `gemini-2.5-pro` | `us-central1` | Sunsetting June 2026 |
| `gemini-2.5-flash` | `us-central1` | Sunsetting June 2026 |

Override with `--model` and `--location`:

```bash
uv run agent-eval analyze --results-dir eval/results/v2 --model gemini-3-flash-preview
```

### Cost Estimation

The `evaluate` command estimates per-run cost using model pricing stored in `src/agent_eval/core/deterministic_metrics.py`. Current pricing (April 2026):

| Model | Input / 1M tokens | Output / 1M tokens |
|-------|-------------------|---------------------|
| `gemini-3.1-pro` | $2.00 | $12.00 |
| `gemini-3-flash` | $0.50 | $3.00 |
| `gemini-2.5-pro` | $1.25 | $10.00 |
| `gemini-2.5-flash` | $0.30 | $2.50 |
| `gemini-2.0-flash` | $0.15 | $0.60 |

Source: [Vertex AI Generative AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)

---

## ADK Optimization Patterns

The `analyze` command includes ADK-specific design patterns in its Gemini prompt, enabling actionable recommendations with code examples. These patterns are bundled in `src/agent_eval/core/adk_optimization_patterns.py` and cover:

- **Tool design** — Error handling, output truncation, docstring constraints
- **Agent architecture** — Sub-agent isolation, sequential/parallel pipelines
- **Prompt engineering** — Capability constraints, clarification rules
- **State & context management** — Initialization, compaction
- **Model configuration** — Temperature, determinism

Recommendations map evaluation signals (e.g., high latency, low tool grounding) to the five **Context Engineering Principles**: Offload, Reduce, Retrieve, Isolate, Cache.

| Signal | Metric to Check | Recommended Fix |
|--------|-----------------|-----------------|
| Agent invents capabilities | `capability_honesty` < 3.0 | Add `KNOWN LIMITATIONS` to tool docstrings |
| Agent takes wrong paths | `trajectory_accuracy` < 3.0 | Isolate into specialized sub-agents |
| Tools called with bad args | `tool_use_quality` < 3.0 | Add Pydantic schemas, stricter types |
| High latency, bloated context | `prompt_tokens` > 10K | Compact stale tool outputs, offload to disk |
| Agent fabricates data on failure | `pipeline_integrity` < 3.0 | Add circuit breaker checks |
| Low cache hits | `cache_hit_rate` < 50% | Put static instructions in `global_instruction` |

---

## AI Assistant Integration

This repository includes context files for AI coding assistants:

- **`CLAUDE.md`** — Loaded automatically by Claude Code
- **`GEMINI.md`** — Loaded automatically by Gemini CLI

These provide project context so assistants can give relevant advice when you share evaluation results.

### Gemini CLI

```bash
npm install -g @google/gemini-cli
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=true
gemini  # Run from project root
```

### Claude Code

```bash
npm install -g @anthropic-ai/claude-code

# Option A: Vertex AI
export ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
export CLOUD_ML_REGION=us-central1

# Option B: API Key
export ANTHROPIC_API_KEY=your-api-key

claude  # Run from project root
```

### Tips

1. **Share data** — Paste `eval_summary.json` and `gemini_analysis.md` for data-driven help
2. **Be specific** — "Improve trajectory_accuracy by fixing tool selection" beats "make it better"
3. **Iterate** — Run eval -> share results -> get suggestions -> implement -> repeat

### Dashboard

For visual, interactive comparison of evaluation runs:

```bash
uv run agent-eval dashboard --results-dir eval/results/
# Open http://127.0.0.1:7860
```

Requires: `pip install agent-eval[dashboard]`. See the [dashboard](#dashboard) CLI reference for all options.

---

## Troubleshooting

### Token usage shows all zeros

**Cause:** `app_name` in `session_input.json` doesn't match the folder name containing `agent.py`.
**Fix:** Update `app_name` to match the folder name, not the agent's display name.

### "Variable conversation_history is required"

**Cause:** Using `MULTI_TURN_*` metrics on a single-turn agent.
**Fix:** Use `GENERAL_QUALITY` instead of `MULTI_TURN_GENERAL_QUALITY`.

### Empty metrics / all scores are zero

**Cause:** Using `GOOGLE_API_KEY` instead of Vertex AI.
**Fix:** Remove `GOOGLE_API_KEY` and set `GOOGLE_CLOUD_PROJECT` instead.

### "ModuleNotFoundError"

**Cause:** Running from the wrong directory.
**Fix:** `cd` to the directory containing the agent module before running commands.

### ADK evaluation shows stale results

**Cause:** Didn't clear `eval_history` before running.
**Fix:** Use `uv run agent-eval simulate` which clears eval_history automatically. If running ADK manually: `rm -rf agent_module/.adk/eval_history/*`

### Vertex AI authentication errors

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT
```

### Permission denied on autorater model

**Cause:** Vertex AI service account lacks permissions.
**Fix:**

```bash
export PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/aiplatform.serviceAgent"
```

### Gemini model location errors

**Cause:** Gemini 3+ models require `global` region.
**Fix:** Use `--location global`. The default model (`gemini-3.1-pro-preview`) auto-configures to `global`.

### ADK UserSim: "Error rendering metric prompt template"

**Cause:** ADK runs its own built-in LLM scoring during `adk eval`, which is separate from `agent-eval`.
**Fix:** The `simulate` command defaults to an empty `eval_config.json` (`{"criteria": {}}`) which skips ADK's scoring. `agent-eval` handles all scoring via the `evaluate` command instead.

### Trajectory accuracy penalizing for missing tools

**Cause:** LLM judge expects tools that don't exist.
**Fix:** Include `extracted_data:tool_declarations` in your metric's `reference` mapping, and add "CRITICAL: Only evaluate against AVAILABLE tools listed above" to the template.

### Mock data being penalized

**Cause:** Test environments return mock data.
**Fix:** Add to your metric template: "Do NOT penalize the agent for correctly relaying mock data in test environments."

### Using --debug

Add `--debug` to any command to see detailed logs from ADK, Vertex AI SDK, and other services. By default, third-party logs are suppressed to keep the CLI output clean.

```bash
uv run agent-eval run --agent-dir ./my_agent --debug
```

---

## Additional Resources

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK User Simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/docs/generative-ai/evaluation/)
- [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)
