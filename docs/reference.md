# Agent Evaluation Reference Guide

Complete documentation for the `agent-eval` CLI, metrics, data formats, and customization.

---

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Metrics Overview](#metrics-overview)
3. [CLI Reference](#cli-reference)
4. [Interaction Modes](#interaction-modes)
5. [Metrics Deep Dive](#metrics-deep-dive)
6. [Creating Custom Metrics](#creating-custom-metrics)
7. [Structured Response Evaluation](#structured-response-evaluation)
8. [Output Files](#output-files)
9. [Data Formats](#data-formats)
10. [Adapting for Your Own Agent](#adapting-for-your-own-agent)
11. [Creating Custom Simulations](#creating-custom-simulations)
12. [Troubleshooting](#troubleshooting)
13. [AI Assistant Setup](#ai-assistant-setup)

---

## Environment Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10–3.12 | Python 3.13+ not yet supported |
| uv | Latest | Package manager |
| gcloud CLI | Latest | Google Cloud authentication |
| Vertex AI API | Enabled | Required for evaluation metrics |

### Required IAM Permissions

- `roles/aiplatform.user` — For running evaluations
- `roles/resourcemanager.projectIamAdmin` — For quota project setup

### Critical: Vertex AI Configuration

```
+------------------------------------------------------------------+
|  WARNING: You MUST use Vertex AI, not API keys                    |
|                                                                   |
|  Set these environment variables:                                 |
|    GOOGLE_CLOUD_PROJECT=your-project-id                          |
|    GOOGLE_CLOUD_LOCATION=us-central1                             |
|                                                                   |
|  DO NOT use GOOGLE_API_KEY                                        |
|                                                                   |
|  Why? The evaluation pipeline extracts metrics from Vertex AI    |
|  traces. API keys bypass Vertex AI, resulting in empty metrics.  |
+------------------------------------------------------------------+
```

### Dependency Management

The repository contains the `agent-eval` CLI package and example agents, each with their own dependencies:

```
agent-eval/
├── pyproject.toml                       # agent-eval CLI tool
├── uv.lock
├── tutorial/example_agents/
│   ├── customer-service/                # Example: multi-turn agent
│   │   ├── pyproject.toml
│   │   └── uv.lock
│   └── retail-ai-location-strategy/     # Example: single-turn pipeline
│       ├── pyproject.toml
│       └── uv.lock
```

**Why separate?**
- `agent-eval` is a **standalone CLI tool** that can evaluate any ADK agent
- Example agent folders contain the agents themselves with their own dependencies
- This separation allows you to use `agent-eval` with agents from other repositories

---

## Metrics Overview

`agent-eval` produces two categories of metrics. Understanding them upfront makes the rest of this guide easier to follow.

### Deterministic Metrics (automatic)

Extracted directly from OpenTelemetry traces — no configuration needed. These are the same for every agent:

| Metric Group | What you learn | Key fields |
|-------------|---------------|------------|
| **Token Usage** | How many tokens the agent consumes and estimated cost | `total_tokens`, `prompt_tokens`, `estimated_cost_usd` |
| **Latency** | Where time is spent (LLM, tools, overhead) | `total_latency_seconds`, `llm_latency_seconds`, `tool_latency_seconds` |
| **Cache Efficiency** | Is your prompt structured for KV-cache hits? | `cache_hit_rate`, `cached_tokens`, `fresh_prompt_tokens` |
| **Tool Reliability** | How often tool calls succeed vs fail | `tool_success_rate`, `failed_tool_calls` |
| **Thinking** | How much the model reasons before responding | `reasoning_ratio`, `thinking_tokens` |

### LLM-as-Judge Metrics (configurable)

Scored by Vertex AI Evaluation using rubrics you define in `eval/metrics/metric_definitions.json`. The `init` command creates starter metrics; you customize them for your agent.

| Default Metric | What it scores | Score Range |
|---------------|---------------|-------------|
| `general_quality` | Overall response quality (managed by Vertex AI) | 0–1 |
| `trajectory_accuracy` | Did the agent take the right execution path? | 0–5 |
| `tool_use_quality` | Were tool arguments correct and calls efficient? | 0–5 |
| `safety` | Safety compliance (managed by Vertex AI) | 0–1 |

You can define **custom metrics** with your own scoring rubrics — see [Creating Custom Metrics](#creating-custom-metrics) below.

> **Important:** Each metric has a `dataset_mapping` that controls which trace fields the LLM judge receives. If a metric scores unexpectedly low (e.g., 0.0), it often means the mapping points to the wrong field — not that your agent is broken. Always validate your metrics alongside your agent.

---

## CLI Reference

### All Commands

| Command | Purpose | Mode |
|---------|---------|------|
| \`uv run agent-eval init` | Scaffold eval folder structure | Setup |
| \`uv run agent-eval run` | Full pipeline: simulate + interact + evaluate + analyze | Both |
| \`uv run agent-eval simulate` | Run ADK User Sim + convert traces | ADK User Sim |
| \`uv run agent-eval interact` | Run interactions against live agent | DIY Interactions |
| \`uv run agent-eval evaluate` | Run metrics on interactions | Both |
| \`uv run agent-eval analyze` | Generate reports and AI analysis | Both |
| \`uv run agent-eval convert` | Convert ADK traces to JSONL (used by simulate) | ADK User Sim |
| \`uv run agent-eval create-dataset` | Convert test files to Golden Dataset | DIY Interactions |

### \`uv run agent-eval init`

Scaffolds the `eval/` folder structure for an ADK agent. Automatically discovers `agent.py` files in the current directory tree and lets you select which agent to add evaluation to. The `eval/` folder is created inside the agent module directory, as a sibling to `agent.py`.

```bash
uv run agent-eval init
```

| Option | Default | Description |
|--------|---------|-------------|
| `--target-dir` | (auto-detected) | Directory containing agent.py (eval/ created here) |
| `--agent-name` | (auto-detected) | Agent module name |
| `--mode` | (prompted) | Interaction mode: `user-sim`, `diy`, or `both` |
| `--auto-approve`, `-y` | `false` | Skip interactive prompts, use defaults |

### \`uv run agent-eval run`

Orchestrates the full evaluation pipeline in a single command: simulate, interact, evaluate, and analyze. By default, all four phases run. If the agent is not reachable at `--base-url`, the interact phase is skipped gracefully.

```bash
# Full pipeline (simulate + interact + evaluate + analyze)
uv run agent-eval run --agent-dir agents/my-agent/app

# Skip interact (simulation only)
uv run agent-eval run --agent-dir agents/my-agent/app --no-interact

# With focus highlighting in analysis
uv run agent-eval run --agent-dir agents/my-agent/app --focus "latency, cache"
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--agent-dir` | Yes | — | Path to agent module directory (containing agent.py) |
| `--eval-dir` | No | (auto-detected) | Path to eval/ directory |
| `--run-id` | No | (prompted, or timestamp) | Name for the results folder |
| `--simulate/--no-simulate` | No | `--simulate` | Run ADK User Sim scenarios |
| `--interact/--no-interact` | No | `--interact` | Run DIY interactions against live agent (skipped gracefully if unreachable) |
| `--base-url` | No | `http://localhost:8501` | Agent API URL for interact mode |
| `--evaluate/--no-evaluate` | No | `--evaluate` | Run evaluation metrics after collecting data |
| `--analyze/--no-analyze` | No | `--analyze` | Run AI-powered analysis after evaluation |
| `--focus` | No | — | Developer focus for analysis: metric names to highlight (e.g., `"latency, cache"`) |
| `--skip-gemini` | No | `false` | Skip AI-powered analysis in the analyze phase |
| `--app-name` | No | dir name | Agent app name for interact |
| `--questions-file` | No | auto-detected | Golden dataset JSON for interact mode |
| `--num-questions` | No | `-1` (all) | Limit number of questions for interact |
| `--skip-traces` | No | `false` | Skip trace retrieval in interact mode |

**Graceful fallback:** If the agent is not reachable at `--base-url`, the interact phase is skipped automatically and the pipeline continues with simulation data. If simulate fails but interact succeeds, evaluation proceeds with interaction data only.

**Output:** All interaction files are saved to `eval/results/<run-id>/raw/`, evaluation results and analysis go to `eval/results/<run-id>/`.

### \`uv run agent-eval simulate`

Runs the full ADK User Sim workflow in a single command: creates symlinks so ADK can find scenario files, clears previous traces, sets up a fresh eval set, runs the simulation, and converts traces to agent-eval format.

```bash
uv run agent-eval simulate --agent-dir <path-to-agent-module>
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--agent-dir` | Yes | — | Path to agent module directory (containing agent.py) |
| `--eval-dir` | No | (auto-detected) | Path to eval/ directory |
| `--run-id` | No | (prompted, or timestamp) | Name for the results folder (e.g., "baseline") |

**What it does (5 steps):**

1. **Symlink scenario files** — Creates symlinks for `session_input.json`, `conversation_scenarios.json`, and `eval_config.json` from `eval/scenarios/` into the agent module directory (ADK requires these next to `agent.py`)
2. **Clear eval history** — Removes `.adk/eval_history/` to avoid mixing stale traces with new results
3. **Create eval set** — Recreates the eval set from scratch and loads your scenarios (ADK's `add_eval_case` appends, so recreating avoids duplicates)
4. **Run ADK User Sim** — Runs `adk eval` which has an LLM simulate users following your scenario scripts
5. **Convert traces** — Converts the resulting OpenTelemetry traces to agent-eval's JSONL format

**Output:** `eval/results/<timestamp>/raw/processed_interaction_sim.jsonl`

> **Note:** ADK's built-in eval runs a limited set of metrics (hallucination, safety). The `evaluate` command adds deterministic metrics (latency, tokens, cost, cache efficiency) and custom LLM-as-judge metrics via Vertex AI Evaluation. This also means agent-eval is not locked to ADK — you can run `evaluate` and `analyze` on traces from any agent framework.

### \`uv run agent-eval convert`

Converts ADK simulator history (`.adk/eval_history/`) to evaluation JSONL. This is called automatically by `simulate` — you only need this if you ran ADK manually.

```bash
uv run agent-eval convert \
  --agent-dir <path-to-agent-module> \
  --output-dir <path-to-results>
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--agent-dir` | Yes | — | Agent module containing `.adk/eval_history/` |
| `--output-dir` | No | `results/` | Output directory |
| `--questions-file` | No | — | Golden dataset for merging reference data |

**Output:** `<output-dir>/<timestamp>/raw/processed_interaction_sim.jsonl`

### \`uv run agent-eval interact`

Runs interactions against a live agent endpoint. Prompts interactively for any missing configuration.

```bash
# Interactive — prompts for questions file, base URL, run ID:
uv run agent-eval interact --agent-dir path/to/agent_module

# Non-interactive — all options provided:
uv run agent-eval interact \
  --agent-dir path/to/agent_module \
  --questions-file path/to/golden_dataset.json \
  --base-url http://localhost:8501 \
  --run-id baseline
```

Before running, start your agent in a separate terminal:
- **ADK Starter Pack:** `cd path/to/agent && make playground` (port 8501)
- **Custom agents:** start your server on any port

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--agent-dir` | No | — | Agent module directory (prompted if omitted) |
| `--app-name` | No | dir name | Agent application name |
| `--questions-file` | No | auto-detected | Golden Dataset JSON (prompted if not found) |
| `--base-url` | No | prompted | Agent API URL (prompted if omitted) |
| `--results-dir` | No | auto-detected | Output directory |
| `--run-id` | No | prompted | Name for results folder (prompted if omitted) |
| `--user-id` | No | `eval_user` | User ID for session |
| `--runs` | No | `1` | Number of runs per question |

**Output:** `<results-dir>/<run-id>/raw/processed_interaction_<app_name>.jsonl`

### \`uv run agent-eval evaluate`

Runs metrics on processed interaction data.

```bash
uv run agent-eval evaluate \
  --interaction-file <path-to-jsonl> \
  --metrics-files <path-to-metrics.json> \
  --results-dir <path-to-results>
```

**Combining simulation + DIY results:** Specify `--interaction-file` multiple times to evaluate both data sources together:

```bash
uv run agent-eval evaluate \
  --interaction-file results/run1/raw/processed_interaction_sim.jsonl \
  --interaction-file results/run1/raw/processed_interaction_app.jsonl \
  --metrics-files eval/metrics/metric_definitions.json \
  --results-dir results/run1
```

| Option | Required | Description |
|--------|----------|-------------|
| `--interaction-file` | Yes | Path to processed JSONL or CSV (can specify multiple times) |
| `--metrics-files` | Yes | Metric definition JSON (can specify multiple) |
| `--results-dir` | Yes | Output directory (use same timestamp folder) |
| `--input-label` | No | Run label (e.g., "baseline") |
| `--test-description` | No | Description for this run |

**Output:** `eval_summary.json`, `evaluation_results_*.csv`

### \`uv run agent-eval analyze`

Generates reports and AI-powered root cause analysis. Automatically compares against the previous evaluation run, displays a terminal metrics table, and maintains a cumulative `OPTIMIZATION_LOG.md`.

```bash
# Basic analysis (auto-compares to previous run if available)
uv run agent-eval analyze --results-dir eval/results/baseline --agent-dir ./my_agent

# With developer focus (highlights specific metrics)
uv run agent-eval analyze --results-dir eval/results/v2 --focus "latency, cache"

# Compare to a specific previous run
uv run agent-eval analyze --results-dir eval/results/v3 --compare-to eval/results/v1
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--results-dir` | Yes | — | Directory with eval results |
| `--agent-dir` | No | — | Agent source (adds context to AI analysis) |
| `--compare-to` | No | (auto-detected) | Previous run's results dir for comparison |
| `--focus` | No | — | Metric names to highlight + analysis priority (e.g., `"latency, cache"`) |
| `--strategy-file` | No | — | Optimization strategy markdown |
| `--report-audience` | No | — | Target audience for the analysis report |
| `--report-tone` | No | — | Tone of the analysis report |
| `--report-length` | No | — | Length of the analysis report |
| `--model` | No | `gemini-3.1-pro-preview` | Gemini model for analysis |
| `--location` | No | `global` | Vertex AI region (use `global` for Gemini 3+ models) |
| `--skip-gemini` | No | `false` | Skip AI analysis |
| `--gcs-bucket` | No | — | GCS bucket for upload |

**Output:** `question_answer_log.md`, `gemini_analysis.md`, `OPTIMIZATION_LOG.md` (in parent results dir)

#### Comparing Runs

The analyze command automatically compares your current evaluation against the most recent previous run in the same results directory. This powers three features:

1. **Terminal metrics table** — A Rich table showing all metrics with baseline, current, and change columns. Metrics matching `--focus` keywords are highlighted in bold cyan with a ★ marker, making the table screenshot-friendly for sharing with leadership.

2. **Two Gemini calls** — Call 1 diagnoses the current run. Call 2 analyzes *what changed* between runs: which code changes (via `git diff`) caused which metric movements. Both are combined into `gemini_analysis.md`.

3. **OPTIMIZATION_LOG.md** — A cumulative log in the parent results directory. The first run creates a baseline entry; subsequent runs append iterations with metric deltas (🟢 improvement / 🔴 regression / ⚪ neutral), git info, and Gemini's comparison summary.

**Direction classification:** Metrics are classified as "lower is better" (tokens, latency, cost, failed calls) or "higher is better" (quality scores, cache hit rate). Changes under 1% are marked neutral.

**Override auto-detection:** Use `--compare-to` to compare against a specific previous run instead of the most recent one.

### \`uv run agent-eval create-dataset`

Converts ADK test files to Golden Dataset format.

```bash
uv run agent-eval create-dataset \
  --input <path-to-test.json> \
  --output <path-to-golden.json> \
  --agent-name <agent_name>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--input` | Yes | Path to ADK test JSON |
| `--output` | Yes | Path for output Golden Dataset |
| `--agent-name` | Yes | Agent name for metadata |
| `--metadata` | No | Add tags (format: `key:value`) |

---

## Interaction Modes

The evaluation framework supports two ways to generate agent interactions:

### ADK User Sim

Use the ADK simulator to generate multi-turn conversations from scenario definitions. This solves the **cold start problem** — you don't need hand-crafted golden datasets to start evaluating.

**How it works:**
1. Define conversation scenarios (intent + plan)
2. ADK uses an LLM to simulate a realistic user following your plan
3. The agent responds naturally to the simulated user
4. Traces are captured and converted to evaluation format

**Run it:**
```bash
uv run agent-eval simulate --agent-dir path/to/agent_module
```

The `simulate` command handles the full workflow: symlinks scenario files for ADK, clears stale traces, creates a fresh eval set, runs the simulation, and converts traces automatically.

**When to use:**
- Development and rapid iteration
- Testing conversation flows without reference answers
- Exploring agent behavior across many scenarios
- You don't have a golden dataset yet
- Multi-turn conversational agents

**Files needed:**
```
agent_module/eval/scenarios/
├── conversation_scenarios.json   # Scenario definitions
├── session_input.json            # Session config (app_name, user_id)
└── eval_config.json              # ADK eval criteria (auto-created if missing)
```

### DIY Interactions

Run interactions against a live agent endpoint. Use when you have specific queries or when the agent is a single-turn pipeline.

**How it works:**
1. Create a Golden Dataset with queries and expected responses
2. Start your agent (`make playground` for ADK Starter Pack, port 8501)
3. Run `uv run agent-eval interact --agent-dir path/to/agent_module` — it prompts for any missing config
4. Responses and traces are captured as JSONL

**When to use:**
- Single-turn pipeline agents (ADK User Sim is overkill)
- Testing deployed or remote agents
- Regression testing with known good responses
- Validating against specific expected answers
- Any agent accessible via URL (localhost, cloud, remote)

### Choosing the Right Mode

| Agent Type | Recommended Mode | Why |
|------------|------------------|-----|
| Multi-turn chatbot | ADK User Sim | Tests dialogue flow, explores edge cases |
| Single-turn pipeline | DIY Interactions | Faster, no conversation to simulate |
| Deployed agent | DIY Interactions | Works with any URL |
| Rapid prototyping | ADK User Sim | No golden dataset needed |

---

## Metrics Deep Dive

### Metric Types

| Type | Configuration | Auto-calculated |
|------|---------------|-----------------|
| **Deterministic** | None needed | Yes |
| **API Predefined** | `is_managed: true` | No |
| **Custom LLM** | `template: "..."` | No |

### Deterministic Metrics

Automatically calculated from session traces:

| Metric | Fields | Description |
|--------|--------|-------------|
| `token_usage` | `total_tokens`, `llm_calls`, `estimated_cost` | Token consumption |
| `latency_metrics` | `total_seconds`, `first_response`, `avg_turn` | Timing data |
| `cache_efficiency` | `hit_rate`, `cached_tokens`, `fresh_tokens` | KV-cache performance |
| `thinking_metrics` | `reasoning_ratio`, `thinking_tokens` | Reasoning analysis |
| `tool_utilization` | `total_calls`, `unique_tools`, `tool_counts` | Tool usage |
| `tool_success_rate` | `rate`, `failed_calls`, `failed_list` | Tool reliability |
| `grounding_utilization` | `chunks_used` | RAG grounding |
| `context_saturation` | `max_tokens`, `peak_span` | Context window usage |
| `agent_handoffs` | `total`, `unique_agents`, `agents_list` | Sub-agent calls |
| `output_density` | `avg_output_tokens` | Output verbosity |

### API Predefined Metrics (Vertex AI)

| Metric | Agent Type | Description |
|--------|------------|-------------|
| `GENERAL_QUALITY` | Single-turn | Overall response quality |
| `TEXT_QUALITY` | Single-turn | Text coherence |
| `MULTI_TURN_GENERAL_QUALITY` | Multi-turn | Conversation quality |
| `MULTI_TURN_TEXT_QUALITY` | Multi-turn | Multi-turn coherence |
| `INSTRUCTION_FOLLOWING` | Both | Instruction adherence |
| `GROUNDING` | Both | Factual accuracy |
| `SAFETY` | Both | Safety compliance |
| `HALLUCINATION` | Both | Hallucination detection |

**Example Configuration:**
```json
{
  "general_quality": {
    "metric_type": "llm",
    "is_managed": true,
    "managed_metric_name": "GENERAL_QUALITY",
    "use_gemini_format": true,
    "score_range": {"min": 0, "max": 1},
    "natural_language_guidelines": "Evaluate response quality..."
  }
}
```

### Single-Turn vs Multi-Turn

Choose based on your agent's conversation pattern:

| Agent Pattern | Metrics to Use |
|---------------|----------------|
| User ↔ Agent ↔ User ↔ Agent (back-and-forth) | `MULTI_TURN_GENERAL_QUALITY`, `MULTI_TURN_TEXT_QUALITY` |
| User → Agent pipeline → Response | `GENERAL_QUALITY`, `TEXT_QUALITY` |

> **Error:** Using `MULTI_TURN_*` on a pipeline agent causes: `"Variable conversation_history is required but not provided"`

---

## Creating Custom Metrics

### Basic Structure

```json
{
  "metrics": {
    "my_metric": {
      "metric_type": "llm",
      "agents": ["my_agent"],
      "score_range": {"min": 0, "max": 5, "description": "0=Fail, 5=Perfect"},
      "dataset_mapping": {
        "prompt": {"source_column": "user_inputs"},
        "response": {"source_column": "final_response"}
      },
      "template": "Evaluate...\n\n{prompt}\n{response}\n\nScore: [0-5]"
    }
  }
}
```

### Dataset Mapping Sources

| Source | Description |
|--------|-------------|
| `user_inputs` | User messages (JSON list) |
| `final_response` | Agent's final text response (or structured JSON) |
| `trace_summary` | Execution trajectory |
| `extracted_data:tool_interactions` | Tool calls with inputs/outputs |
| `extracted_data:tool_declarations` | Available tools |
| `extracted_data:state_variables` | Session state |
| `extracted_data:conversation_history` | Full conversation |
| `extracted_data:<any_state_var>` | Agent-specific state |

### Nested Field Access with `:`

Use `:` to access nested fields within JSON responses:

```json
"dataset_mapping": {
  "location": {"source_column": "extracted_data:target_location"},
  "recommendation": {"source_column": "final_response:top_recommendation"}
}
```

### Example: Trajectory Accuracy

```json
{
  "trajectory_accuracy": {
    "metric_type": "llm",
    "agents": ["my_agent"],
    "score_range": {"min": 0, "max": 5, "description": "0=Wrong, 5=Perfect"},
    "dataset_mapping": {
      "prompt": {"source_column": "user_inputs"},
      "response": {"source_column": "trace_summary"},
      "available_tools": {"source_column": "extracted_data:tool_declarations"}
    },
    "template": "Evaluate the agent's execution trajectory.\n\n**User Request:**\n{prompt}\n\n**Agent Trajectory:**\n{response}\n\n**Available Tools:**\n{available_tools}\n\n**Scoring:**\n- 5: Perfect execution\n- 3: Mostly correct with minor issues\n- 0: Completely wrong\n\nCRITICAL: Only evaluate against tools that exist. Do NOT penalize for missing tools.\n\nScore: [0-5]\nExplanation: [Your reasoning]"
  }
}
```

### Example: Tool Usage Quality

```json
{
  "tool_use_quality": {
    "metric_type": "llm",
    "agents": ["my_agent"],
    "score_range": {"min": 0, "max": 5, "description": "0=Poor, 5=Excellent"},
    "dataset_mapping": {
      "prompt": {"source_column": "user_inputs"},
      "response": {"source_column": "final_response"},
      "tool_interactions": {"source_column": "extracted_data:tool_interactions"},
      "available_tools": {"source_column": "extracted_data:tool_declarations"}
    },
    "template": "Evaluate tool usage.\n\n**Request:** {prompt}\n**Available Tools:** {available_tools}\n**Tool Calls:** {tool_interactions}\n**Response:** {response}\n\n**Criteria:**\n1. Tool Selection: Were appropriate tools chosen?\n2. Arguments: Were parameters correct?\n3. Efficiency: Were calls non-redundant?\n\nScore: [0-5]\nExplanation:"
  }
}
```

### Custom Placeholder Names

You are **not limited** to `prompt`, `response`, and `reference`. Any valid Python identifier works as a placeholder name. Each key in `dataset_mapping` becomes a column that's substituted into `{key}` in your template:

```json
"dataset_mapping": {
  "prompt": {"source_column": "user_inputs"},
  "response": {"source_column": "final_response"},
  "tool_calls": {"source_column": "extracted_data:tool_interactions"},
  "available_tools": {"source_column": "extracted_data:tool_declarations"}
},
"template": "Request: {prompt}\nTools available: {available_tools}\nCalls made: {tool_calls}\nResponse: {response}\n\nScore: [0-5]"
```

> **Note:** `prompt` and `response` are auto-populated from `user_inputs` and `final_response` if you don't include them in `dataset_mapping`. All other placeholders must be explicitly mapped.

### Combining Multiple Columns (Meta-Columns)

To merge several source columns into a single placeholder, use the `template` + `source_columns` syntax instead of `source_column`:

```json
"dataset_mapping": {
  "prompt": {"source_column": "user_inputs"},
  "combined_context": {
    "template": "Agent reasoning: {agent_reasoning}\nSearch output: {extracted_data_search_results}",
    "source_columns": ["agent_reasoning", "extracted_data:search_results"]
  }
},
"template": "Evaluate the agent's analysis.\n\nUser: {prompt}\n\n{combined_context}\n\nScore: [0-5]"
```

**Rules for meta-columns:**
- `source_columns` lists the columns to pull values from
- `template` is a Python format string with `{variable}` placeholders
- Colons in source column names are replaced with underscores in the template variables (e.g., `extracted_data:search_results` → `{extracted_data_search_results}`)
- Placeholder names must be valid Python identifiers (letters, digits, underscores only — no hyphens or dots)

### Tips for Custom Metrics

1. **Be specific** — Define exactly what each score level means
2. **Request structured output** — Ask for `Score: [X]` format for parsing
3. **Use score_range** — Documents expected output range
4. **Filter by agent** — Use `agents` array for agent-specific metrics
5. **Include available_tools** — Prevents penalizing for non-existent tools
6. **Use compound mapping** — For large state objects, select specific fields

### Binary Decomposition (Recommended Approach)

Instead of asking an LLM for a vague "Quality" score (1-5), break requirements into specific True/False assertions:

**Step 1: Decompose into Binary Assertions**
- Bad: "Is the response helpful?"
- Good:
  - Did the agent provide a direct answer? (Yes/No)
  - Did the agent mention the user's specific product? (Yes/No)
  - Did the agent provide a 'next step'? (Yes/No)

**Step 2: Map the Evidence**
Identify which columns prove/disprove your assertions:
- `user_query` → `user_inputs`
- `agent_reply` → `final_response`
- `product_context` → `extracted_data:product_name`

**Step 3: Construct the Summation Prompt**
Write the prompt as a calculator, not a critic:

```json
"my_checklist_metric": {
  "metric_type": "llm",
  "score_range": {"min": 0, "max": 3, "description": "Sum of 3 binary checks"},
  "dataset_mapping": {
    "prompt": {"source_column": "user_inputs"},
    "response": {"source_column": "final_response"}
  },
  "template": "Evaluate the response.\n\nUser: {prompt}\nAgent: {response}\n\nChecklist:\n1. [_] Greeting provided?\n2. [_] Solution offered?\n3. [_] Closing statement?\n\nMark [x] for each Yes. Sum the total.\n\nScore: [0-3]\nExplanation: [Show your checklist]"
}
```

**Step 4: Enforce "Show Your Work"**
Force the LLM to output the checklist itself. This makes results auditable.

---

## Structured Response Evaluation

When your agent returns structured JSON (not just text), you can evaluate specific fields.

### How It Works

The evaluation framework stores `final_response` as a parsed JSON object, allowing you to access nested fields using `:` notation.

### Example: Evaluating `top_recommendation`

If your agent returns:
```json
{
  "top_recommendation": {
    "zone_name": "Capitol Hill",
    "priority_score": 4.2,
    "key_strengths": ["high foot traffic", "low competition"]
  },
  "total_competitors_found": 12,
  "zones_analyzed": 3
}
```

You can create a metric that evaluates just the `top_recommendation`:

```json
{
  "recommendation_quality": {
    "metric_type": "llm",
    "agents": ["app"],
    "score_range": {"min": 0, "max": 5, "description": "0=Poor, 5=Excellent recommendation"},
    "dataset_mapping": {
      "prompt": {"source_column": "user_inputs"},
      "top_recommendation": {"source_column": "final_response:top_recommendation"},
      "total_competitors": {"source_column": "final_response:total_competitors_found"},
      "zones_analyzed": {"source_column": "final_response:zones_analyzed"}
    },
    "template": "Evaluate the quality of a location recommendation.\n\n**User Request:**\n{prompt}\n\n**Data Coverage:**\n- Competitors Found: {total_competitors}\n- Zones Analyzed: {zones_analyzed}\n\n**Top Recommendation:**\n{top_recommendation}\n\n**Criteria:**\n1. **Actionability** - Is it specific enough to act on? Named location, next steps?\n2. **Evidence-Based** - Are strengths/concerns backed by data?\n3. **Practicality** - Are mitigation strategies realistic?\n\n**Scoring (0-5):**\n- 5: Specific, evidence-based, actionable\n- 3: Reasonable but lacks depth\n- 0: No recommendation or irrelevant\n\nIf no recommendation (clarifying question), respond: Score: N/A\n\nScore: [0-5 or N/A]\nExplanation: [Your reasoning]"
  }
}
```

### Key Takeaway

By using `final_response:top_recommendation`, you evaluate just one field from the structured JSON response. This enables:

- **Fine-grained evaluation** of specific response components
- **Reduced noise** by not evaluating the entire response for every metric
- **Domain-specific metrics** (e.g., recommendation quality, data coverage)

---

## Output Files

### Folder Structure

```
eval/results/<timestamp>/
├── eval_summary.json           # START HERE - aggregated metrics
├── question_answer_log.md      # Detailed Q&A transcript with scores
├── gemini_analysis.md          # AI root cause analysis
└── raw/
    ├── processed_interaction_*.jsonl  # Converted traces
    ├── evaluation_results_*.csv       # Full results spreadsheet
    ├── gemini_prompt.txt              # Debug: prompt sent to Gemini
    ├── session_<qid>_<sid>.json       # Session state dumps
    └── trace_<qid>_<sid>.json         # Execution trace dumps
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
    "commit": "a1b2c3d4e5f6...",
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
  "per_question_summary": [
    {
      "question_id": "scenario_001",
      "source_type": "simulation",
      "deterministic_metrics": {},
      "llm_metrics": {
        "trajectory_accuracy": {
          "score": 4.0,
          "explanation": "The agent correctly...",
          "input": {"prompt": "...", "response": "..."}
        }
      }
    }
  ],
  "per_source_summary": {
    "simulation": {
      "trajectory_accuracy": {"average": 4.2, "count": 5}
    },
    "interaction": {
      "trajectory_accuracy": {"average": 3.8, "count": 3}
    }
  }
}
```

> **`git_info`**: Captured automatically during `evaluate`. Records the git commit hash, branch, and whether there were uncommitted changes (`dirty: true`). This is used by `analyze` to run `git diff` between runs and explain *what code changes* caused metric improvements or regressions. **For this to be meaningful, commit your agent changes before each evaluation run.** If `dirty` is `true`, the diff may not fully represent what was evaluated. An easy workflow:
>
> 1. Make changes to your agent code
> 2. `git commit` the changes
> 3. Run `evaluate` (or `run`) — the commit hash is captured
> 4. Run `analyze` — it auto-detects the previous run and diffs the two commits
>
> If you're not in a git repo or git is unavailable, `git_info` will be an empty object and comparison will still work (just without code diffs).

> **`source_type`**: Appears in per-question summaries when records include it (simulation or interaction). `per_source_summary` is only generated when evaluating multiple data sources together (e.g., combining `--interaction-file` from both `simulate` and `interact` outputs). It shows per-source metric averages alongside the overall summary.

### gemini_analysis.md

AI-generated root cause analysis:

```markdown
## Critical Issues

1. **Tool Selection Error** (affects 3 test cases)
   - File: `agent/tools/billing.py:45`
   - Issue: The `lookup_invoice` tool returns incomplete data
   - Recommendation: Apply Tool Hardening pattern
```

---

## Data Formats

### Golden Dataset Format

For DIY interactions, create a JSON file with this structure:

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
    },
    {
      "id": "test_002",
      "user_inputs": ["Analyze the downtown area"],
      "agents_evaluated": ["app"],
      "reference_data": {
        "expected_behavior": "Should ask clarifying question about business type"
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

> **Tip:** Use `uv run agent-eval create-dataset` to convert ADK test files to this format.

### Conversation Scenario Format

For ADK User Sim, define scenarios in JSON:

```json
{
  "scenarios": [
    {
      "starting_prompt": "I need help with my order.",
      "conversation_plan": "Ask about order status. If asked for order ID, provide '12345'. Then ask about return policy."
    },
    {
      "starting_prompt": "I want to return a product.",
      "conversation_plan": "Explain you bought a defective item. Provide order number when asked. Request a refund."
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `starting_prompt` | First message the simulated user sends |
| `conversation_plan` | Natural language instructions for the conversation arc |

**Tips for good scenarios:**
- Be specific about user intent
- Include conditional logic ("If asked for X, provide Y")
- Define conversation flow (start, middle, end)
- Cover edge cases

### Session Input Format

```json
{
  "app_name": "my_agent",
  "user_id": "eval_user"
}
```

**CRITICAL:** `app_name` must match the **folder name** containing your agent's `agent.py`, not the agent's internal name.

### Processed JSONL Fields

The evaluation pipeline produces JSONL with these fields:

| Field | Description | Used By |
|-------|-------------|---------|
| `question_id` | Unique test case ID | All metrics |
| `source_type` | `"simulation"` or `"interaction"` — identifies data origin | Per-source summaries, filtering |
| `user_inputs` | User messages (JSON list) | LLM metrics |
| `final_response` | Agent's final response (text or JSON) | LLM metrics |
| `reference_data` | Ground truth (DIY mode) | Reference metrics |
| `session_id` | Session UUID | Debugging |
| `extracted_data` | State, tools, etc. | Custom metrics |
| `session_trace` | Full execution trace | Deterministic metrics |
| `trace_summary` | Simplified trajectory | Trajectory analysis |
| `request` | Gemini batch format request | Managed metrics |
| `response` | Gemini batch format response | Managed metrics |

---

## Adapting for Your Own Agent

To evaluate an agent from a different repository:

### 1. Scaffold Eval Structure

The easiest way is to use the `init` command:

```bash
cd /path/to/your-agent
uv run agent-eval init
```

Or create the structure manually:

```bash
mkdir -p eval/metrics eval/scenarios eval/results
```

### 2. For ADK Agents (User Sim)

Create scenario files:

```bash
# eval/scenarios/conversation_scenarios.json
{
  "scenarios": [
    {
      "starting_prompt": "I need help with...",
      "conversation_plan": "Ask about X. If asked for Y, provide Z."
    }
  ]
}

# eval/scenarios/session_input.json
{
  "app_name": "your_agent_folder_name",
  "user_id": "eval_user"
}
```

### 3. For Live Agents (DIY)

Create a Golden Dataset:

```json
{
  "golden_questions": [
    {
      "id": "test_001",
      "user_inputs": ["Your test query here"],
      "agents_evaluated": ["your_agent"],
      "reference_data": {
        "expected_behavior": "Description of expected outcome"
      }
    }
  ]
}
```

### 4. Generate Interactions

```bash
# For ADK agents (multi-turn) — simulate runs the full workflow
uv run agent-eval simulate --agent-dir ~/my-agent/my_agent_module

# For live agents (single-turn) — prompts interactively for missing config
uv run agent-eval interact --agent-dir ~/my-agent/my_agent_module
```

---

## Creating Custom Simulations

### Step 1: Define Conversation Scenarios

Create `eval/scenarios/conversation_scenarios.json`:

```json
{
  "scenarios": [
    {
      "starting_prompt": "I need help with my order.",
      "conversation_plan": "Ask about order status. If asked for order ID, provide '12345'. Then ask about return policy."
    },
    {
      "starting_prompt": "I want to return a product.",
      "conversation_plan": "Explain you bought a defective item. Provide order number when asked. Request a refund."
    }
  ]
}
```

### Step 2: Create Session Input

Create `eval/scenarios/session_input.json`:

```json
{
  "app_name": "your_agent_module",
  "user_id": "eval_user"
}
```

> **CRITICAL:** `app_name` must match the **folder name** containing `agent.py`, not the agent's internal name.

### Step 3: Run the Simulation

```bash
# From the agent-eval repository root:
uv run agent-eval simulate --agent-dir path/to/your_agent_module
```

The `simulate` command handles the full workflow automatically:
1. Creates symlinks so ADK can find your scenario files
2. Clears previous eval_history to avoid stale traces
3. Creates a fresh eval_set (avoids duplicate scenarios)
4. Runs ADK User Sim with your scenarios
5. Converts the resulting traces to agent-eval JSONL format

It prints the exact `evaluate` and `analyze` commands to run next.

---

## Supported Models & Pricing

### Analysis Models

The `analyze` command uses Gemini to generate AI-powered root cause analysis. The default model is `gemini-3.1-pro-preview` (requires `global` region, auto-configured).

| Model | Region | Status | Notes |
|-------|--------|--------|-------|
| `gemini-3.1-pro-preview` | `global` | **Default** | Latest Pro model |
| `gemini-3-flash-preview` | `global` | Active | Faster, lower cost |
| `gemini-2.5-pro` | `us-central1` | Sunsetting June 2026 | Use `--location us-central1` |
| `gemini-2.5-flash` | `us-central1` | Sunsetting June 2026 | Use `--location us-central1` |

Override with `--model` and `--location`:
```bash
uv run agent-eval analyze --results-dir eval/results/v2 --model gemini-3-flash-preview
```

### Cost Estimation Pricing

The `evaluate` command estimates per-run cost using model pricing stored in `src/agent_eval/core/deterministic_metrics.py` (`MODEL_PRICING` dict). The pricing table uses list prices per 1K tokens for the standard tier (prompts ≤ 200K tokens).

**Maintainer note:** This table must be updated when:
- New models are released (add their pricing)
- Models are deprecated or shut down (keep for backward compat with old traces)
- Google updates pricing tiers

Current pricing (April 2026):

| Model | Input / 1M tokens | Output / 1M tokens |
|-------|-------------------|-------------------- |
| `gemini-3.1-pro` | $2.00 | $12.00 |
| `gemini-3-flash` | $0.50 | $3.00 |
| `gemini-2.5-pro` | $1.25 | $10.00 |
| `gemini-2.5-flash` | $0.30 | $2.50 |
| `gemini-2.0-flash` | $0.15 | $0.60 |

Source: [Vertex AI Generative AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)

### ADK Optimization Patterns

The `analyze` command includes ADK-specific design patterns in its Gemini prompt, enabling the AI analysis to provide actionable recommendations with code examples. These patterns are bundled in `src/agent_eval/core/adk_optimization_patterns.py` and cover:

- Tool design (error handling, output truncation, docstring constraints)
- Agent architecture (sub-agent isolation, sequential/parallel pipelines)
- Prompt engineering (capability constraints, clarification rules)
- State & context management (initialization, compaction)
- Model configuration (temperature, determinism)

The patterns map evaluation metric signals (e.g., high latency, low tool grounding) to concrete ADK fixes using the five **Context Engineering Principles**: Offload, Reduce, Retrieve, Isolate, Cache.

**Maintainer note:** These patterns are derived from the [ADK documentation skills](https://github.com/google/adk-docs). To update them when ADK evolves:
```bash
# Install/update ADK skills locally to review the latest patterns
npx skills add google/adk-docs/skills -y -g

# Review the installed references
ls ~/.agents/skills/adk-cheatsheet/references/
ls ~/.agents/skills/adk-eval-guide/references/

# Update src/agent_eval/core/adk_optimization_patterns.py accordingly
```

### Smart Comparison

The `analyze` command automatically skips the comparison Gemini call (Call 2) when both runs share the same git commit and no code diff is detected. This avoids wasting API calls analyzing LLM non-determinism as if it were a code change. The comparison metrics table is still displayed so you can see the variance.

---

## Troubleshooting

### "ModuleNotFoundError: No module named '...'"

**Cause:** Running from wrong directory.
**Fix:** `cd` to the directory containing the agent module before running commands.

### Token usage shows all zeros

**Cause:** `app_name` in evalset doesn't match folder name.
**Fix:** Update `session_input.json` to match the folder containing `agent.py`.

### "Variable conversation_history is required"

**Cause:** Using `MULTI_TURN_*` metrics on a single-turn agent.
**Fix:** Use `GENERAL_QUALITY` instead of `MULTI_TURN_GENERAL_QUALITY`.

### ADK evaluation shows stale results

**Cause:** Didn't clear `eval_history` before running.
**Fix:** Use `uv run agent-eval simulate` which clears eval_history automatically. If running ADK manually: `rm -rf agent_module/.adk/eval_history/*`

### Vertex AI authentication errors

**Cause:** Missing ADC or wrong project.
**Fix:**
```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT
```

### Dashboard shows empty charts

**Cause:** Using `GOOGLE_API_KEY` instead of Vertex AI.
**Fix:** Remove `GOOGLE_API_KEY`, set `GOOGLE_CLOUD_PROJECT` instead.

### Gemini model location errors

**Cause:** Gemini 3+ and 2.5 models require specific regions.
**Fix:** Use `--location global` for Gemini 3+ models. The default (`gemini-3.1-pro-preview`) auto-configures to `global`.

### Trajectory accuracy penalizing for missing tools

**Cause:** LLM judge expects tools that don't exist.
**Fix:** Add `available_tools` to metric:
```json
"dataset_mapping": {
  "available_tools": {"source_column": "extracted_data:tool_declarations"}
}
```

And add to template:
```
CRITICAL: Only evaluate against AVAILABLE tools listed above.
```

### Mock data being penalized

**Cause:** Test environments return mock data.
**Fix:** Add to metric template:
```
IMPORTANT: Tools may return MOCK data in test environments.
Do NOT penalize the agent for correctly relaying mock data.
```

### ADK UserSim: "Error rendering metric prompt template" during `adk eval`

**Cause:** ADK runs its own built-in LLM-as-judge evaluation per interaction during `adk eval`. This is separate from `agent-eval`'s evaluation (which runs in batch via the Vertex AI Evaluation SDK). ADK's per-interaction scoring is slow and unnecessary when using `agent-eval`.

**Fix:** The `simulate` command defaults to an empty `eval_config.json` (`{"criteria": {}`), which skips ADK's built-in scoring entirely. The agent interactions and traces are still captured — only ADK's own LLM scoring is skipped.

If you see old results with ADK scores, they appear in a separate `adk_eval_scores` section in `eval_summary.json` and are not mixed with `agent-eval`'s LLM-as-judge metrics.

For more details, see the [ADK User Simulation docs](https://google.github.io/adk-docs/evaluate/user-sim/).

### Permission denied on autorater model during evaluation

**Cause:** The Vertex AI service account lacks permissions to access the autorater model.
**Fix:** Grant the Vertex AI service agent role:

```bash
export GOOGLE_CLOUD_PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:service-$GOOGLE_CLOUD_PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/aiplatform.serviceAgent"
```

---

## AI Assistant Setup

Use AI coding assistants to accelerate the evaluation workflow. Both Gemini CLI and Claude Code can help you interpret evaluation results, debug metric definitions, and suggest optimizations.

This repository includes context files for both assistants:

- **`GEMINI.md`** — Loaded automatically by Gemini CLI when running from the project root
- **`CLAUDE.md`** — Loaded automatically by Claude Code when running from the project root

These files provide the assistant with project context: what `agent-eval` is, how the CLI commands work, the evaluation pipeline, and the example agents. This lets the assistant give relevant advice when you share `eval_summary.json` or `gemini_analysis.md` results.

### Gemini CLI

```bash
# Install
npm install -g @google/gemini-cli

# Configure for Vertex AI
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=true

# Run from project root (GEMINI.md is loaded automatically)
gemini
```

### Claude Code

```bash
# Install
npm install -g @anthropic-ai/claude-code

# Option A: With Vertex AI
export ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
export CLOUD_ML_REGION=us-central1

# Option B: With API Key
export ANTHROPIC_API_KEY=your-api-key

# Run from project root (CLAUDE.md is loaded automatically)
claude
```

See [Vertex AI guide for Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/claude-code/bedrock-vertex) for detailed setup.

### Tips for Using AI Assistants with Evaluation Results

1. **Share data:** Paste `eval_summary.json` and `gemini_analysis.md` for data-driven help
2. **Be specific:** "Improve trajectory_accuracy by fixing tool selection" beats "make it better"
3. **Iterate:** Run eval → share results → get suggestions → implement → repeat

### Dashboard (Alternative)

For visual, interactive comparison of evaluation runs across multiple experiments, a Gradio dashboard is also available:

```bash
cd dashboard
uv run dashboard.py
# Open http://127.0.0.1:7860
```

See [`dashboard/README.md`](../dashboard/README.md) for details.

---

## Additional Resources

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK User Simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/docs/generative-ai/evaluation/)
