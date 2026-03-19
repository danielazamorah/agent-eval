# agent-eval

Evaluation CLI for ADK agents — run interactions, evaluate with metrics, and analyze results.

Move from trial-and-error prompt engineering to systematic, measurable agent optimization.

---

## What is agent-eval?

`agent-eval` is a command-line tool that acts as the glue between:

- **OpenTelemetry** traces from ADK
- **Vertex AI Evaluation** service for LLM-as-judge metrics
- **Gemini** for analyzing results

It consolidates the full evaluation workflow into a single CLI: generate interactions, extract deterministic metrics from traces, run LLM-as-judge scoring, and produce AI-powered analysis reports.

---

## How it works

```
  Interact           Evaluate              Analyze
 ──────────       ────────────          ────────────
│ simulate │ ──▶ │ Deterministic │ ──▶ │ Gemini AI  │
│ interact │     │ + LLM Judge   │     │ Diagnosis  │
 ──────────       ────────────          ────────────

 Generate           Score traces          Root cause
 agent traces       with metrics          analysis
```

**1. Interact** — Generate agent traces via ADK User Sim (multi-turn) or DIY queries (single-turn)

**2. Evaluate** — Score traces with two types of metrics:

| Type | What it measures | How it works |
|------|-----------------|--------------|
| **Deterministic** | Latency, tokens, cost, cache efficiency, tool reliability | Auto-extracted from OpenTelemetry traces — no configuration needed |
| **LLM-as-Judge** | Response quality, trajectory accuracy, tool use, safety | Scored by Vertex AI using customizable rubrics you define |

**3. Analyze** — Gemini reads all metrics and generates a diagnosis report with root cause analysis and optimization recommendations.

### Metrics at a glance

**Deterministic** (automatic, same for all agents):

| Metric | What you learn |
|--------|---------------|
| `token_usage.*` | Total tokens, prompt vs completion, estimated cost in USD |
| `latency_metrics.*` | Total time, LLM time, tool time, time to first response |
| `cache_efficiency.*` | KV-cache hit rate — are your prompts structured for caching? |
| `tool_success_rate.*` | How often tool calls succeed vs fail |
| `thinking_metrics.*` | How much the model "thinks" before responding |

**LLM-as-Judge** (configurable per agent in `metric_definitions.json`):

| Metric | What it scores |
|--------|---------------|
| `general_quality` | Overall response quality (Vertex AI managed) |
| `trajectory_accuracy` | Did the agent take the right path through tools? |
| `tool_use_quality` | Were tool arguments correct and efficient? |
| `safety` | Safety compliance (Vertex AI managed) |
| Custom metrics | Anything you define with a scoring rubric |

