# Tutorial: Evaluating and Optimizing ADK Agents

A step-by-step walkthrough using the two example agents included in this repository. By the end, you'll understand the full evaluation pipeline and how to apply it to your own agents.

> **Note:** This tutorial is under active validation. The example agents and evaluation workflows have been tested, but some steps or paths may need adjustment as the tool evolves. If you encounter issues, please check the [troubleshooting section](reference.md#troubleshooting) in the reference guide or open an issue.

---

## What You'll Do

1. **Run baseline evaluations** on two agents to establish starting metrics
2. **Apply optimizations** to the agent code (guided, step-by-step)
3. **Re-run evaluations** to measure the impact of each change
4. **Use AI assistants** (Gemini CLI or Claude Code) to analyze, compare, and generate optimization logs

For every step, we follow a rigorous loop inspired by the scientific method:

1. **Hypothesize:** Review evaluation outputs, understand errors/metrics/problems, and propose a code change
2. **Test:** Implement changes and re-run evaluations to generate interpretable results
3. **Analyze:** Review the new data — did the fix work completely, partially, or introduce regressions? What trade-offs exist? Do we now meet the quality criteria to ship the agent?

---

## Prerequisites

1. Complete the [installation steps](../README.md#installation) in the README
2. Ensure `uv run agent-eval --help` works
3. Have a GCP project with Vertex AI enabled
4. (Recommended) Install [Gemini CLI](https://github.com/google-gemini/gemini-cli) or [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/claude-code) for AI-assisted analysis

---

## The Example Agents

Rather than starting from a blank page, this repository includes two fully functional ADK agents sourced from the [ADK samples](https://google.github.io/adk-docs/) and scaffolded using the [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack). These agents are left largely untouched — the focus is on evaluating and optimizing them, not building them from scratch.

We use two different agents to demonstrate different classes of problems:

### Customer Service Agent

**Cymbal Home & Garden** — A multi-turn conversational agent designed to provide customer service, help with product selection, manage orders, and offer personalized recommendations.

- **Evaluation method:** ADK User Sim (multi-turn scenarios)
- **Why this agent:** Demonstrates evaluation of complex dialogue flows, tool selection across multiple capabilities, and context management over long conversations

### Retail AI Location Strategy Agent

A single-turn multi-agent AI pipeline for retail site selection. Given a business type and target area, it runs competitor analysis, foot traffic estimation, and zone scoring to recommend optimal locations.

- **Evaluation method:** DIY Interactions (golden dataset)
- **Why this agent:** Demonstrates evaluation of sequential pipelines, structured JSON responses, and tool argument quality

| Agent | Type | Evaluation Method |
|-------|------|-------------------|
| [customer-service](tutorial/example_agents/customer-service/) | Multi-turn | ADK User Sim |
| [retail-ai-location-strategy](tutorial/example_agents/retail-ai-location-strategy/) | Single-turn | DIY Interactions |

---

## Step 1: Environment Setup

### 1.1 Authenticate with Google Cloud

```bash
gcloud auth login
gcloud auth application-default login

export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT

# Enable required APIs
gcloud services enable aiplatform.googleapis.com --project=$GOOGLE_CLOUD_PROJECT
```

### 1.2 Configure the Example Agents

**Customer Service Agent:**

```bash
cp docs/tutorial/example_agents/customer-service/.env.example \
   docs/tutorial/example_agents/customer-service/.env
```

Edit `docs/tutorial/example_agents/customer-service/.env` and set:
```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

**Retail AI Agent:**

```bash
cp docs/tutorial/example_agents/retail-ai-location-strategy/.env.example \
   docs/tutorial/example_agents/retail-ai-location-strategy/.env
```

Edit `docs/tutorial/example_agents/retail-ai-location-strategy/.env` and set:
```
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
MAPS_API_KEY=your-maps-api-key
```

> **Note:** `MAPS_API_KEY` is required for the competitor mapping feature. Enable the "Places API" in your GCP project and create an API key.

### 1.3 Install Dependencies

```bash
# From repo root — install agent-eval
uv sync

# Install example agent dependencies
uv sync --directory docs/tutorial/example_agents/customer-service
uv sync --directory docs/tutorial/example_agents/retail-ai-location-strategy
```

---

## Step 2: Run Baseline — Customer Service (ADK User Sim)

ADK User Sim generates multi-turn conversations from scenario definitions. Instead of hand-writing conversation data, you write *scenarios* — a starting prompt and a conversation plan. The simulator uses an LLM to act as a user following your plan.

### 2.1 Run the Simulation

```bash
# From the agent-eval repository root:
uv run agent-eval simulate \
  --agent-dir docs/tutorial/example_agents/customer-service/customer_service
```

The `simulate` command handles the full workflow: symlinks scenario files, clears previous traces, creates a fresh eval set, runs ADK User Sim, and converts traces to evaluation format.

### 2.2 Evaluate & Analyze

The `simulate` command prints the exact commands to run next — copy and paste them. They will look like:

```bash
# Run evaluation
uv run agent-eval evaluate \
  --interaction-file docs/tutorial/example_agents/customer-service/customer_service/eval/results/<timestamp>/raw/processed_interaction_sim.jsonl \
  --metrics-files docs/tutorial/example_agents/customer-service/customer_service/eval/metrics/metric_definitions.json \
  --results-dir docs/tutorial/example_agents/customer-service/customer_service/eval/results/<timestamp> \
  --input-label baseline

# Analyze
uv run agent-eval analyze \
  --results-dir docs/tutorial/example_agents/customer-service/customer_service/eval/results/<timestamp> \
  --agent-dir docs/tutorial/example_agents/customer-service/customer_service \
  --location global
```

### 2.3 Review Baseline Results

```bash
cat $CS_RUN_DIR/gemini_analysis.md    # AI-generated analysis
cat $CS_RUN_DIR/eval_summary.json     # Raw metrics
```

**What to expect (Customer Service baseline):**

| Metric | Typical Value | What It Means |
|--------|---------------|---------------|
| `capability_honesty` | ~2.2/5 | Agent claims it can do things it can't |
| `trajectory_accuracy` | ~3.6/5 | Agent sometimes takes wrong paths |
| `tool_use_quality` | ~3.6/5 | Tools are called but not always correctly |
| `prompt_tokens` | ~21,000 | High token usage per turn |
| `avg_turn_latency` | ~11s | Relatively slow responses |

> **Save your baseline results!** Copy the results directory path — you'll compare against it after each optimization.

---

## Step 3: Run Baseline — Retail AI (DIY Interactions)

> **Note:** This requires **two terminals** — one for the agent server, one for evaluation.

### 3.1 Start the Agent (Terminal 1)

```bash
cd docs/tutorial/example_agents/retail-ai-location-strategy
make dev  # Starts on port 8502
```

Keep this terminal running.

### 3.2 Run Interactions & Evaluate (Terminal 2)

```bash
# From repo root
export RETAIL_RUN_DIR=$(uv run agent-eval interact \
  --app-name app \
  --questions-file docs/tutorial/example_agents/retail-ai-location-strategy/app/eval/eval_data/golden_dataset.json \
  --base-url http://localhost:8502 \
  --results-dir docs/tutorial/example_agents/retail-ai-location-strategy/app/eval/results \
  2>&1 | grep "Run folder:" | awk '{print $3}')

echo "Results saved to: $RETAIL_RUN_DIR"

uv run agent-eval evaluate \
  --interaction-file $RETAIL_RUN_DIR/raw/processed_interaction_app.jsonl \
  --metrics-files docs/tutorial/example_agents/retail-ai-location-strategy/app/eval/metrics/metric_definitions.json \
  --results-dir $RETAIL_RUN_DIR \
  --input-label baseline

uv run agent-eval analyze \
  --results-dir $RETAIL_RUN_DIR \
  --agent-dir docs/tutorial/example_agents/retail-ai-location-strategy \
  --location global
```

### 3.3 Review Baseline Results

```bash
cat $RETAIL_RUN_DIR/gemini_analysis.md
```

**What to expect (Retail AI baseline):**

| Metric | Typical Value | What It Means |
|--------|---------------|---------------|
| `trajectory_accuracy` | ~5.0/5 | Pipeline stages execute in correct order |
| `tool_use_quality` | ~2.0/5 | Tools called with suboptimal parameters |
| `general_quality` | ~0.79/1 | Overall response quality is decent |
| `total_tokens` | ~58,000 | Very high token usage |
| `avg_turn_latency` | ~165s | Pipeline takes several minutes |

You can stop the agent in Terminal 1 (`Ctrl+C`) for now.

---

## Step 4: Generate an Optimization Log with AI

Before making any code changes, use an AI assistant to analyze your baseline results and generate your first optimization log. This is the primary method we use to interpret evaluation results and decide what to change.

### 4.1 Start Your AI Assistant

```bash
# From repo root (GEMINI.md / CLAUDE.md are loaded automatically)
gemini    # or: claude
```

### 4.2 Ask It to Analyze the Baseline

Paste this prompt (adjust paths to your actual results):

```
Read the files at:
- <CS_RUN_DIR>/eval_summary.json
- <CS_RUN_DIR>/gemini_analysis.md

Summarize the key metrics and issues found. What is the weakest metric?
Look at the per-question breakdown — which test cases scored lowest and why?

Then generate an OPTIMIZATION_LOG.md that documents:
1. Baseline metrics table
2. The top 3 issues identified
3. A hypothesis for the first optimization to try
4. Which Context Engineering principle applies (Offload, Reduce, Retrieve, Isolate, Cache)
```

The assistant will produce a structured optimization log — save it to `docs/tutorial/example_agents/customer-service/customer_service/eval/results/OPTIMIZATION_LOG.md`.

This is the format you'll update after every optimization cycle.

---

## Step 5: Optimization Exercises — Customer Service Agent

Each exercise below tells you exactly what to change, why, and what to expect. After each change, you re-run the full evaluation pipeline and compare.

### How to Re-Run Evaluation After a Change

After modifying agent code, always run the full cycle from the **agent-eval repository root**:

```bash
# Step 1: Re-run simulation (handles clearing traces, creating eval set, etc.)
uv run agent-eval simulate \
  --agent-dir docs/tutorial/example_agents/customer-service/customer_service

# Step 2: Copy the evaluate and analyze commands printed by simulate
# They include the correct paths for this run's timestamp
```

> **Tip:** The `simulate` command prints the exact `evaluate` and `analyze` commands with the correct paths — just copy and paste them. Change `--input-label` to match your optimization (e.g., `--input-label tool-hardening`).

Then use your AI assistant to compare the new results against the baseline:

```
Compare these two evaluation runs:
- Baseline: <baseline_path>/eval_summary.json
- Optimization: <new_path>/eval_summary.json

Create a metrics comparison table. What improved? What regressed?
Update the OPTIMIZATION_LOG.md with this iteration.
```

---

### Exercise M0: Model Swap

**Principle:** None — this demonstrates why model swaps alone aren't enough.

**Hypothesis:** Swapping to a newer, smarter model should improve all metrics.

**The change:** Edit `docs/tutorial/example_agents/customer-service/customer_service/config.py`:

```python
# BEFORE (line 30):
    model: str = Field(default="gemini-2.5-flash")

# AFTER:
    model: str = Field(default="gemini-3-flash-preview")
```

Also change the location (line 46):
```python
# BEFORE:
    CLOUD_LOCATION: str = Field(default="us-central1")

# AFTER:
    CLOUD_LOCATION: str = Field(default="global")
```

**Re-run evaluation** using the instructions above with `--input-label model-swap`.

**What to expect:**

| Metric | Baseline | Model Swap | Delta |
|--------|----------|------------|-------|
| `trajectory_accuracy` | ~3.2/5 | ~4.0/5 | +0.8 |
| `capability_honesty` | ~1.2/5 | ~1.0/5 | -0.2 |
| `prompt_tokens` | ~21,000 | ~28,000 | +35% |
| `avg_turn_latency` | ~6.8s | ~9.5s | +40% |

**Key insight:** The smarter model improved planning but became a **"High-IQ Liar"** — it hallucinates capabilities with more confidence, uses more tokens, and costs more. A smarter model amplifies your architecture's strengths *and* weaknesses. Context engineering is needed, not just model swaps.

> **After comparing:** Use your AI assistant to update the OPTIMIZATION_LOG.md with the model swap results. Then revert config.py back to `gemini-2.5-flash` / `us-central1` before continuing, or keep `gemini-3-flash-preview` and continue to M1 (the optimizations work with either model, but results will differ).

---

### Exercise M1: Tool Schema Hardening

**Principle:** Retrieve — give the model better definitions so it knows what tools can and cannot do.

**Hypothesis:** The agent hallucinates capabilities (claims it can send emails, apply discounts, see video) because the tool docstrings don't state limitations. Adding explicit `**KNOWN LIMITATIONS**` sections will improve honesty.

**The changes:**

#### 1. Add KNOWN LIMITATIONS to tool docstrings

Edit `docs/tutorial/example_agents/customer-service/customer_service/tools/tools.py`. For each tool, add a `**KNOWN LIMITATIONS**` section to the docstring. Here are the key ones:

**`send_call_companion_link`** — add after the existing docstring:
```python
def send_call_companion_link(phone_number: str) -> str:
    """
    Sends a link to the user's phone number to start a video session.

    **KNOWN LIMITATIONS:**
    * This tool ONLY sends the link.
    * The AI agent CANNOT see the video stream or identify plants visually.
    * After sending the link, you must ask the user to describe the plant textually.

    Args:
        phone_number (str): The phone number to send the link to.
    Returns:
        dict: A dictionary with the status and message.
    """
```

**`approve_discount`** — add limitations:
```python
def approve_discount(discount_type: str, value: float, reason: str) -> str:
    """
    Approve the flat rate or percentage discount requested by the user.

    **KNOWN LIMITATIONS:**
    * This tool is for internal logic checks ONLY.
    * It does NOT directly apply the discount to a user's cart or session.
    * The discount value must be 10 or less.

    Args:
        discount_type (str): The type of discount, either "percentage" or "flat".
        value (float): The value of the discount.
        reason (str): The reason for the discount.
    Returns:
        str: A JSON string indicating the status of the approval.
    """
```

**`sync_ask_for_approval`** — add limitations:
```python
def sync_ask_for_approval(discount_type: str, value: float, reason: str) -> str:
    """
    Asks the manager for approval for a discount.

    **KNOWN LIMITATIONS:**
    * This tool ONLY provides approval status.
    * It does NOT apply the discount automatically.
    * After receiving approval, you must inform the user and explain they can apply it at checkout.

    Args:
        discount_type (str): The type of discount, either "percentage" or "flat".
        value (float): The value of the discount.
        reason (str): The reason for the discount.
    Returns:
        str: A JSON string indicating the status of the approval.
    """
```

**`access_cart_information`** — add limitations:
```python
    """
    Retrieves the customer's cart contents.

    **KNOWN LIMITATIONS:**
    * This tool is READ-ONLY. It cannot modify the cart.
    * Use modify_cart to make changes.
    ...
    """
```

**`modify_cart`** — add limitations:
```python
    """Modifies the user's shopping cart by adding and/or removing items.

    **KNOWN LIMITATIONS:**
    * Cannot modify prices or apply discounts directly.
    * Cannot add items that are out of stock.
    * NEVER modify the cart before the user gives explicit confirmation.
    ...
    """
```

**`generate_qr_code`** — add limitations:
```python
    """Generates a QR code for a discount.

    **KNOWN LIMITATIONS:**
    * Maximum discount: 10% for percentage, $20 for fixed.
    * The QR code is for display only — it cannot be sent via email.
    * The QR code is for in-store use only.
    ...
    """
```

**`schedule_planting_service`** — add limitations:
```python
    """Schedules a planting service appointment.

    **KNOWN LIMITATIONS:**
    * Valid time slots are ONLY '9-12' and '13-16'.
    * Always call get_available_planting_times first.
    ...
    """
```

#### 2. Add CORE OPERATIONAL BOUNDARIES to the system prompt

Edit `docs/tutorial/example_agents/customer-service/customer_service/prompts.py`. Add this section at the beginning of `INSTRUCTION`, right after the first paragraph:

```python
INSTRUCTION = """
You are "Project Pro," the primary AI assistant for Cymbal Home & Garden...
Your main goal is to provide excellent customer service...
Always use conversation context/state or tools to get information. Prefer tools over your own internal knowledge

**CORE OPERATIONAL BOUNDARIES:**
1. **Tool Limitations:** Strictly follow "KNOWN LIMITATIONS" documented for each tool.
2. **Approval vs. Application:** `sync_ask_for_approval` ONLY provides status; does NOT apply discount to cart.
3. **Visual Input:** You CANNOT see video; you must ask users for text descriptions of plants.
4. **Negative Constraints:** You must respect user's explicit "don't do X" instructions.

**Core Capabilities:**
...
```

**Re-run evaluation** with `--input-label tool-hardening`.

**What to expect:**

| Metric | Baseline | M1: Hardening | Delta |
|--------|----------|---------------|-------|
| `capability_honesty` | ~2.2/5 | **~5.0/5** | +2.8 |
| `trajectory_accuracy` | ~3.6/5 | ~3.4/5 | -0.2 |
| `prompt_tokens` | ~22,000 | ~14,000 | -36% |
| `avg_turn_latency` | ~11.0s | ~8.8s | -2.2s |

**Key insight:** Honesty jumps to 5.0 — the agent no longer claims it can see video or apply discounts. Token usage drops 36% because the model stops generating long explanations about things it can't do. But trajectory accuracy regresses slightly — the model is now overloaded with constraints ("Attention Dilution"). The next optimization addresses this.

---

### Exercise M2: Context Compaction

**Principle:** Reduce — surgically strip stale tool outputs from conversation history to prevent context rot.

**Hypothesis:** Older tool outputs (e.g., cart contents from 5 turns ago) are still in the context window, wasting tokens and confusing the model. Replacing them with lightweight placeholders will improve accuracy.

**The change:** Add a `before_model_compaction` callback.

Edit `docs/tutorial/example_agents/customer-service/customer_service/shared_libraries/callbacks.py`. Add this new function:

```python
def before_model_compaction(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    """Compact stale tool outputs to reduce context window size.

    Replaces heavy JSON responses from older turns with lightweight placeholders.
    The agent can re-call tools if it needs the full data again (reversible).
    """
    PROTECT_LAST_N = 3  # Keep the last 3 messages intact

    contents = llm_request.contents
    if len(contents) <= PROTECT_LAST_N:
        return

    # Only compact older messages
    for content in contents[:-PROTECT_LAST_N]:
        if not content.parts:
            continue
        for part in content.parts:
            # Look for function responses (tool outputs)
            if hasattr(part, 'function_response') and part.function_response:
                tool_name = part.function_response.name
                # Replace heavy response with placeholder
                part.function_response.response = {
                    "status": "success",
                    "note": f"Output from {tool_name} was compacted. Re-call the tool if you need the full data."
                }
                logger.debug(f"Compacted output from {tool_name}")
```

Then register it in `docs/tutorial/example_agents/customer-service/customer_service/agent.py`. Add the import and callback:

```python
from .shared_libraries.callbacks import (
    rate_limit_callback,
    before_agent,
    before_tool,
    after_tool,
    before_model_compaction,  # ADD THIS
)

root_agent = Agent(
    ...
    before_model_callback=[rate_limit_callback, before_model_compaction],  # CHANGE THIS (was just rate_limit_callback)
    ...
)
```

**Re-run evaluation** with `--input-label context-compaction`.

**What to expect:**

| Metric | Baseline | M1 | M2: Compaction | Delta (vs Baseline) |
|--------|----------|----|----------------|---------------------|
| `prompt_tokens` | ~21,000 | ~14,000 | **~13,500** | -35% |
| `capability_honesty` | 1.2/5 | 5.0/5 | **4.4/5** | +3.2 |
| `trajectory_accuracy` | 3.2/5 | 3.4/5 | **4.4/5** | +1.2 |
| `tool_use_quality` | 3.6/5 | 3.6/5 | **4.0/5** | +0.4 |

**Key insight:** Trajectory accuracy jumps to 4.4 — the model is no longer confused by stale tool outputs. The compaction is reversible: if the agent needs old data, it can re-call the tool. But analysis may reveal a new issue: **Functional Congestion** — the agent has 12 tools in one bucket, causing scope confusion (e.g., confusing cart tools with order history). This motivates the next optimization.

---

### Exercise M3: Functional Isolation (Multi-Agent)

**Principle:** Isolate — split the monolithic agent into specialized sub-agents to reduce tool confusion.

**Hypothesis:** With 12 tools in one agent, the model confuses tool responsibilities (e.g., routing cart requests to scheduling). Splitting into Triage (router) + Sales + Fulfillment specialists will improve routing accuracy.

**The changes:** This is a larger refactor. You'll split the single agent into three.

#### 1. Create specialized instructions

Edit `docs/tutorial/example_agents/customer-service/customer_service/prompts.py`. Add these new instruction constants:

```python
TRIAGE_INSTRUCTION = """
You are a routing agent for Cymbal Home & Garden customer service.

Your job is to route the customer's request to the right specialist:
- **Sales Agent**: Product recommendations, cart management, discounts, stock checks
- **Fulfillment Agent**: Scheduling planting services, sending care instructions, video calls

Rules:
- Route to the specialist that matches the user's intent
- For ambiguous requests, ask for clarification
- For out-of-scope requests (returns, refunds, complaints), politely decline and explain what you CAN help with
- Do NOT attempt to answer questions yourself — always delegate to a specialist
"""

SALES_INSTRUCTION = """
You are the Sales specialist for Cymbal Home & Garden.

You handle: product recommendations, cart management, discounts, and stock checks.

**CORE OPERATIONAL BOUNDARIES:**
1. **Tool Limitations:** Strictly follow "KNOWN LIMITATIONS" documented for each tool.
2. **Approval vs. Application:** `sync_ask_for_approval` ONLY provides status; does NOT apply discount to cart. After approval, tell the user "Great news! The discount was approved" and explain they apply it at checkout.
3. **Cart Safety:** NEVER modify the cart before the user gives explicit confirmation. Always check cart contents first.
4. **Always check the customer profile** before asking the customer questions — you might already have the answer.
"""

FULFILLMENT_INSTRUCTION = """
You are the Fulfillment specialist for Cymbal Home & Garden.

You handle: scheduling planting services, sending care instructions, and video call assistance.

**CORE OPERATIONAL BOUNDARIES:**
1. **Visual Input:** You CANNOT see video. The `send_call_companion_link` tool ONLY sends a link. After sending, ask the user to describe the plant in text.
2. **Scheduling:** Always call `get_available_planting_times` before booking. Valid slots are '9-12' and '13-16' only.
3. **Care Instructions:** Send via email or SMS using `send_care_instructions`.
"""
```

#### 2. Restructure agent.py

Replace the contents of `docs/tutorial/example_agents/customer-service/customer_service/agent.py` with:

```python
"""Agent module for the customer service agent."""

import logging
import warnings
from google.adk import Agent
from .config import Config
from .prompts import GLOBAL_INSTRUCTION, TRIAGE_INSTRUCTION, SALES_INSTRUCTION, FULFILLMENT_INSTRUCTION
from .shared_libraries.callbacks import (
    rate_limit_callback,
    before_agent,
    before_tool,
    after_tool,
    before_model_compaction,
)
from .tools.tools import (
    send_call_companion_link,
    approve_discount,
    sync_ask_for_approval,
    update_salesforce_crm,
    access_cart_information,
    modify_cart,
    get_product_recommendations,
    check_product_availability,
    schedule_planting_service,
    get_available_planting_times,
    send_care_instructions,
    generate_qr_code,
)

warnings.filterwarnings("ignore", category=UserWarning, module=".*pydantic.*")

configs = Config()
logger = logging.getLogger(__name__)

# Sales specialist: products, cart, discounts
sales_agent = Agent(
    model=configs.agent_settings.model,
    name="sales_agent",
    instruction=SALES_INSTRUCTION,
    tools=[
        access_cart_information,
        modify_cart,
        get_product_recommendations,
        check_product_availability,
        approve_discount,
        sync_ask_for_approval,
        generate_qr_code,
        update_salesforce_crm,
    ],
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
    before_model_callback=[rate_limit_callback, before_model_compaction],
)

# Fulfillment specialist: scheduling, care, video
fulfillment_agent = Agent(
    model=configs.agent_settings.model,
    name="fulfillment_agent",
    instruction=FULFILLMENT_INSTRUCTION,
    tools=[
        schedule_planting_service,
        get_available_planting_times,
        send_care_instructions,
        send_call_companion_link,
    ],
    before_tool_callback=before_tool,
    after_tool_callback=after_tool,
    before_model_callback=[rate_limit_callback, before_model_compaction],
)

# Triage router: no tools, only routes to specialists
# CACHING OPTIMIZATION: Static instruction as global_instruction (cached),
# dynamic customer profile as instruction (changes per session).
root_agent = Agent(
    model=configs.agent_settings.model,
    global_instruction=TRIAGE_INSTRUCTION,
    instruction=GLOBAL_INSTRUCTION,
    name=configs.agent_settings.name,
    sub_agents=[sales_agent, fulfillment_agent],
    before_agent_callback=before_agent,
    before_model_callback=[rate_limit_callback, before_model_compaction],
)

from google.adk.apps.app import App
app = App(root_agent=root_agent, name="customer_service")
```

**Re-run evaluation** with `--input-label functional-isolation`.

**What to expect:**

| Metric | M2: Compaction | M3: Isolation | Delta |
|--------|----------------|---------------|-------|
| `prompt_tokens` | ~13,500 | **~6,000** | -55% |
| `capability_honesty` | 4.4/5 | ~3.2/5 | -1.2 |
| `avg_turn_latency` | 9.20s | ~9.76s | +0.5s |

**Key insight:** 55% token reduction — each specialist sees only its relevant tools, dramatically reducing context. The slight honesty regression is the "15% Paradox": the Sales agent doesn't see the 10% discount limit that lives in `generate_qr_code`'s definition (it's in a different specialist). The fix is to make tool outputs return constraints dynamically (e.g., `sync_ask_for_approval` returns `max_allowed: 10`).

---

## Step 6: Optimization Exercises — Retail AI Agent

### How to Re-Run Evaluation (Retail AI)

After modifying Retail AI code:

```bash
# Terminal 1: Restart the agent
cd docs/tutorial/example_agents/retail-ai-location-strategy
make dev

# Terminal 2: Run evaluation
export RETAIL_RUN_DIR=$(uv run agent-eval interact \
  --app-name app \
  --questions-file docs/tutorial/example_agents/retail-ai-location-strategy/app/eval/eval_data/golden_dataset.json \
  --base-url http://localhost:8502 \
  --results-dir docs/tutorial/example_agents/retail-ai-location-strategy/app/eval/results \
  2>&1 | grep "Run folder:" | awk '{print $3}')

uv run agent-eval evaluate \
  --interaction-file $RETAIL_RUN_DIR/raw/processed_interaction_app.jsonl \
  --metrics-files docs/tutorial/example_agents/retail-ai-location-strategy/app/eval/metrics/metric_definitions.json \
  --results-dir $RETAIL_RUN_DIR \
  --input-label <optimization-name>

uv run agent-eval analyze \
  --results-dir $RETAIL_RUN_DIR \
  --agent-dir docs/tutorial/example_agents/retail-ai-location-strategy \
  --location global
```

---

### Exercise M4: Offload & Reduce

**Principle:** Offload heavy data to disk; Reduce context by injecting only previews.

**Hypothesis:** The `search_places` tool returns 15,000+ tokens of raw JSON per call, saturating the context window. Saving full results to disk and returning only a preview will reduce latency and improve tool quality.

**The changes:**

#### 1. Offload search results to disk

Edit `docs/tutorial/example_agents/retail-ai-location-strategy/app/tools/places_search.py`. Modify the `search_places` function to save full results to a file and return only a preview:

After the line `places.append({...})` and before the `return` statement, add:

```python
        # Offload full results to disk
        import json as _json
        competitors_path = os.path.join(os.path.dirname(__file__), "..", "competitors.json")
        with open(competitors_path, "w") as f:
            _json.dump(places, f, indent=2)

        # Return only a preview (first 3 results)
        preview = places[:3]
        return {
            "status": "success",
            "results": preview,
            "count": len(places),
            "total_saved": len(places),
            "file_path": competitors_path,
            "message": f"Found {len(places)} competitors. Full data saved to {competitors_path}. Preview shows first 3.",
        }
```

And remove the old return block that returned all results.

#### 2. Minify data in the callback

Edit `docs/tutorial/example_agents/retail-ai-location-strategy/app/callbacks/pipeline_callbacks.py`. In the `before_gap_analysis` function, add data minification before the `return None`:

```python
def before_gap_analysis(callback_context: CallbackContext) -> Optional[types.Content]:
    """Log start of gap analysis phase."""
    # ... existing logging code ...

    # Minify competitor data for context injection
    import os
    competitors_path = os.path.join(
        os.path.dirname(__file__), "..", "competitors.json"
    )
    if os.path.exists(competitors_path):
        with open(competitors_path) as f:
            raw_data = json.load(f)
        # Keep only essential fields, rename for brevity
        minified = []
        for c in raw_data:
            minified.append({
                "name": c.get("name", ""),
                "rating": c.get("rating", 0),
                "reviews": c.get("user_ratings_total", 0),
                "price": c.get("price_level", "N/A"),
                "loc": c.get("location", {}),
            })
        callback_context.state["competitor_data_minified"] = json.dumps(minified)
        logger.info(f"  Injected minified competitor data: {len(minified)} entries")

    return None
```

#### 3. Update gap analysis to use minified data

Edit `docs/tutorial/example_agents/retail-ai-location-strategy/app/sub_agents/gap_analysis/agent.py`. In `GAP_ANALYSIS_INSTRUCTION`, add this line to the `## Available Data` section:

```
### COMPETITOR DATA (Minified JSON):
{competitor_data_minified}
```

And update Step 1 to say:

```
### Step 1: Parse Competitor Data
Use the minified competitor JSON data provided above.
Load it with `json.loads()` into a pandas DataFrame for analysis.
```

**Restart the agent and re-run evaluation** with `--input-label offload-reduce`.

**What to expect:**

| Metric | Baseline | M4: Offload & Reduce | Delta |
|--------|----------|----------------------|-------|
| `avg_turn_latency` | ~164.7s | **~113.4s** | -31% |
| `total_tokens` | ~58,619 | **~39,663** | -32% |
| `tool_use_quality` | 2.0/5 | **3.67/5** | +1.67 |

**Key insight:** Big wins on latency, tokens, and tool quality. But the analysis may reveal a dangerous new issue: **"Fail-Open" behavior** — when `search_places` returns 0 results for a remote area, the agent ignores the empty data and fabricates competitor information to fill the report.

---

### Exercise M5: Circuit Breaker

**Principle:** Offload validation — add explicit checkpoints that stop execution on invalid data instead of letting the model hallucinate.

**Hypothesis:** When the search tool returns empty results, the agent fabricates data to satisfy the report format. Adding a circuit breaker that detects empty data and stops the pipeline will improve integrity.

**The changes:**

#### 1. Add a data validity check to gap analysis

Edit `docs/tutorial/example_agents/retail-ai-location-strategy/app/sub_agents/gap_analysis/agent.py`. In `GAP_ANALYSIS_INSTRUCTION`, add a new **Step 0** before Step 1:

```
## Analysis Steps

### Step 0: DATA VALIDITY CHECK (CRITICAL — DO THIS FIRST)
Before ANY analysis, check if the competitor data is valid:
- Parse the competitor data JSON
- If the data is empty (`[]`), has 0 items, or is None:
  - Print: "ERROR: DATA_UNAVAILABLE - No competitor data found for this location."
  - Do NOT proceed with any calculations
  - Do NOT make up or estimate competitor counts
  - STOP EXECUTION immediately
- Only proceed to Step 1 if valid data exists

### Step 1: Parse Competitor Data
...
```

#### 2. Add a fail-safe to strategy advisor

Edit `docs/tutorial/example_agents/retail-ai-location-strategy/app/sub_agents/strategy_advisor/agent.py`. In `STRATEGY_ADVISOR_INSTRUCTION`, add a **Step 0** before "### 1. Data Integration":

```
## Analysis Framework

### Step 0: FAIL-SAFE CHECK (CRITICAL — DO THIS FIRST)
Before synthesizing strategy, check the Gap Analysis input:
- If it contains "ERROR: DATA_UNAVAILABLE" or is empty/None:
  - Do NOT synthesize a false strategy
  - Do NOT make up competitor numbers or ratings
  - Generate a FAILURE REPORT with:
    - market_validation: "Data unavailable for this location"
    - total_competitors_found: 0
    - top_recommendation with location_name: "DATA UNAVAILABLE", overall_score: 0
    - All numeric fields set to 0
  - This is better than fabricated analysis — honesty over completeness

### 1. Data Integration
...
```

**Restart the agent and re-run evaluation** with `--input-label circuit-breaker`.

**What to expect:**

| Metric | M4: Offload | M5: Circuit Breaker | Delta |
|--------|-------------|---------------------|-------|
| `pipeline_integrity` | ~2.33/5 | **~4.0/5** | +1.67 |
| `tool_use_quality` | 3.67/5 | **4.0/5** | +0.33 |
| `avg_turn_latency` | 113.4s | **~81.6s** | -28% |
| `total_tokens` | 39,663 | **~30,269** | -24% |

**Key insight:** The agent now honestly reports "Data Unavailable" instead of fabricating competitor data for remote locations. This is the right behavior — **honesty over completeness**. The latency drop happens because the agent short-circuits instead of spending tokens generating fake analysis.

---

## Step 7: Compare All Results with AI

After running multiple optimizations, use your AI assistant to generate a comprehensive comparison:

```
I have the following evaluation runs for the Customer Service agent:
- Baseline: docs/tutorial/example_agents/customer-service/customer_service/eval/results/<baseline_dir>/eval_summary.json
- Model Swap: docs/tutorial/example_agents/customer-service/customer_service/eval/results/<m0_dir>/eval_summary.json
- Tool Hardening: docs/tutorial/example_agents/customer-service/customer_service/eval/results/<m1_dir>/eval_summary.json
- Context Compaction: docs/tutorial/example_agents/customer-service/customer_service/eval/results/<m2_dir>/eval_summary.json
- Functional Isolation: docs/tutorial/example_agents/customer-service/customer_service/eval/results/<m3_dir>/eval_summary.json

Read all of them and:
1. Create a full progression table showing every metric across all iterations
2. Identify which optimization had the biggest impact
3. Note all regressions and their causes
4. Recommend which combination of optimizations to ship to production
5. Update OPTIMIZATION_LOG.md with the complete iteration history
```

### The Optimization Log as a Lab Notebook

Over time, you build a structured record of every optimization attempt:

```
eval/results/
├── OPTIMIZATION_LOG.md          # Cumulative log of all iterations
├── <baseline_timestamp>/        # M0: Starting point
│   ├── eval_summary.json
│   └── gemini_analysis.md
├── <m1_timestamp>/              # M1: Tool Schema Hardening
│   ├── eval_summary.json
│   └── gemini_analysis.md
├── <m2_timestamp>/              # M2: Context Compaction
│   ├── eval_summary.json
│   └── gemini_analysis.md
└── ...
```

The OPTIMIZATION_LOG becomes your project's "lab notebook" — a data-driven record of what you tried, what worked, and why. It's invaluable for onboarding team members and for making informed decisions about which optimizations to ship.

---

## Full Progression Summary

### Customer Service Agent

| Metric | Baseline | M0: Model Swap | M1: Hardening | M2: Compaction | M3: Isolation |
|--------|----------|----------------|---------------|----------------|---------------|
| `prompt_tokens` | ~21,000 | ~28,000 | ~14,000 | ~13,500 | **~6,000** |
| `capability_honesty` | 1.2/5 | 1.0/5 | 5.0/5 | 4.4/5 | 3.2/5 |
| `trajectory_accuracy` | 3.2/5 | 4.0/5 | 3.4/5 | 4.4/5 | 4.0/5 |
| `tool_use_quality` | 3.6/5 | 3.6/5 | 3.6/5 | 4.0/5 | 3.6/5 |

### Retail AI Agent

| Metric | Baseline | M4: Offload | M5: Circuit Breaker |
|--------|----------|-------------|---------------------|
| `avg_turn_latency` | 164.7s | 113.4s | **81.6s** |
| `total_tokens` | 58,619 | 39,663 | **30,269** |
| `tool_use_quality` | 2.0/5 | 3.67/5 | **4.0/5** |
| `pipeline_integrity` | — | 2.33/5 | **4.0/5** |

---

## Key Takeaways

- **Evaluation is a cycle:** Hypothesize → Test → Analyze → Repeat
- **Metrics guide decisions:** Don't rely on intuition — measure the impact
- **Trade-offs are real:** Improving one metric may affect another (honesty vs. latency, modularity vs. overhead)
- **Model swaps aren't enough:** A smarter model amplifies your architecture's strengths *and* weaknesses
- **Not all optimizations improve metrics:** Naive functional isolation regressed performance — and that's a valuable data point
- **Context Engineering principles** (Offload, Reduce, Retrieve, Isolate, Cache) provide a systematic approach to diagnosing and fixing agent issues
- **AI assistants accelerate the loop:** Use Gemini CLI or Claude Code to interpret results, compare runs, and generate optimization logs

---

## Next Steps

1. **Apply to your own agents** — Run `uv run agent-eval init` in your agent project to get started
2. **Create custom metrics** — See [reference.md — Creating Custom Metrics](reference.md#creating-custom-metrics)
3. **Integrate with CI/CD** — Run evaluations on every code change
4. **Build dashboards** — Push results to BigQuery and visualize in Looker

See [reference.md](reference.md) for the complete CLI reference, metrics glossary, and troubleshooting guide.
