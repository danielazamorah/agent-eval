# Example Agents

This folder contains two fully functional ADK agents with pre-configured evaluation setups. Both agents were sourced from the [ADK samples](https://google.github.io/adk-docs/) and scaffolded using the [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack). They are left largely untouched — the focus is on evaluating and optimizing them, not building them from scratch.

We use two different agents to demonstrate different classes of problems in agent evaluation.

## Agents

### [customer-service/](customer-service/)

**Cymbal Home & Garden** — A multi-turn conversational agent designed to provide customer service, help with product selection, manage orders, and offer personalized recommendations. The agent has 12 tools covering cart management, product search, discount approvals, scheduling, and more.

- **Evaluation method:** ADK User Sim (multi-turn scenarios)
- **Why this agent:** Demonstrates evaluation of complex dialogue flows, tool selection across multiple capabilities, context management over long conversations, and capability honesty (does the agent claim it can do things it can't?)
- **Key eval files:**
  - `eval/scenarios/conversation_scenarios.json` — test scenarios for the simulator
  - `eval/scenarios/session_input.json` — session configuration
  - `eval/metrics/metric_definitions.json` — evaluation metrics (trajectory accuracy, capability honesty, tool use quality)

### [retail-ai-location-strategy/](retail-ai-location-strategy/)

A single-turn multi-agent AI pipeline for retail site selection. Given a business type and target area, it runs market research, competitor mapping (via Google Maps Places API), quantitative gap analysis (via code execution), and strategy synthesis to recommend optimal locations.

- **Evaluation method:** DIY Interactions (golden dataset)
- **Why this agent:** Demonstrates evaluation of sequential pipelines with multiple sub-agents, structured JSON responses, tool argument quality, and pipeline integrity (does the agent handle tool failures gracefully or fabricate data?)
- **Key eval files:**
  - `eval/eval_data/golden_dataset.json` — test queries with expected behaviors
  - `eval/metrics/metric_definitions.json` — evaluation metrics (trajectory accuracy, tool use quality, pipeline integrity)

## Getting Started

Each agent is a standalone Python project with its own `pyproject.toml` and dependencies.

```bash
cd customer-service  # or retail-ai-location-strategy
cp .env.example .env  # configure your GCP project and API keys
uv sync
```

See the [tutorial](../tutorial.md) for a complete walkthrough of evaluating and optimizing both agents step by step.
