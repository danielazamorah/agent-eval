# Agent Optimization & Evaluation Workshop

**Google Cloud Accelerate '26**

Learn to move from trial-and-error prompt engineering to systematic, measurable agent optimization.

---

## Critical Requirement

```
+------------------------------------------------------------------+
|  You MUST use Vertex AI for the evaluation pipeline to work.     |
|                                                                   |
|  Set: GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION             |
|  Do NOT use: GOOGLE_API_KEY (metrics will be empty)              |
+------------------------------------------------------------------+
```

### Getting a GCP Project (Argolis)

If you don't already have a GCP project with Vertex AI enabled, use **Argolis** - Google's internal GCP environment for demos and testing.

1. **Access Argolis:** Navigate to [go/argolis](http://go/argolis)

2. **Create a new project:**
   - Click "Create Project"
   - Choose a descriptive name (e.g., `accelerate-workshop-yourname`)
   - Select your organization

> **Important:** Argolis projects have quotas and are intended for demos/testing. For production workloads, use a standard GCP project.
>
> **Note:** The API enablement and environment setup happen in [Part 2: Workshop Steps](#part-2-workshop-steps) after you install gcloud.

---

## What You'll Do in This Workshop

During this workshop, you will:

1. **Run baseline evaluations** on two agents (Retail AI and Customer Service) to establish starting metrics
2. **Checkout optimization branches** that contain pre-made improvements to the agent source code
3. **Run evaluations on each branch** to measure the impact of the code changes
4. **Compare metrics** between baseline and optimized versions to see what improved (and what didn't)

> **Note:** For the ease of this workshop, you won't modify the agent source code yourself. The optimization branches already contain the code changes. Your job is to run evaluations and interpret the results.

---

## How to Use This Guide

This README is split into two parts:

| Section | Who It's For | What's Inside |
|---------|--------------|---------------|
| **Part 1: Knowing Before Coding** | Everyone | Context covered in the presentation slides. Read if you missed it or want a refresher. |
| **Part 2: Workshop Steps** | Hands-on participants | Step-by-step coding exercises. **Start here if you're ready to code.** |

> **Ready to code?** [Jump to Workshop Step 1](#workshop-step-1-environment-setup)

---

# Part 1: Knowing Before Coding

> **Note:** This section covers what the speakers presented in slides. If you attended the presentation, you can skip directly to [Part 2: Workshop Steps](#part-2-workshop-steps).

## The Problem We're Solving

Prototyping an agent is easy. Graduating it to production is where things fall apart.

| Challenge | The Problem |
|-----------|-------------|
| **The Visibility Gap** | When an agent fails, it doesn't throw a stack trace. It drifts, hallucinates, or gets lost. |
| **The Prompt Trap** | Most optimization stops at prompt engineering. But prompts are fragile. Real improvement requires architectural shifts. |
| **The Validation Hurdle** | Fixing one edge case often degrades another. Without objective measurement, you can't prove optimizations work. |

## The Evaluation Framework

We use a 3-step evaluation process:

```
Step 1: Run Interactions  →  Step 2: Run Evaluation  →  Step 3: Analyze Results
   (Generate traces)          (Grade with metrics)       (AI root cause analysis)
```

| Step | What Happens | Output |
|------|--------------|--------|
| **Interactions** | Run agent through test scenarios | Traces (JSONL) |
| **Evaluation** | Grade interactions with deterministic + LLM metrics | `eval_summary.json` |
| **Analysis** | AI analyzes results, identifies root causes | `gemini_analysis.md` |

## The Test Agents

We use two agents to demonstrate different optimization challenges:

| | Customer Service Agent | Retail AI Agent |
|---|---|---|
| **Problem** | Single agent with 12+ tools. Logic errors, hallucinations. | Processes massive datasets. Token bloat, high latency. |
| **Conversation Type** | Multi-turn (back-and-forth) | Single-turn pipeline |
| **Evaluation Mode** | ADK User Sim | DIY Interactions |
| **Key Metrics** | `trajectory_accuracy`, `tool_use_quality` | `general_quality`, `pipeline_integrity` |

## Context Engineering Principles

> "Context Engineering is the systematic management of the model's context window to maximize Signal-to-Noise Ratio."
>
> **More Context != More Intelligence**

| Principle | When to Apply |
|-----------|---------------|
| **Offload** | Move deterministic logic to tools/code |
| **Reduce** | Summarize history, trim context |
| **Retrieve** | Replace static data with RAG |
| **Isolate** | Split into specialized sub-agents |
| **Cache** | Restructure prompts for prefix caching |

## The Optimization Milestones

| Milestone | Branch | What It Fixes |
|-----------|--------|---------------|
| M0 | `main` | Baseline (no optimizations) |
| M1 | `01-tool-definition` | Tool errors → Stricter schemas |
| M2 | `02-context-compaction` | Context rot → Summarization |
| M3 | `03-functional-isolation` | Wrong tool selection → Sub-agents |
| M3a | `03-functional-isolation-v2` | Sub-agents → Stateless routing |
| M4 | `04-offload-and-reduce` | Token bloat → Offload to code |
| M5 | `05-circuit-breaker` | Hallucinated data → Fail-fast validation |

---

# Part 2: Workshop Steps

> **You're ready to code!** Follow each step in order. If you get stuck, ask for help.

> **Cloudtop Users:** To paste commands into the terminal, use `Ctrl+Shift+V` (not `Ctrl+V`).

---

## Workshop Step 1: Environment Setup

**Goal:** Verify your environment is ready to run evaluations.

### 1.1 Check Prerequisites

Run these commands to verify your setup:

```bash
python3 --version  # Must be 3.10, 3.11, or 3.12 (NOT 3.13+)
uv --version       # Must be installed
gcloud --version   # Must be installed
```

**Missing gcloud?**
Install the Google Cloud SDK: [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)

After installation, run `gcloud init` to configure your default project and region.

**Missing uv?**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Have Python 3.13+?** No problem - uv can manage Python versions for you. After cloning the repo, run:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
```

This creates a virtual environment with Python 3.12 regardless of your system Python version.

### 1.2 Authenticate with Google Cloud (Important!)

This step is **critical** for the evaluation pipeline to work:

```bash
# Check if you're already authenticated
gcloud auth list

# If not authenticated, login:
gcloud auth login

# Set up Application Default Credentials (ADC) - REQUIRED for Vertex AI
gcloud auth application-default login
```

> **Why both commands?** `gcloud auth login` authenticates the CLI. `gcloud auth application-default login` creates credentials that Python libraries (like the evaluation CLI) use to call Vertex AI APIs. **You need both.**

### 1.3 Set Your Project and Enable APIs

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT

# Enable required APIs
gcloud services enable aiplatform.googleapis.com --project=$GOOGLE_CLOUD_PROJECT

# Places API (required for Retail AI competitor mapping)
gcloud services enable places.googleapis.com --project=$GOOGLE_CLOUD_PROJECT
```

### 1.4 Clone and Verify

```bash
# Ensure you have valid credentials for Git-on-Borg
gcert

# Clone the repository
git clone sso://user/jessecarah/accelerate_context_engineering_workshop accelerate
cd accelerate

# Run verification script
./setup_workshop.sh
```

### 1.5 Configure Agent Credentials

**Customer Service Agent:**

```bash
cd customer-service
cp .env.example .env
```

Edit `.env` and set:
```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

**Retail AI Agent:**

```bash
cd ../retail-ai-location-strategy
cp .env.example .env
```

Edit `.env` and set:
```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
MAPS_API_KEY=your-maps-api-key
```

> **Note:** `MAPS_API_KEY` is required for competitor mapping. Get it from [Google Cloud Console](https://console.cloud.google.com/apis/credentials) and enable "Places API".

### 1.6 Install Evaluation CLI

```bash
cd ../evaluation
uv sync
```

**Checkpoint:** You should see no errors. You're ready for the next step.

---

### 1.7 (Optional) Set Up AI Assistant

For faster iteration during the workshop, consider setting up an AI coding assistant:

| Tool | Install | Why Use It |
|------|---------|------------|
| **Gemini CLI** | `npm install -g @google/gemini-cli` | Compare eval results, generate optimization logs |
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` | Code exploration, debugging |

**On Cloudtop?** Use the pre-installed Gemini CLI:
```bash
alias gemini='/google/bin/releases/gemini-cli/tools/gemini'
```

> **Setup details:** See [REFERENCE.md - AI Assistant Setup](REFERENCE.md#ai-assistant-setup-optional) for full configuration with Vertex AI.

---

## Workshop Step 2: Run Interactions

**Goal:** Generate traces by running both agents through test scenarios.

### About the `agent-eval` CLI

Throughout this workshop, you'll use a CLI tool called `agent-eval`. This is a **reference implementation** we built to act as the "glue" between:
- **OpenTelemetry** traces from ADK
- **Vertex AI Evaluation** service for LLM-as-judge metrics
- **Gemini** for analyzing results

The CLI encapsulates scripts for converting traces, running evaluations, and generating analysis. It consolidates our experience with evaluation and how to actually use it for real scenarios. You can use it as-is for any ADK agent - that's our hope! If needed, dive deep into the code, understand the patterns, and adapt it to your customers' specific frameworks.

---

To test an agent, we need traffic. We need to capture traces of agent interactions to use as our evaluation data. We'll use two methods:

| Method | When to Use | Agent |
|--------|-------------|-------|
| **ADK User Sim** | Multi-turn conversations, or when you don't have test data yet | Customer Service |
| **DIY Interactions** | Single-turn agents, deployed agents, or when you have a golden dataset | Retail AI |

---

### Step 2A: Customer Service - ADK User Sim

Writing golden datasets by hand is tedious - you end up needing to hand-write JSON logs or manually simulate multi-turn conversations.

**ADK User Sim solves this.** Instead of writing conversation data, you write *scenarios* - a starting prompt and a conversation plan. The simulator uses another model to act as a user following your plan.

#### 2A.1 Set Up the Simulation

```bash
cd ../customer-service
uv sync

# Create eval set
uv run adk eval_set create customer_service eval_set_with_scenarios

# Add test scenarios (these define HOW the simulated user behaves)
uv run adk eval_set add_eval_case customer_service eval_set_with_scenarios \
  --scenarios_file eval/scenarios/conversation_scenarios.json \
  --session_input_file eval/scenarios/session_input.json
```

#### 2A.2 Run the Simulation

```bash
uv run adk eval customer_service eval_set_with_scenarios
```

This runs for 2-3 minutes. You'll see simulated conversations in real-time.

> **What's happening:** The simulator reads your scenarios, spawns a "user" model that follows the conversation plan, and interacts with your agent. All traces are captured automatically.

#### 2A.3 Convert Traces to Evaluation Format

The `convert` command takes raw ADK traces and standardizes them for the evaluation step.

```bash
cd ../evaluation

# Convert and capture the output folder path automatically
export CS_RUN_DIR=$(uv run agent-eval convert \
  --agent-dir ../customer-service/customer_service \
  --output-dir ../customer-service/eval/results \
  2>&1 | grep "Run folder:" | awk '{print $3}')

echo "Results saved to: $CS_RUN_DIR"
```

---

### Step 2B: Retail AI - DIY Interactions

For single-turn agents or when you already have a golden dataset, you can run **DIY Interactions** - querying the agent directly with test inputs.

The Retail AI agent is a single-turn pipeline. We run it against a **Golden Dataset** - a JSON file with test queries and expected behaviors.

> **Note:** This requires **two terminals** - one for the agent server, one for evaluation.

#### 2B.1 Start the Agent (Terminal 1)

```bash
cd ../retail-ai-location-strategy
uv sync
make dev  # Starts on port 8502
```

**Keep this terminal running.** Open a new terminal for the next steps.

#### 2B.2 Run Test Queries (Terminal 2)

The `interact` command sends queries from your golden dataset to the running agent and collects traces.

```bash
# From a new terminal, navigate to the repo's evaluation folder
cd accelerate/evaluation

# Run interactions and capture the output folder path automatically
export RETAIL_RUN_DIR=$(uv run agent-eval interact \
  --app-name app \
  --questions-file ../retail-ai-location-strategy/eval/eval_data/golden_dataset.json \
  --base-url http://localhost:8502 \
  --results-dir ../retail-ai-location-strategy/eval/results \
  2>&1 | grep "Run folder:" | awk '{print $3}')

echo "Results saved to: $RETAIL_RUN_DIR"
```

This runs for 3-5 minutes.

> **What's happening:** The CLI creates sessions, sends user inputs from the golden dataset, and collects all traces and session data programmatically.

---

## Workshop Step 3: Run Evaluation

**Goal:** Score the interactions using deterministic and LLM-as-judge metrics.

Now that we have traces, we score them. The `evaluate` command:
1. Extracts **deterministic metrics** from traces (latency, tokens, cost)
2. Calls **Vertex AI Evaluation** to run LLM-as-judge metrics (quality, accuracy)

---

### Step 3A: Evaluate Customer Service

```bash
# Uses $CS_RUN_DIR from Step 2A.3
uv run agent-eval evaluate \
  --interaction-file $CS_RUN_DIR/raw/processed_interaction_sim.jsonl \
  --metrics-files ../customer-service/eval/metrics/metric_definitions.json \
  --results-dir $CS_RUN_DIR \
  --input-label baseline
```

---

### Step 3B: Evaluate Retail AI

```bash
# Uses $RETAIL_RUN_DIR from Step 2B.2
uv run agent-eval evaluate \
  --interaction-file $RETAIL_RUN_DIR/raw/processed_interaction_app.jsonl \
  --metrics-files ../retail-ai-location-strategy/eval/metrics/metric_definitions.json \
  --results-dir $RETAIL_RUN_DIR \
  --input-label baseline
```

---

### Understanding Metrics

The evaluation generates `eval_summary.json` with two types of metrics:

**Deterministic Metrics** (extracted from traces):
- `latency_metrics.*` - How long things took
- `token_usage.*` - Input/output tokens, cost
- `cache_efficiency.*` - Cache hit rates
- `tool_success_rate.*` - Tool call success/failure

**LLM-as-Judge Metrics** (scored by Vertex AI):
- `general_quality` - Overall response quality
- `trajectory_accuracy` - Did the agent follow correct steps?
- `tool_use_quality` - Were tools called correctly?

> **Explore the metrics:** See [REFERENCE.md - Deterministic Metrics](REFERENCE.md#deterministic-metrics) for a complete glossary.

---

### Understanding Metric Definitions

Open the metric definitions file to see how LLM-as-judge metrics are configured:

```bash
cat ../retail-ai-location-strategy/eval/metrics/metric_definitions.json
```

Each metric has:
- `metric_type` - "llm" for LLM-as-judge
- `dataset_mapping` - Which trace fields to use
- `template` - The prompt sent to the judge model
- `score_range` - Expected output range

> **Deep dive:** See [REFERENCE.md - Creating Custom Metrics](REFERENCE.md#creating-custom-metrics) for how to add your own.

---

## Workshop Step 4: Analyze Results

**Goal:** Interpret what the metrics mean and identify improvement opportunities.

---

### Step 4A: Analyze Customer Service

```bash
# Uses $CS_RUN_DIR from Step 2A.3
uv run agent-eval analyze \
  --results-dir $CS_RUN_DIR \
  --agent-dir ../customer-service \
  --location global
```

#### Review Results

**Option 1: AI-Generated Analysis (Recommended)**
```bash
cat $CS_RUN_DIR/gemini_analysis.md
```

This markdown file contains Gemini's interpretation of your results, including root cause analysis and improvement suggestions.

**Option 2: Raw Metrics**
```bash
cat $CS_RUN_DIR/eval_summary.json
```

**Option 3: Visual Dashboard**

For interactive comparison of evaluation runs, use the Gradio dashboard:
```bash
cd dashboard
uv run dashboard.py
# Open http://127.0.0.1:7860 in your browser
```
See [`dashboard/README.md`](dashboard/README.md) for detailed usage instructions.

**What to Look For (Customer Service):**

| Metric | Typical Value | What It Means |
|--------|---------------|---------------|
| `trajectory_accuracy` | ~3.6/5 | Agent sometimes takes wrong paths |
| `tool_use_quality` | ~5.0/5 | Tools are called correctly when used |
| `capability_honesty` | ~2.2/5 | Agent may misrepresent what it can do |
| `cache_efficiency.cache_hit_rate` | ~35% | Some caching, room for improvement |
| `latency_metrics.total_latency_seconds` | ~40s | Total conversation duration |

---

### Step 4B: Analyze Retail AI

```bash
# Uses $RETAIL_RUN_DIR from Step 2B.2
uv run agent-eval analyze \
  --results-dir $RETAIL_RUN_DIR \
  --agent-dir ../retail-ai-location-strategy \
  --location global
```

#### Review Results

```bash
cat $RETAIL_RUN_DIR/gemini_analysis.md
```

**What to Look For (Retail AI):**

| Metric | Typical Value | What It Means |
|--------|---------------|---------------|
| `trajectory_accuracy` | ~5.0/5 | Pipeline stages execute in correct order |
| `tool_use_quality` | ~2.0/5 | Tools may be called with suboptimal parameters |
| `pipeline_integrity` | ~2.3/5 | Some stages may not complete properly |
| `general_quality` | ~0.79/1 | Overall response quality is good |
| `latency_metrics.total_latency_seconds` | ~165s | Full pipeline takes several minutes |
| `cache_efficiency.cache_hit_rate` | ~8% | Very low caching - opportunity for optimization |

You can now stop the agent in Terminal 1 (`Ctrl+C`).

> **Tip:** See [REFERENCE.md - Deterministic Metrics](REFERENCE.md#deterministic-metrics) for a complete glossary of all available metrics.

---

## Workshop Step 5: Hill Climbing with Optimization Branches

**Goal:** Apply optimizations and measure their impact.

You now have **baseline metrics** from Steps 2-4. The optimization branches contain pre-made improvements. Your job is to:

1. Checkout an optimization branch
2. Explore what changed in the agent code
3. Run evaluation
4. Compare metrics with baseline
5. Understand the trade-offs
6. **Return here** and move to the next branch

---

### The Optimization Sequence

We'll work through the branches in order. Each branch builds on concepts from the previous one:

| Order | Branch | Agent | Optimization |
|-------|--------|-------|--------------|
| 1 | `optimizations/01-tool-definition` | Customer Service | Tool Schema Hardening |
| 2 | `optimizations/02-context-compaction` | Customer Service | Context Compaction |
| 3 | `optimizations/03-functional-isolation` | Customer Service | Functional Isolation |
| 3a | `optimizations/03-functional-isolation-v2` | Customer Service | Functional Isolation (Iteration) |
| 4 | `optimizations/04-offload-and-reduce` | Retail AI | Offload & Reduce |
| 5 | `optimizations/05-circuit-breaker` | Retail AI | Circuit Breaker |

---

> **Optional: Branch 00 (Model Swap)**
> Before diving into architectural optimizations, you can explore `optimizations/00-model-swap` to see what happens when you *only* change the model (e.g., Flash → Pro). This demonstrates that model swaps alone have trade-offs and aren't a substitute for proper context engineering.
> ```bash
> git checkout optimizations/00-model-swap
> ```

### Start with Branch 01: Tool Schema Hardening

```bash
git checkout optimizations/01-tool-definition
cat README.md  # Follow the branch-specific guide
```

The branch README will guide you through:
1. What optimization was applied
2. How to explore the code changes
3. How to run evaluation
4. How to interpret the results

**When you finish branch 01, return here and continue to branch 02.**

---

### Continue with Branch 02: Context Compaction

```bash
git checkout optimizations/02-context-compaction
cat README.md
```

---

### Continue with Branch 03: Functional Isolation

```bash
git checkout optimizations/03-functional-isolation
cat README.md
```

After exploring branch 03, continue to the iteration:

```bash
git checkout optimizations/03-functional-isolation-v2
cat README.md
```

---

### Continue with Branch 04: Offload & Reduce

```bash
git checkout optimizations/04-offload-and-reduce
cat README.md
```

---

### Continue with Branch 05: Prefix Caching

```bash
git checkout optimizations/05-circuit-breaker
cat README.md
```

---

### Skip to a Specific Branch

If you want to jump ahead or focus on a specific optimization:

```bash
# Jump to any branch
git checkout optimizations/01-tool-definition       # Customer Service
git checkout optimizations/02-context-compaction    # Customer Service
git checkout optimizations/03-functional-isolation  # Customer Service
git checkout optimizations/03-functional-isolation-v2  # Customer Service (iteration)
git checkout optimizations/04-offload-and-reduce    # Retail AI
git checkout optimizations/05-circuit-breaker       # Retail AI
```

---

## Workshop Step 6: Final Thoughts

**Congratulations!** You've completed the Agent Optimization Workshop.

### What You Accomplished

1. **Ran baseline evaluations** on two different agents using two evaluation methods (DIY and User Sim)
2. **Explored deterministic metrics** (latency, tokens, cost) and **LLM-as-judge metrics** (quality, accuracy)
3. **Applied Context Engineering optimizations** through the optimization branches
4. **Compared before/after metrics** to validate improvements

### Key Takeaways

- **Evaluation is a cycle:** Build → Test → Analyze → Repeat
- **Metrics guide decisions:** Don't rely on vibes - measure the impact
- **Trade-offs are real:** Improving one metric may affect another (e.g., slower but more accurate)
- **Context Engineering principles** (Offload, Reduce, Retrieve, Isolate, Cache) provide a systematic approach

### What's Next?

1. **Apply to your own agents** - The `agent-eval` CLI is ready to use with any ADK agent. See [REFERENCE.md](REFERENCE.md) for how to adapt it to other frameworks.
2. **Create custom metrics** - Define metrics specific to your use case. See [REFERENCE.md - Creating Custom Metrics](REFERENCE.md#creating-custom-metrics).
3. **Integrate with CI/CD** - Run evaluations on every code change
4. **Build dashboards** - Push results to BigQuery and visualize in Looker

### Keep Exploring

- **Dive deep into the `agent-eval` CLI** - The code in `evaluation/src/` consolidates all our findings on how to evaluate agents in real scenarios. Understand it, modify it if needed, but it's ready to use for any ADK agent out of the box.
- **Check out [REFERENCE.md](REFERENCE.md)** for:
  - Complete CLI command reference
  - Full deterministic metrics glossary
  - Creating custom LLM-as-judge metrics
  - Troubleshooting common issues
  - Adapting the framework for non-ADK agents
- **Create your own conversation scenarios** for User Sim
- **Experiment with different Context Engineering patterns** on your own agents

---

## Quick Reference

### Full Pipeline: Customer Service (ADK User Sim)

```bash
# Run from repo root (accelerate/)
cd customer-service
rm -rf customer_service/.adk/eval_history/*
rm -f customer_service/*.evalset.json

uv run adk eval_set create customer_service eval_set_with_scenarios
uv run adk eval_set add_eval_case customer_service eval_set_with_scenarios \
  --scenarios_file eval/scenarios/conversation_scenarios.json \
  --session_input_file eval/scenarios/session_input.json
uv run adk eval customer_service eval_set_with_scenarios

cd ../evaluation

# Convert and capture output folder
export CS_RUN_DIR=$(uv run agent-eval convert \
  --agent-dir ../customer-service/customer_service \
  --output-dir ../customer-service/eval/results \
  2>&1 | grep "Run folder:" | awk '{print $3}')

uv run agent-eval evaluate \
  --interaction-file $CS_RUN_DIR/raw/processed_interaction_sim.jsonl \
  --metrics-files ../customer-service/eval/metrics/metric_definitions.json \
  --results-dir $CS_RUN_DIR

uv run agent-eval analyze \
  --results-dir $CS_RUN_DIR \
  --agent-dir ../customer-service \
  --location global
```

### Full Pipeline: Retail AI (DIY Interactions)

```bash
# Terminal 1 (from repo root): Start agent
cd retail-ai-location-strategy && make dev

# Terminal 2 (from repo root): Run evaluation
cd evaluation

# Run interactions and capture output folder
export RETAIL_RUN_DIR=$(uv run agent-eval interact \
  --app-name app \
  --questions-file ../retail-ai-location-strategy/eval/eval_data/golden_dataset.json \
  --base-url http://localhost:8502 \
  --results-dir ../retail-ai-location-strategy/eval/results \
  2>&1 | grep "Run folder:" | awk '{print $3}')

uv run agent-eval evaluate \
  --interaction-file $RETAIL_RUN_DIR/raw/processed_interaction_app.jsonl \
  --metrics-files ../retail-ai-location-strategy/eval/metrics/metric_definitions.json \
  --results-dir $RETAIL_RUN_DIR

uv run agent-eval analyze \
  --results-dir $RETAIL_RUN_DIR \
  --agent-dir ../retail-ai-location-strategy \
  --location global
```

---

## Need Help?

| Resource | What It Contains |
|----------|------------------|
| [REFERENCE.md](REFERENCE.md) | CLI commands, metrics guide, troubleshooting |
| [REFERENCE.md#ai-assistant-setup](REFERENCE.md#ai-assistant-setup-optional) | Gemini CLI setup for AI assistance |
| Speakers | Raise your hand! |

---

## Additional Resources

- [ADK Documentation](https://google.github.io/adk-docs/)
- [ADK User Simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex AI Evaluation](https://cloud.google.com/vertex-ai/docs/generative-ai/evaluation/)