> Metrics are defined in `eval/metrics/metric_definitions.json`. The `init` command creates starter metrics; you customize them for your agent. See [docs/reference.md](docs/reference.md) for the full metrics glossary and custom metric creation guide.

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10–3.12 | Python 3.13+ not yet supported |
| [uv](https://docs.astral.sh/uv/) | Latest | Package manager |
| [gcloud CLI](https://cloud.google.com/sdk/docs/install) | Latest | Google Cloud authentication |
| Vertex AI API | Enabled | Required for evaluation metrics |

### Vertex AI Configuration

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

```bash
# Clone the repository
git clone REPO_URL_PLACEHOLDER agent-eval
cd agent-eval

# Install dependencies
uv sync

# Verify installation
uv run agent-eval --version
```

### Authentication

```bash
# Authenticate with Google Cloud
gcloud auth login
gcloud auth application-default login

# Set your project
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT

# Enable required APIs
gcloud services enable aiplatform.googleapis.com --project=$GOOGLE_CLOUD_PROJECT
```

Grant Vertex AI autorater model permissions:

```bash
export GOOGLE_CLOUD_PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:service-$GOOGLE_CLOUD_PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/aiplatform.serviceAgent"
```

---

## Quickstart

All `uv run agent-eval` commands run from the **agent-eval repository root**. You point the CLI to your agent using `--agent-dir` with the path to the folder containing your `agent.py`.

> **Don't have an agent yet?** Create one with [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack):
>
> ```bash
> uvx agent-starter-pack create my-agent
> ```
>
> Or to follow along with the [tutorial](docs/tutorial.md), use one of the [example agents](docs/tutorial/example_agents/).

### 1. Initialize your project

```bash
uv run agent-eval init
```

The CLI scans for `agent.py` files and lets you select which agent to scaffold evaluation for. It creates an `eval/` folder inside the agent module directory with starter metrics, scenario files, and a golden dataset.

Use `uv run agent-eval init -y` for non-interactive mode with defaults.

### 2. Generate interactions

Choose the method that fits your agent:

| Method | Best for | Command |
|--------|----------|---------|
| **ADK User Sim** | Multi-turn conversational agents | `uv run agent-eval simulate` |
| **DIY Interactions** | Single-turn agents, deployed endpoints | `uv run agent-eval interact` |

**ADK User Sim** (multi-turn):

```bash
# Pass the full path to your agent module (the folder with agent.py)
uv run agent-eval simulate --agent-dir path/to/your/agent_module
```

This single command handles the full workflow: creates symlinks for ADK, clears previous traces, sets up a fresh eval set, runs the simulation, and converts traces to evaluation format.

**DIY Interactions** (single-turn or live agents):

```bash
# First, start your agent (in a separate terminal):
# ADK Starter Pack agents: cd path/to/your/agent && make playground
# Custom agents: start your server on any port

# Then run the interactive command:
uv run agent-eval interact --agent-dir path/to/your/agent_module
```

The command prompts for any missing configuration (questions file, base URL, run ID). Pass `--base-url`, `--questions-file`, etc. to skip prompts in CI.

### 3. Evaluate & Analyze

> **Don't type these commands manually!** Both `simulate` and `interact` print the exact `evaluate` and `analyze` commands with the correct paths pre-filled at the end of their output. Just copy and paste them.

The commands look like this:

```bash
uv run agent-eval evaluate \
  --interaction-file <path-to-interactions.jsonl> \
  --metrics-files <path-to-metric_definitions.json> \
  --results-dir <path-to-run-dir>

uv run agent-eval analyze \
  --results-dir <path-to-run-dir> \
  --agent-dir <path-to-agent-module>
```

The `evaluate` command displays a metrics summary table directly in the terminal. The `analyze` command renders the full AI diagnosis report in the terminal. Results are also saved to files for deeper review.

---

## CLI Commands

| Command | Purpose |
|---------|---------|
| `uv run agent-eval init` | Scaffold eval folder structure for a new project |
| `uv run agent-eval simulate` | Run ADK User Sim + convert traces (multi-turn) |
| `uv run agent-eval interact` | Run interactions against a live agent endpoint (single-turn) |
| `uv run agent-eval evaluate` | Run deterministic + LLM-as-judge metrics |
| `uv run agent-eval analyze` | Generate reports and AI-powered analysis |
| `uv run agent-eval convert` | Convert ADK traces to evaluation format (used by simulate) |
| `uv run agent-eval create-dataset` | Convert ADK test files to golden dataset format |

Run `uv run agent-eval --help` or `uv run agent-eval <command> --help` for detailed usage.

---

## Examples

The [`docs/tutorial/example_agents/`](docs/tutorial/example_agents/) folder contains two complete agent projects with pre-configured evaluation setups:

| Example | Type | Description |
|---------|------|-------------|
| [customer-service](docs/tutorial/example_agents/customer-service/) | Multi-turn | ADK conversational agent evaluated with User Sim |
| [retail-ai-location-strategy](docs/tutorial/example_agents/retail-ai-location-strategy/) | Single-turn | ADK pipeline agent evaluated with DIY Interactions |

See the [tutorial](docs/tutorial.md) for a guided walkthrough using these examples.

---

## Documentation

| Document | Contents |
|----------|----------|
| [Reference Guide](docs/reference.md) | CLI reference, metrics deep dive, data formats, custom metrics, troubleshooting |
| [Tutorial](docs/tutorial.md) | Step-by-step walkthrough using the example agents |
| [Examples](docs/tutorial/example_agents/README.md) | Overview of the example agent projects |

---

## Additional Resources

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK User Simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/docs/generative-ai/evaluation/)
