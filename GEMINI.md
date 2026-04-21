# agent-eval — AI Assistant Context

> This file provides context for Gemini CLI. It is loaded automatically when you run `gemini` from a project that uses `agent-eval`.

---

## What is agent-eval?

`agent-eval` is an evaluation CLI for ADK agents. It acts as the glue between OpenTelemetry traces from ADK, Vertex AI Evaluation for LLM-as-judge metrics, and Gemini for analysis.

**The evaluation cycle:**
1. **Interact** — Generate agent traces. Either `agent-eval simulate` (UserSim, multi-turn) or `agent-eval interact` (DIY, single-turn) — both are forms of interacting with the agent, just different drivers.
2. **Evaluate** — Score traces with deterministic metrics (latency, tokens, cost) + LLM-as-judge metrics (quality, accuracy)
3. **Analyze** — Generate AI-powered root cause analysis

**Context Engineering Principles** guide optimizations:
- **Offload**: Move deterministic logic out of the LLM into tools/code
- **Reduce**: Summarize or compact stale context to prevent "context rot"
- **Retrieve**: Replace static knowledge with RAG
- **Isolate**: Split monolithic agents into specialized sub-agents
- **Cache**: Restructure prompts for prefix caching

---

## Typical Project Structure

When a user runs `agent-eval init`, it scaffolds eval artifacts under `tests/eval/` (Path A — Agent Engine) and/or `eval/` (Path B — local ADK source, ADK-runtime files):

```
my-agent/
├── my_agent/                                  # ADK agent source code
│   ├── agent.py
│   ├── tools/
│   └── ...
├── tests/eval/                                # Path A — unified SDK-aligned layout
│   ├── dataset.jsonl                          # Unified rows (prompt / reference / conversation_history / session_inputs / expected_*)
│   ├── metrics/metric_definitions.json        # LLM-as-judge metric rubrics
│   └── results/                               # Evaluation outputs (eval_summary.json, gemini_analysis.md, ...)
├── eval/                                      # Path B — kept for local ADK runtime (UserSim + DIY)
│   ├── scenarios/                             # ADK User Sim scenarios + session input
│   ├── eval_data/golden_dataset.json          # DIY test queries
│   └── metrics/metric_definitions.json        # Same rubrics, read by `evaluate` if tests/eval/metrics/ is absent
├── pyproject.toml
└── .env
```

> **Migrating an old project?** Run `agent-eval migrate` to flatten `eval/scenarios/` + `eval/eval_data/golden_dataset.json` into `tests/eval/dataset.jsonl` (originals are copied to `tests/eval/.backup/<timestamp>/`).

---

## CLI Commands

| Command | Purpose |
|---------|---------|
| `uv run agent-eval setup` | Walk gcloud auth, ADC, project + location, Vertex AI API enablement, autorater IAM (run once per shell) |
| `uv run agent-eval init` | Scaffold eval files (with optional AI metric generation via `--ai-metrics`) |
| `uv run agent-eval migrate` | Convert legacy `eval/scenarios/` + `golden_dataset.json` into the unified `tests/eval/dataset.jsonl` |
| `uv run agent-eval import --from <evalset>.json` | Flatten an ADK `.evalset.json` file into `tests/eval/dataset.jsonl` |
| `uv run agent-eval run` | Full pipeline: simulate + interact + evaluate + analyze |
| `uv run agent-eval simulate` | Run ADK User Sim + convert traces (multi-turn) |
| `uv run agent-eval interact` | Run queries against a live agent endpoint (single-turn) |
| `uv run agent-eval evaluate` | Run deterministic + LLM-as-judge metrics (supports multiple `--interaction-file`) |
| `uv run agent-eval agent-engine` | Path A — streamlined `create_evaluation_run()` against a deployed Agent Engine |
| `uv run agent-eval analyze` | Generate AI-powered analysis reports |
| `uv run agent-eval convert` | Convert ADK traces to evaluation format (used by simulate) |
| `uv run agent-eval create-dataset` | Convert ADK test files to golden dataset format |
| `uv run agent-eval dashboard` | Launch interactive Gradio dashboard for comparing runs |

