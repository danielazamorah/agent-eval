# agent-eval — AI Assistant Context

> This file provides context for Claude Code. It is loaded automatically when you run `claude` from a project that uses `agent-eval`.

---

## What is agent-eval?

`agent-eval` is an evaluation CLI for ADK agents. It acts as the glue between OpenTelemetry traces from ADK, Vertex AI Evaluation for LLM-as-judge metrics, and Gemini for analysis.

**The evaluation cycle:**
1. **Interact** — Generate agent traces (ADK User Sim for multi-turn, or DIY for single-turn/live agents)
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

When a user runs `agent-eval init`, it scaffolds an `eval/` folder:

```
my-agent/
├── my_agent/                            # ADK agent source code
│   ├── agent.py
│   ├── tools/
│   └── ...
├── eval/                                # Created by `agent-eval init`
│   ├── metrics/metric_definitions.json  # LLM-as-judge metric rubrics
│   ├── scenarios/                       # User Sim scenarios + session input
│   ├── eval_data/golden_dataset.json    # DIY test queries
│   └── results/                         # Evaluation outputs
│       ├── OPTIMIZATION_LOG.md          # Cumulative optimization comparison
│       └── <timestamp>/
│           ├── eval_summary.json        # Aggregated metrics (start here)
│           ├── gemini_analysis.md       # AI root cause analysis
│           ├── question_answer_log.md   # Per-question breakdown
│           └── raw/                     # Traces, CSVs, prompts
├── pyproject.toml
└── .env
```

---

## CLI Commands

| Command | Purpose |
|---------|---------|
| `uv run agent-eval init` | Scaffold eval folder structure |
| `uv run agent-eval run` | Full pipeline: simulate + interact + evaluate + analyze |
| `uv run agent-eval simulate` | Run ADK User Sim + convert traces (multi-turn) |
| `uv run agent-eval interact` | Run queries against a live agent endpoint (single-turn) |
| `uv run agent-eval evaluate` | Run deterministic + LLM-as-judge metrics (supports multiple `--interaction-file`) |
| `uv run agent-eval analyze` | Generate AI-powered analysis reports |
| `uv run agent-eval convert` | Convert ADK traces to evaluation format (used by simulate) |
| `uv run agent-eval create-dataset` | Convert ADK test files to golden dataset format |

---

## Common Tasks You Should Help With

### Interpreting Evaluation Results

- `eval_summary.json` → Aggregated metrics (start here)
- `gemini_analysis.md` → AI root cause analysis
- `question_answer_log.md` → Per-question detailed breakdown with scores

### Debugging Evaluation Issues

- Zero token usage → `app_name` in `session_input.json` doesn't match the agent module folder name
- "conversation_history required" → Using `MULTI_TURN_*` metrics on a single-turn agent; use `GENERAL_QUALITY` instead
- Empty metrics → Using `GOOGLE_API_KEY` instead of Vertex AI; set `GOOGLE_CLOUD_PROJECT` instead
- Permission denied on autorater → Grant `roles/aiplatform.serviceAgent` to the AI Platform service account

### Creating Custom Metrics

Metrics live in `eval/metrics/metric_definitions.json`. Help users write LLM-as-judge metrics with:
- Clear scoring criteria (what each score level means)
- `dataset_mapping` pointing to the right trace fields
- `Score: [X]` format in the template for reliable parsing

### Diagnosing Agent Issues from Metrics

| Signal | Metric to Check | Fix |
|--------|-----------------|-----|
| Agent invents capabilities | `capability_honesty` < 3.0 | Add `**KNOWN LIMITATIONS**` to tool docstrings |
| Agent takes wrong paths | `trajectory_accuracy` < 3.0 | Isolate into specialized sub-agents |
| Tools called with bad args | `tool_use_quality` < 3.0 | Add Pydantic schemas, stricter types |
| High latency, bloated context | `prompt_tokens` > 10,000 | Compact stale tool outputs, offload to disk |
| Agent fabricates data on failure | `pipeline_integrity` < 3.0 | Add circuit breaker checks |
| Low cache hits | `cache_hit_rate` < 50% | Put static instructions in `global_instruction` |

> The `analyze` command includes ADK-specific design patterns in its Gemini prompt, so the AI analysis provides actionable recommendations with code examples based on these patterns. The patterns are in `src/agent_eval/core/adk_optimization_patterns.py`.

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
3. **Use `--location global`** for Gemini 2.5+ models in the analyze command
4. **`app_name` must match the folder name** containing `agent.py`, not the agent's display name
