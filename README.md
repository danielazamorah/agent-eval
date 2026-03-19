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
git clone REPO_URL_PLACEHOLDER
cd agent-eval

# Install dependencies
uv sync
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

### 1. Initialize your project

```bash
agent-eval init
```

This interactive command scaffolds an `eval/` folder in your agent project with starter metrics, scenario files, and a golden dataset.

Use `agent-eval init -y` for non-interactive mode with defaults.

### 2. Generate interactions

Choose the method that fits your agent:

| Method | Best for | Command |
|--------|----------|---------|
| **ADK User Sim** | Multi-turn conversational agents | `adk eval` → `agent-eval convert` |
| **DIY Interactions** | Single-turn agents, deployed endpoints | `agent-eval interact` |

**ADK User Sim** (multi-turn):

```bash
# In your agent project directory
uv run adk eval_set create <agent_module> eval_set
uv run adk eval_set add_eval_case <agent_module> eval_set \
  --scenarios_file eval/scenarios/conversation_scenarios.json \
  --session_input_file eval/scenarios/session_input.json
uv run adk eval <agent_module> eval_set

# Convert traces to evaluation format
agent-eval convert \
  --agent-dir <agent_module> \
  --output-dir eval/results
```

**DIY Interactions** (single-turn or live agents):

```bash
# Start your agent, then:
agent-eval interact \
  --app-name <agent_name> \
  --questions-file eval/eval_data/golden_dataset.json \
  --base-url http://localhost:8080 \
  --results-dir eval/results
```

### 3. Evaluate

```bash
agent-eval evaluate \
  --interaction-file eval/results/<run>/raw/processed_interaction_*.jsonl \
  --metrics-files eval/metrics/metric_definitions.json \
  --results-dir eval/results/<run>
```

### 4. Analyze

```bash
agent-eval analyze \
  --results-dir eval/results/<run> \
  --agent-dir <path-to-agent> \
  --location global
```

Review the results:

```bash
cat eval/results/<run>/gemini_analysis.md    # AI-generated analysis
cat eval/results/<run>/eval_summary.json     # Raw metrics
```

---

## CLI Commands

| Command | Purpose |
|---------|---------|
| `agent-eval init` | Scaffold eval folder structure for a new project |
| `agent-eval interact` | Run interactions against a live agent endpoint |
| `agent-eval convert` | Convert ADK traces to evaluation format |
| `agent-eval evaluate` | Run deterministic + LLM-as-judge metrics |
| `agent-eval analyze` | Generate reports and AI-powered analysis |
| `agent-eval create-dataset` | Convert ADK test files to golden dataset format |

Run `agent-eval --help` or `agent-eval <command> --help` for detailed usage.

---

## Metrics

The evaluation produces two types of metrics:

**Deterministic** (extracted automatically from traces):
- `latency_metrics.*` — timing data
- `token_usage.*` — input/output tokens, estimated cost
- `cache_efficiency.*` — KV-cache hit rates
- `tool_success_rate.*` — tool call reliability

**LLM-as-Judge** (scored by Vertex AI):
- `general_quality` — overall response quality
- `trajectory_accuracy` — execution path correctness
- `tool_use_quality` — tool argument correctness
- Custom metrics you define

See [docs/reference.md](docs/reference.md) for the full metrics glossary, custom metric creation, and data format specifications.

---

## Examples

The [`examples/`](examples/) folder contains two complete agent projects with pre-configured evaluation setups:

| Example | Type | Description |
|---------|------|-------------|
| [customer-service](examples/customer-service/) | Multi-turn | ADK conversational agent evaluated with User Sim |
| [retail-ai-location-strategy](examples/retail-ai-location-strategy/) | Single-turn | ADK pipeline agent evaluated with DIY Interactions |

See the [tutorial](docs/tutorial.md) for a guided walkthrough using these examples.

---

## Documentation

| Document | Contents |
|----------|----------|
| [Reference Guide](docs/reference.md) | CLI reference, metrics deep dive, data formats, custom metrics, troubleshooting |
| [Tutorial](docs/tutorial.md) | Step-by-step walkthrough using the example agents |
| [Examples](examples/README.md) | Overview of the example agent projects |

---

## Additional Resources

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK User Simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/docs/generative-ai/evaluation/)
