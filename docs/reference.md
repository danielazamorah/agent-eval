# Agent Evaluation Reference Guide

Complete documentation for the `agent-eval` CLI, metrics, data formats, and customization.

---

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [CLI Reference](#cli-reference)
3. [Interaction Modes](#interaction-modes)
4. [Metrics Deep Dive](#metrics-deep-dive)
5. [Creating Custom Metrics](#creating-custom-metrics)
6. [Structured Response Evaluation](#structured-response-evaluation)
7. [Output Files](#output-files)
8. [Data Formats](#data-formats)
9. [Adapting for Your Own Agent](#adapting-for-your-own-agent)
10. [Creating Custom Simulations](#creating-custom-simulations)
11. [Troubleshooting](#troubleshooting)
12. [AI Assistant Setup](#ai-assistant-setup)

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
├── examples/
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

## CLI Reference

### All Commands

| Command | Purpose | Mode |
|---------|---------|------|
| `agent-eval init` | Scaffold eval folder structure | Setup |
| `agent-eval convert` | Convert ADK traces to JSONL | ADK User Sim |
| `agent-eval interact` | Run interactions against live agent | DIY Interactions |
| `agent-eval evaluate` | Run metrics on interactions | Both |
| `agent-eval analyze` | Generate reports and AI analysis | Both |
| `agent-eval create-dataset` | Convert test files to Golden Dataset | DIY Interactions |

### `agent-eval init`

Scaffolds the `eval/` folder structure for a new agent project with starter metrics and data files.

```bash
agent-eval init
```

| Option | Default | Description |
|--------|---------|-------------|
| `--target-dir` | `.` | Root directory of your agent project |
| `--agent-name` | (prompted) | Agent application name |
| `--mode` | (prompted) | Interaction mode: `user-sim`, `diy`, or `both` |
| `--auto-approve`, `-y` | `false` | Skip interactive prompts, use defaults |

### `agent-eval convert`

Converts ADK simulator history (`.adk/eval_history/`) to evaluation JSONL.

```bash
agent-eval convert \
  --agent-dir <path-to-agent-module> \
  --output-dir <path-to-results>
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--agent-dir` | Yes | — | Agent module containing `.adk/eval_history/` |
| `--output-dir` | No | `results/` | Output directory |
| `--questions-file` | No | — | Golden dataset for merging reference data |

**Output:** `<output-dir>/<timestamp>/raw/processed_interaction_sim.jsonl`

### `agent-eval interact`

Runs interactions against a live agent endpoint.

```bash
agent-eval interact \
  --app-name <agent_name> \
  --questions-file <path-to-golden.json> \
  --base-url <agent-url> \
  --results-dir <path-to-results>
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--app-name` | Yes | — | Agent application name |
| `--questions-file` | Yes | — | Golden Dataset JSON |
| `--base-url` | No | `http://localhost:8080` | Agent API URL |
| `--results-dir` | No | `results/` | Output directory |
| `--user-id` | No | `test_user` | User ID for session |
| `--runs` | No | `1` | Number of runs per question |

**Output:** `<results-dir>/<timestamp>/raw/processed_interaction_<app_name>.jsonl`

### `agent-eval evaluate`

Runs metrics on processed interaction data.

```bash
agent-eval evaluate \
  --interaction-file <path-to-jsonl> \
  --metrics-files <path-to-metrics.json> \
  --results-dir <path-to-results>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--interaction-file` | Yes | Path to processed JSONL |
| `--metrics-files` | Yes | Metric definition JSON (can specify multiple) |
| `--results-dir` | Yes | Output directory (use same timestamp folder) |
| `--input-label` | No | Run label (e.g., "baseline") |
| `--test-description` | No | Description for this run |

**Output:** `eval_summary.json`, `evaluation_results_*.csv`

### `agent-eval analyze`

Generates reports and AI-powered root cause analysis.

```bash
agent-eval analyze \
  --results-dir <path-to-results> \
  --agent-dir <path-to-agent>
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--results-dir` | Yes | — | Directory with eval results |
| `--agent-dir` | No | — | Agent source (adds context to AI analysis) |
| `--strategy-file` | No | — | Optimization strategy markdown |
| `--model` | No | `gemini-2.5-pro` | Gemini model for analysis |
| `--location` | No | — | Vertex AI region (use `global` for Gemini 2.5) |
| `--skip-gemini` | No | `false` | Skip AI analysis |

**Output:** `question_answer_log.md`, `gemini_analysis.md`

### `agent-eval create-dataset`

Converts ADK test files to Golden Dataset format.

```bash
agent-eval create-dataset \
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
4. Traces are captured in `.adk/eval_history/`

**When to use:**
- Development and rapid iteration
- Testing conversation flows without reference answers
- Exploring agent behavior across many scenarios
- You don't have a golden dataset yet
- Multi-turn conversational agents

**Files needed:**
```
eval/scenarios/
├── conversation_scenarios.json   # Scenario definitions
└── session_input.json            # Session config (app_name, user_id)
```

### DIY Interactions

Run interactions against a live agent endpoint. Use when you have specific queries or when the agent is a single-turn pipeline.

**How it works:**
1. Create a Golden Dataset with queries and expected responses
2. Start your agent
3. Run `agent-eval interact` against the running agent
4. Traces are captured as JSONL

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
      "deterministic_metrics": {},
      "llm_metrics": {
        "trajectory_accuracy": {
          "score": 4.0,
          "explanation": "The agent correctly...",
          "input": {"prompt": "...", "response": "..."}
        }
      }
    }
  ]
}
```

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

> **Tip:** Use `agent-eval create-dataset` to convert ADK test files to this format.

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
agent-eval init
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

### 4. Run Evaluation

```bash
# For ADK agents — convert traces
agent-eval convert \
  --agent-dir ~/my-agent/my_agent_module \
  --output-dir ~/my-agent/eval/results

# For live agents — run interactions
agent-eval interact \
  --app-name my_agent \
  --questions-file ~/my-agent/eval/golden_dataset.json \
  --base-url http://localhost:8080 \
  --results-dir ~/my-agent/eval/results
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
cd your-agent
rm -rf agent_module/.adk/eval_history/*

# Create eval set
uv run adk eval_set create agent_module eval_set_name
uv run adk eval_set add_eval_case agent_module eval_set_name \
  --scenarios_file eval/scenarios/conversation_scenarios.json \
  --session_input_file eval/scenarios/session_input.json

# Run simulation
uv run adk eval agent_module eval_set_name
```

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
**Fix:** `rm -rf agent_module/.adk/eval_history/*`

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

### Gemini 2.5 model location errors

**Cause:** Model not available in specified region.
**Fix:** Use `--location global` in the analyze command.

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

**Cause:** ADK UserSim runs a built-in evaluation by default after the simulation completes. If no eval config file is provided, the default metrics may fail. This does not affect the simulation runs themselves — the agent interactions and traces are captured successfully. `agent-eval` runs its own separate evaluation step using the Vertex AI SDK.
**Fix:** Provide an eval config file with your `adk eval` command:

```bash
uv run adk eval my_agent --config_file_path my_agent/eval_config.json eval_set_name
```

If you don't have an eval config file, create one (e.g., `eval/eval_config.json`):

```json
{
  "criteria": {
    "hallucinations_v1": {
      "threshold": 0.5,
      "evaluate_intermediate_nl_responses": true
    },
    "safety_v1": {
      "threshold": 0.8
    }
  }
}
```

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