---

## Common Tasks You Should Help With

### Interpreting Evaluation Results

- `eval_summary.json` → Aggregated metrics (start here)
- `gemini_analysis.md` → AI root cause analysis
- `question_answer_log.md` → Per-question detailed breakdown with scores

### Debugging Evaluation Issues

- **Use `--debug`** on any command (`run`, `simulate`, `interact`, `evaluate`, `analyze`) to see detailed logs from ADK, Vertex AI SDK, and other services. By default, third-party logs are suppressed to keep the CLI output clean — `--debug` opens the floodgates.
- **Auth issues?** → Re-run `agent-eval init` — it verifies project ID, ADC, API enablement, and quota project automatically
- Zero token usage → `app_name` in `session_input.json` doesn't match the agent module folder name
- "conversation_history required" → Using `MULTI_TURN_*` metrics on a single-turn agent; use `GENERAL_QUALITY` instead
- Empty metrics → Using `GOOGLE_API_KEY` instead of Vertex AI; set `GOOGLE_CLOUD_PROJECT` instead
- Permission denied on autorater → Grant `roles/aiplatform.serviceAgent` to the AI Platform service account

### Creating Custom Metrics

Metrics live in `tests/eval/metrics/metric_definitions.json` (Path A) or `eval/metrics/metric_definitions.json` (Path B / legacy fallback). Users can create them in two ways:

