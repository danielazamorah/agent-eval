# agent-eval

Evaluation CLI for ADK agents — run interactions, evaluate with metrics, and analyze results.

Move from trial-and-error prompt engineering to systematic, measurable agent optimization.

---

## How It Works

```
  Interact           Evaluate              Analyze
 ──────────       ────────────          ────────────
│ simulate │ ──▶ │ Deterministic │ ──▶ │ Gemini AI  │
│ interact │     │ + LLM Judge   │     │ Diagnosis  │
 ──────────       ────────────          ────────────

 Generate           Score traces          Root cause
 agent traces       with metrics          analysis
```

`agent-eval` consolidates the full evaluation workflow into a single CLI:

1. **Interact** — Generate agent traces via ADK User Sim (multi-turn) or DIY queries (single-turn)
2. **Evaluate** — Score traces with deterministic metrics (latency, tokens, cost) + LLM-as-judge metrics (quality, accuracy, safety)
3. **Analyze** — Gemini reads all metrics and generates root cause analysis with optimization recommendations

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10-3.12 | Python 3.13+ not yet supported |
| [uv](https://docs.astral.sh/uv/) | Latest | Package manager |
| [gcloud CLI](https://cloud.google.com/sdk/docs/install) | Latest | Google Cloud authentication |
| Vertex AI API | Enabled | Required for evaluation metrics |

```
+------------------------------------------------------------------+
|  You MUST use Vertex AI for the evaluation pipeline to work.     |
|                                                                   |
|  Set: GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION             |
|  Do NOT use: GOOGLE_API_KEY (metrics will be empty)              |
+------------------------------------------------------------------+
```

---

## Installation

There are two ways to install `agent-eval`, depending on your setup.

### Option A: Build a Wheel (recommended for existing agent projects)

If you already have an agent project with its own dependencies (e.g., from [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)), build `agent-eval` as a wheel and install it alongside your project. This avoids dependency conflicts.

```bash
# 1. Clone the agent-eval repository
git clone <REPO_URL> agent-eval
cd agent-eval

# 2. Build the wheel
./build_wheel.sh
# Output: dist/agent_eval-0.1.0-py3-none-any.whl

# 3. Copy the wheel to your agent project
cp dist/agent_eval-*.whl /path/to/your-agent/vendor/

# 4. Install in your agent project's environment
cd /path/to/your-agent
uv pip install ./vendor/agent_eval-0.1.0-py3-none-any.whl

# 5. Verify
agent-eval --version
```

After installing the wheel, all `agent-eval` commands run directly (no `uv run` prefix needed):

```bash
agent-eval init
agent-eval run --agent-dir ./my_agent
```

### Option B: Run from source (for development or standalone use)

If you want to use `agent-eval` as a standalone tool or contribute to development:

```bash
# 1. Clone the repository
git clone <REPO_URL> agent-eval
cd agent-eval

# 2. Install dependencies
uv sync

# 3. Verify
uv run agent-eval --version
```

When running from source, prefix all commands with `uv run`:

```bash
uv run agent-eval init
uv run agent-eval run --agent-dir /path/to/your/agent_module
```

> Throughout this documentation, commands use the `uv run agent-eval` prefix. If you installed the wheel, drop the `uv run` prefix.

---

## Authentication

```bash
# 1. Authenticate with Google Cloud
gcloud auth login
gcloud auth application-default login

# 2. Set your project
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT

# 3. Enable required APIs
gcloud services enable aiplatform.googleapis.com --project=$GOOGLE_CLOUD_PROJECT

# 4. Grant Vertex AI autorater permissions
export PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/aiplatform.serviceAgent"
```

---

## Getting Started

### Step 1: Initialize your project

Point `agent-eval` at the directory containing your `agent.py`:

```bash
uv run agent-eval init
```

The CLI scans for `agent.py` files and lets you select which agent to evaluate. It creates an `eval/` folder inside the agent module directory with:
- **Metric definitions** — LLM-as-judge scoring rubrics (managed + custom)
- **Scenarios** — Multi-turn conversation scripts for ADK User Sim
- **Golden dataset** — Single-turn test queries with expected behavior

**AI-powered setup (recommended):** In Step 3, choose "Generate with AI" (the default). The CLI runs a multi-step pipeline:

1. **Discovers managed metrics** from the Vertex AI SDK at runtime (20+ metrics across quality, safety, tool use, grounding, and more)
2. **Analyzes your agent's source code** with Gemini — identifies tools, state variables, sub-agents, and key behaviors
3. **Generates custom metric definitions** tailored to your agent's specific evaluation needs
4. **Generates scenarios and golden data** based on your agent's capabilities

You select which managed metrics to include and provide evaluation priorities (e.g., "accuracy of billing lookups, response tone") to guide the generation.

```bash
# Non-interactive with AI-generated metrics
uv run agent-eval init -y --ai-metrics
```

### Step 2: Run the full pipeline

The `run` command executes all phases in sequence:

```bash
uv run agent-eval run --agent-dir path/to/your/agent_module
```

This runs: **simulate** (multi-turn conversations) -> **interact** (single-turn queries against a live agent) -> **evaluate** (score all traces) -> **analyze** (AI-powered diagnosis).

Each phase prompts for configuration. If the agent isn't reachable for `interact`, that phase is skipped gracefully.

> **Note:** The `interact` phase sends queries to a running agent. Start your agent first (e.g., `adk web` or `make playground`).

### Step 3: Read your results

Results are saved to `eval/results/<run-id>/`:

| File | What it contains |
|------|-----------------|
| `eval_summary.json` | Aggregated metrics — **start here** |
| `question_answer_log.md` | Per-question breakdown with scores and explanations |
| `gemini_analysis.md` | AI root cause analysis with optimization recommendations |
| `OPTIMIZATION_LOG.md` | Cumulative comparison across runs (in parent results dir) |

### Step 4: Iterate

Make changes to your agent, then run again:

```bash
uv run agent-eval run --agent-dir path/to/agent --run-id v2
```

The `analyze` command automatically compares against the previous run, showing metric deltas and explaining what code changes caused improvements or regressions.

---

## CLI Commands

| Command | Purpose |
|---------|---------|
| `init` | Scaffold eval folder with managed + custom metrics, scenarios, and golden data |
| `run` | Full pipeline: simulate + interact + evaluate + analyze (+ optional dashboard) |
| `simulate` | Run ADK User Sim + convert traces (multi-turn conversations) |
| `interact` | Run queries against a live agent endpoint (single-turn) |
| `evaluate` | Run deterministic + LLM-as-judge metrics on interaction data |
| `analyze` | Generate AI-powered analysis reports with run comparison |
| `convert` | Convert ADK traces to evaluation format (called automatically by simulate) |
| `create-dataset` | Convert ADK test files to golden dataset format |
| `dashboard` | Launch interactive Gradio dashboard for comparing runs (requires `[dashboard]` extras) |

Run `uv run agent-eval --help` or `uv run agent-eval <command> --help` for full options.

See the [Reference Guide](docs/reference.md) for detailed documentation of every command, option, metric type, data format, and customization.

---

## Metrics

`agent-eval` produces two categories of metrics:

### Deterministic (automatic)

Extracted from OpenTelemetry traces — no configuration needed, same for every agent:

| Metric | What you learn |
|--------|---------------|
| `token_usage.*` | Total tokens, prompt vs completion, estimated cost in USD |
| `latency_metrics.*` | Total time, LLM time, tool time, time to first response |
| `cache_efficiency.*` | KV-cache hit rate — are your prompts structured for caching? |
| `tool_success_rate.*` | How often tool calls succeed vs fail |
| `thinking_metrics.*` | How much the model reasons before responding |

### LLM-as-Judge (configurable)

Scored by Vertex AI Evaluation using rubrics defined in `metric_definitions.json`. Two types:

**Managed metrics** — Built into the Vertex AI SDK, discovered at runtime:

| Type | Examples | Score |
|------|----------|-------|
| Server-side (API Predefined) | GENERAL_QUALITY, SAFETY, HALLUCINATION, TOOL_USE_QUALITY, GROUNDING, INSTRUCTION_FOLLOWING | 0-1 rubric pass rate |
| Client-side (GCS YAML) | COHERENCE, FLUENCY, GROUNDEDNESS, VERBOSITY, SUMMARIZATION_QUALITY | 1-5 pointwise |
| Multi-turn | MULTI_TURN_GENERAL_QUALITY, MULTI_TURN_CHAT_QUALITY, MULTI_TURN_SAFETY | varies |

**Custom metrics** — Your own scoring rubrics tailored to your agent's domain. Define what to evaluate, how to score it, and which trace data to feed the LLM judge.

> See [Creating Custom Metrics](docs/reference.md#creating-custom-metrics) in the Reference Guide for the full custom metric creation guide, including dataset mapping constraints, metric routing, and examples.

---

## Interaction Modes

| Agent Type | Recommended Mode | Command |
|------------|------------------|---------|
| Multi-turn chatbot | ADK User Sim | `uv run agent-eval simulate --agent-dir path/to/agent` |
| Single-turn pipeline | DIY Interactions | `uv run agent-eval interact --agent-dir path/to/agent` |
| Deployed/remote agent | DIY Interactions | `uv run agent-eval interact --base-url https://your-agent.run.app` |
| Rapid prototyping | ADK User Sim | No golden dataset needed — LLM simulates users |

**ADK User Sim** solves the cold-start problem: you define conversation scenarios, and an LLM simulates realistic users following your scripts. No hand-crafted golden datasets needed.

**DIY Interactions** sends queries from a golden dataset to a live agent endpoint. Best for regression testing with known-good responses.

---

## Comparing Runs

The `analyze` command automatically maintains an `OPTIMIZATION_LOG.md` with cumulative metric comparisons:

```bash
# First run — creates baseline
uv run agent-eval run --agent-dir ./my_agent --run-id baseline

# Make changes to your agent, then run again
uv run agent-eval run --agent-dir ./my_agent --run-id v2

# The analysis auto-compares v2 vs baseline:
#   - Terminal table with metric deltas
#   - Git diff between commits explaining what changed
#   - Cumulative OPTIMIZATION_LOG.md with iteration history
```

---

## Project Structure

After running `agent-eval init`, your agent project looks like:

```
my-agent/
├── my_agent/                            # Your ADK agent
│   ├── agent.py
│   ├── tools/
│   └── ...
├── eval/                                # Created by agent-eval init
│   ├── metrics/metric_definitions.json  # LLM-as-judge scoring rubrics
│   ├── scenarios/                       # ADK User Sim scenarios
│   │   ├── conversation_scenarios.json
│   │   ├── session_input.json
│   │   └── eval_config.json
│   ├── eval_data/golden_dataset.json    # DIY test queries
│   └── results/                         # Evaluation outputs
│       ├── OPTIMIZATION_LOG.md          # Cumulative run comparison
│       └── <run-id>/
│           ├── eval_summary.json        # Aggregated metrics
│           ├── gemini_analysis.md       # AI root cause analysis
│           ├── question_answer_log.md   # Per-question breakdown
│           └── raw/                     # Traces, CSVs, debug files
├── pyproject.toml
└── .env
```

---

## Dashboard

For visual, interactive comparison of evaluation runs, an integrated Gradio dashboard is available.

**Install dashboard extras:**

```bash
pip install agent-eval[dashboard]
# or: uv pip install gradio plotly
```

**Launch standalone:**

```bash
uv run agent-eval dashboard --results-dir eval/results/
# Open http://127.0.0.1:7860
```

**Or as part of the pipeline:** The `run` command offers to launch the dashboard after the analyze phase completes. Use `--dashboard` to auto-launch, or `--no-dashboard` to skip the prompt.

**Features:**
- Scorecards with delta % for Cost, Latency, and Quality vs baseline
- Grouped bar charts with normalize toggle
- Per-question drilldown by metric
- AI analysis viewer (gemini_analysis.md)
- Full raw data table for export

---

## Documentation

| Document | Contents |
|----------|----------|
| **This README** | Installation, getting started, overview |
| [Reference Guide](docs/reference.md) | Full CLI reference, all command options, metric deep dive, custom metrics, data formats, troubleshooting |

---

## Additional Resources

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK User Simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/docs/generative-ai/evaluation/)
- [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)
