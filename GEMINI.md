# Agent Optimization Workshop Context

> This file provides context for AI assistants. For setup instructions, see [REFERENCE.md](REFERENCE.md#ai-assistant-setup).

---

## Workshop Overview

This is the **Agent Optimization & Evaluation Workshop** for Google Cloud Accelerate '26.

**Objective:** Teach developers to move from prompt engineering to context engineering, using a production-grade evaluation framework to measure and validate agent improvements.

**Key Concepts:**
- Context Engineering: Systematic management of the model's context window (Offload, Reduce, Retrieve, Isolate, Cache)
- Evaluation Framework: 3-step process (Run Interactions → Evaluate → Analyze)
- Hill Climb Methodology: Iterative optimization from M0 (baseline) to M5 (fully optimized)

---

## Repository Structure

```
accelerate_context_engineering_workshop/
├── README.md                  # Workshop guide (linear flow)
├── REFERENCE.md               # Deep dive (CLI, metrics, customization)
├── customer-service/          # Agent A: Multi-turn, reliability focus
├── retail-ai-location-strategy/  # Agent B: Pipeline, scale focus
└── evaluation/                # Shared evaluation CLI (agent-eval)
```

---

## What Participants Are Doing

1. **Running baseline evaluations** on the `main` branch
2. **Checking out optimization branches** (`optimizations/01-tool-definition`, etc.)
3. **Re-running evaluations** to compare before/after metrics
4. **Understanding trade-offs** between quality, cost, and latency

---

## Common Tasks You Should Help With

### Running Evaluations
```bash
# Full pipeline
cd customer-service
rm -rf customer_service/.adk/eval_history/*
uv run adk eval customer_service eval/scenarios/eval_set_with_scenarios.evalset.json

cd ../evaluation
RUN_DIR=$(uv run agent-eval convert --agent-dir ../customer-service/customer_service --output-dir ../customer-service/eval/results | awk -F': ' '/^Run folder:/ {print $2}')
uv run agent-eval evaluate --interaction-file $RUN_DIR/raw/processed_interaction_sim.jsonl --metrics-files ../customer-service/eval/metrics/metric_definitions.json --results-dir $RUN_DIR
uv run agent-eval analyze --results-dir $RUN_DIR --agent-dir ../customer-service --location global
```

### Creating Custom Metrics
Metrics go in `eval/metrics/metric_definitions.json`. Help participants write custom LLM-as-Judge metrics with clear scoring criteria.

### Debugging Evaluation Issues
- Zero token usage → Check `app_name` matches folder name in evalset
- "conversation_history required" → Using MULTI_TURN metrics on single-turn agent
- Empty dashboard → Using API key instead of Vertex AI

### Understanding Results
- `eval_summary.json` → Aggregated metrics
- `gemini_analysis.md` → Root cause analysis
- Low scores → Map to optimization patterns (see README.md Section 5)

---

## Optimization Branches

| Branch | Optimization | Agent | Focus |
|--------|--------------|-------|-------|
| `main` | Baseline | Both | Establish metrics |
| `optimizations/01-tool-definition` | Tool Hardening | Customer Service | Fix hallucinated parameters |
| `optimizations/02-context-compaction` | Reduce Context | Customer Service | Fix "lost in the middle" |
| `optimizations/03-functional-isolation` | Sub-agents | Customer Service | Fix routing confusion |
| `optimizations/04-offload-and-reduce` | Offload & Reduce | Retail AI | Fix token bloat |

---

## Critical Reminders

1. **Always use Vertex AI**, not API keys (evaluation won't work otherwise)
2. **Clear eval_history** before each run: `rm -rf agent/.adk/eval_history/*`
3. **Run `uv sync`** after switching branches
4. **Use `--location global`** for Gemini 2.5 models in analyze command

---

## Creating Optimization Logs (Comparing Results)

When participants run evaluations on baseline vs optimized code, help them create an **OPTIMIZATION_LOG.md** that compares results. This is the key deliverable for understanding what changed.

### Location
Save optimization logs to: `[agent]/eval/results/OPTIMIZATION_LOG.md`

### How to Generate

**Option A: The AI Assist Method (Recommended)**

Use this prompt to have your AI assistant generate the log for you.

```text
Role: You are a Senior Agent Architect and QA Analyst.
Objective: Update the OPTIMIZATION_LOG.md file to prove whether the applied strategy worked.

Inputs:
1. Strategy Applied: [e.g., "Iteration 1: Tool Hardening"]
2. New Evaluation Data: [Paste metrics from eval_summary.json]
3. Qualitative Analysis: [Paste key insights from gemini_analysis.md]
4. Current Log: [Paste current OPTIMIZATION_LOG.md content]

Instructions:
1. Update Metrics Table: Calculate deltas between previous iteration and this one. Use 🟢/🔴/⚪.
2. Append Iteration History:
   - Create a new section for this Iteration.
   - Optimization Pillar: (Offload, Reduce, Retrieve, Isolate, Cache).
   - Analysis of Variance: Did quality/trust/scale improve? Quote specific metrics.
   - Evidence: Extract 1-2 specific conversation examples from the analysis to back up the scores.
   - Conclusion: One sentence summary of the strategic pivot for the next step.
```

**Option B: The Manual Method**

**Step 1: Extract ALL metrics from eval_summary.json files**

The `eval_summary.json` contains two metric categories:
- `deterministic_metrics` - Token usage, latency, cache efficiency (same for all agents)
- `llm_based_metrics` - LLM-as-Judge scores (vary by agent)

```python
import json

def load_summary(path):
    with open(path) as f:
        return json.load(f)

def get_det_metric(data, key):
    """Get deterministic metric by key"""
    return data.get('overall_summary', {}).get('deterministic_metrics', {}).get(key)

def get_llm_metric(data, key):
    """Get LLM metric average by key"""
    m = data.get('overall_summary', {}).get('llm_based_metrics', {}).get(key, {})
    return m.get('average') if isinstance(m, dict) else None

# Load both summaries
baseline = load_summary('eval/results/baseline/eval_summary.json')
optimization = load_summary('eval/results/optimization/eval_summary.json')

# === DETERMINISTIC METRICS (same for all agents) ===
det_metrics = [
    ('token_usage.total_tokens', 'Avg Total Tokens', 'lower'),
    ('token_usage.prompt_tokens', 'Avg Prompt Tokens', 'lower'),
    ('latency_metrics.average_turn_latency_seconds', 'Avg Turn Latency (s)', 'lower'),
    ('cache_efficiency.cache_hit_rate', 'Cache Hit Rate', 'higher'),
    ('thinking_metrics.reasoning_ratio', 'Reasoning Ratio', 'lower'),
    ('tool_success_rate.tool_success_rate', 'Tool Success Rate', 'higher'),
]

print("| Metric | Baseline | Optimization | Delta |")
print("|--------|----------|--------------|-------|")
for key, name, better in det_metrics:
    b, o = get_det_metric(baseline, key), get_det_metric(optimization, key)
    if b is not None and o is not None:
        delta = o - b
        # Determine emoji based on what's "better"
        if better == 'lower':
            emoji = "🟢" if delta < 0 else ("🔴" if delta > 0 else "⚪")
        else:
            emoji = "🟢" if delta > 0 else ("🔴" if delta < 0 else "⚪")
        print(f"| {name} | {b:.2f} | {o:.2f} | {delta:+.2f} {emoji} |")

# === LLM METRICS (vary by agent - check what exists) ===
llm_keys = list(baseline.get('overall_summary', {}).get('llm_based_metrics', {}).keys())
print(f"\nLLM Metrics available: {llm_keys}")

for key in llm_keys:
    b, o = get_llm_metric(baseline, key), get_llm_metric(optimization, key)
    if b is not None and o is not None:
        delta = o - b
        emoji = "🟢" if delta > 0 else ("🔴" if delta < 0 else "⚪")
        print(f"| {key} | {b:.2f} | {o:.2f} | {delta:+.2f} {emoji} |")
```

### Agent-Specific LLM Metrics

**Customer Service Agent:**
| Metric | Description | Range |
|--------|-------------|-------|
| `tool_use_quality` | Did agent use tools correctly? | 0-5 |
| `trajectory_accuracy` | Did agent follow correct steps? | 0-5 |
| `capability_honesty` | Did agent only claim real capabilities? | 0-5 |
| `multi_turn_general_quality` | Overall multi-turn conversation quality | 0-1 |
| `multi_turn_text_quality` | Text quality across turns | 0-1 |

**Retail AI Agent:**
| Metric | Description | Range |
|--------|-------------|-------|
| `tool_use_quality` | Did agent use tools correctly? | 0-5 |
| `trajectory_accuracy` | Did agent follow correct steps? | 0-5 |
| `pipeline_integrity` | Did agent run all stages without hallucination? | 0-5 |
| `general_quality` | Overall response quality | 0-1 |
| `text_quality` | Text quality and clarity | 0-1 |

**Step 2: Read the gemini_analysis.md files** for qualitative insights:
- `baseline/gemini_analysis.md` - What problems exist?
- `optimization/gemini_analysis.md` - What improved? What's still an issue?

**Step 3: Create the OPTIMIZATION_LOG.md with this structure:**

```markdown
# Optimization Log: [Agent Name]

**Branch:** `optimizations/XX-name`
**Optimization:** [Name] (Pillar: Offload/Reduce/Retrieve/Isolate/Cache)
**Date:** YYYY-MM-DD

## 1. Metrics Comparison Table

### Deterministic Metrics (Scale)
| Metric | Baseline | Optimization | Delta |
|--------|----------|--------------|-------|
| Total Tokens | X | Y | -Z 🟢 |
| Turn Latency | Xs | Ys | +Zs 🔴 |

### LLM-as-Judge Metrics (Quality)
| Metric | Baseline | Optimization | Delta |
|--------|----------|--------------|-------|
| tool_use_quality | 3.6 | 4.2 | +0.6 🟢 |
| capability_honesty | 2.2 | 4.2 | +2.0 🟢 |

## 2. Iteration History

### Baseline (M0)
- Key diagnostic signals from AI analysis
- Root causes identified

### Optimization XX
- What was implemented
- What improved (with evidence)
- What trade-offs occurred

## 3. Conclusions
- What worked
- What needs attention
- Recommended next optimization
```

### Example Output
See: `customer-service/eval/results/OPTIMIZATION_LOG.md` for a complete example.

### Emoji Legend for Deltas
- 🟢 = Improvement (lower tokens/latency OR higher quality scores)
- 🔴 = Regression (higher tokens/latency OR lower quality scores)
- ⚪ = Neutral/unchanged

---

## Key Files to Reference

- `README.md` - Workshop guide (linear flow)
- `REFERENCE.md` - Deep dive (CLI, metrics, customization)
- `[agent]/eval/results/OPTIMIZATION_LOG.md` - Optimization comparison reports
- `[agent]/eval/metrics/metric_definitions.json` - Metric configurations