1. **AI generation** (recommended): Run `agent-eval init` and choose "Generate with AI" in Step 3. Select managed metrics (Google's built-in rubrics), then optionally generate custom metrics with Gemini. Custom metrics complement managed ones — they're tailored to the agent's specific behaviors. Re-running `init` preserves existing metrics and pre-checks previous selections. If eval files already exist, they are backed up to `tests/eval/.backup/` (or `eval/.backup/`) before updating.

2. **Manual creation**: Help users write LLM-as-judge metrics with:
   - **CRITICAL:** `dataset_mapping` keys can ONLY be `prompt`, `response`, `reference` — the Vertex AI SDK crashes with any other name. Combine multiple data sources into `reference` using the `template` + `source_columns` syntax.
   - **Per-row capability flags** control which rows a metric runs on (replaces the legacy `applies_to` field):
     - `"requires_reference": true` → only score rows that have reference / expected data (e.g. correctness checks).
     - `"requires_multi_turn": true` → only score rows whose `user_inputs` has more than one turn (e.g. trajectory / conversation metrics).
     - Neither flag set → run on every row (general quality, safety, etc.).
     The evaluator routes per row via `dataset_io.detect_capabilities` — it inspects the row's actual columns instead of trusting a per-metric tag, so mixed-capability datasets just work. Legacy `applies_to: golden_dataset` still maps to `requires_reference: true` for backward compatibility.
   - Clear scoring criteria (what each score level means)
   - `dataset_mapping` pointing to the right trace fields
   - `Score: [X]` format in the template for reliable parsing

### Diagnosing Agent Issues from Metrics

| Signal | Metric to Check | Fix |
|--------|-----------------|-----|
| Agent invents capabilities | custom: `capability_honesty` < 3.0 | Add `**KNOWN LIMITATIONS**` to tool docstrings |
| Agent takes wrong paths | custom: `trajectory_accuracy` < 3.0 | Isolate into specialized sub-agents |
| Tools called with bad args | managed: `TOOL_USE_QUALITY` < 3.0 | Add Pydantic schemas, stricter types |
| High latency, bloated context | deterministic: `prompt_tokens` > 10,000 | Compact stale tool outputs, offload to disk |
| Agent fabricates data on failure | custom: `pipeline_integrity` < 3.0 | Add circuit breaker checks |
| Low cache hits | deterministic: `cache_hit_rate` < 50% | Put static instructions in `global_instruction` |

> The `analyze` command includes ADK-specific design patterns in its Gemini prompt, enabling actionable recommendations mapped to the five Context Engineering Principles. The patterns are in `src/agent_eval/core/adk_optimization_patterns.py`.

---

## Creating Optimization Logs (Comparing Results)

The `analyze` command **automatically** creates and maintains `OPTIMIZATION_LOG.md` in the parent results directory. Every time you run `analyze`, it:
- First run: creates a baseline entry (Iteration 1)
- Subsequent runs: auto-detects the previous run, computes deltas, and appends a new iteration with metric changes, git diff info, and Gemini's comparison summary

```bash
# First run — creates baseline entry
uv run agent-eval analyze --results-dir eval/results/baseline --agent-dir ./my_agent

# Second run — auto-compares to baseline, appends Iteration 2
uv run agent-eval analyze --results-dir eval/results/v2 --agent-dir ./my_agent

# Override which run to compare against
uv run agent-eval analyze --results-dir eval/results/v3 --compare-to eval/results/v1

# Highlight specific metrics in the terminal table
uv run agent-eval analyze --results-dir eval/results/v2 --focus "latency, cache"
```

**For manual optimization logs** (e.g., when using an AI assistant to create a more detailed log), use this prompt structure:

```text
Role: You are a Senior Agent Architect and QA Analyst.
Objective: Update the OPTIMIZATION_LOG.md to document whether the applied strategy worked.

Inputs:
1. Strategy Applied: [e.g., "Iteration 1: Tool Hardening"]
2. New Evaluation Data: [metrics from eval_summary.json]
3. Qualitative Analysis: [key insights from gemini_analysis.md]
4. Current Log: [current OPTIMIZATION_LOG.md content]

Instructions:
1. Update Metrics Table: Calculate deltas. Use 🟢 (improvement) / 🔴 (regression) / ⚪ (neutral).
2. Append Iteration History:
   - Optimization Pillar: (Offload, Reduce, Retrieve, Isolate, Cache)
   - Analysis of Variance: Did quality/trust/scale improve? Quote specific metrics.
   - Evidence: Extract 1-2 specific examples from the analysis.
   - Conclusion: One sentence on the strategic pivot for the next step.
```

### Metric Types

**Deterministic** (auto-extracted from traces, same for all agents):
- `token_usage.*` — total tokens, prompt tokens, estimated cost
- `latency_metrics.*` — total seconds, avg turn latency, first response
- `cache_efficiency.*` — hit rate, cached vs fresh tokens
- `tool_success_rate.*` — success rate, failed calls
- `thinking_metrics.*` — reasoning ratio

**LLM-as-Judge** (configured per agent in `metric_definitions.json`):
- Scores defined by the user's metric templates
- Common ones: `trajectory_accuracy`, `tool_use_quality`, `general_quality`, `safety`

### Emoji Legend
- 🟢 = Improvement (lower tokens/latency OR higher quality scores)
- 🔴 = Regression
- ⚪ = Neutral

---

## Critical Reminders

1. **Always use Vertex AI**, not API keys (evaluation won't work otherwise)
2. **Clear eval_history** before each ADK User Sim run — `simulate` does this automatically; if running manually: `rm -rf <agent_module>/.adk/eval_history/*`
3. **Location is auto-configured** — Gemini 3+ models use `global` automatically via `get_location()` in config.py. Override with `--location` if needed
4. **`app_name` must match the folder name** containing `agent.py`, not the agent's display name
5. **Path A custom LLM metrics translate automatically** — `agent-engine` builds `vt.LLMMetric` from any metric with `template` + `score_range` via `metric_factory.custom_llm_judge` and wraps it for `create_evaluation_run` via `metric_factory.to_evaluation_run_metric`. Don't reintroduce the "skipped, custom LLM metrics aren't supported" warning.
6. **`AGENT_EVAL_NO_PAUSES=1` covers both `_continue` pauses and the `simulate` Run ID prompt.** Any new interactive `Prompt.ask` / `questionary.*` call must guard on `_pauses_disabled()` (or accept a non-interactive default) so CI runs don't deadlock.
7. **`agent-engine` auto-creates the destination GCS bucket** in `--location` if it doesn't exist (uses `google.cloud.storage.Client.create_bucket`). Don't duplicate that logic elsewhere — and don't remove it; first runs depend on it.
