# Optimization Log: Customer Service Agent

**Current State:** M0 (Baseline)
**Branch:** `main`
**Date:** January 30, 2026

## 1. Metrics Comparison Table

| Metric | M0: Baseline | Delta |
| :--- | :--- | :--- |
| **Capability Honesty** | 1.2 / 5.0 | - |
| **Tool Use Quality** | 3.6 / 5.0 | - |
| **Trajectory Accuracy** | 3.2 / 5.0 | - |
| **Avg Turn Latency** | 6.76s | - |
| **Total Tokens** | 16,857 | - |

## 2. Iteration History

### M0: The Naive Monolith (Baseline)
*   **Optimization Pillar:** N/A (Baseline)
*   **Problem Statement:** The "Signal Problem." Every turn re-processes thousands of static tokens, leading to confusion, logical drift, and hallucinations.
*   **Implementation Details:** 
    *   **Prompt Bloat:** 4,500+ tokens of merged system instructions.
    *   **Attention Diffusion:** 12+ tools attached to a single agent.
    *   **State Rot:** Raw JSON logs and full customer profiles stored in conversation history.
*   **Analysis of Variance:**
    *   **Quality & Trust:** The agent suffers from critical honesty failures (1.2/5.0). It consistently promises actions it cannot perform due to **Attention Diffusion**.
    *   **Scale:** High latency (6.76s avg) and token costs are driven by the massive system prompt overhead.

### Evidence / Talking Points

**1. Hallucinated Delivery Channels (The "Email" Lie)**
*   **Scenario:** User asks for a QR code (Question `68b39c35`).
*   **Agent Response:** _"I've sent the QR code to your email address: alex.johnson@example.com."_
*   **Reality:** The `generate_qr_code` tool returns raw data. There is **zero** code infrastructure to send emails. The agent hallucinates this side effect because it assumes a "helpful" agent would do so.

**2. Fake Tool Capabilities (The "History" Lie)**
*   **Scenario:** User asks to return an item (Question `90f9fb35`).
*   **Agent Response:** _"My tools allow me to see your purchase history with specific items and dates."_
*   **Reality:** The agent has **no** tool to look up purchase history. It only has `access_cart_information`. It hallucinates a database lookup capability to seem competent, setting the user up for failure in the next turn.

**3. Logic Failure (The "Discount" Trap)**
*   **Scenario:** User asks to match a competitor's 15% coupon (Question `b961b0eb`).
*   **Agent Action:** The agent tries to call `approve_discount(15%)` immediately.
*   **Reality:** The tool rejects it ("Max 10%"). The agent then "asks manager," gets approval, and claims _"This discount will be applied,"_ despite having **no tool** to actually apply a 15% discount. It creates a "dead end" where the user thinks a task is done, but the system state is unchanged.

**Conclusion:** The monolithic approach creates a "Latency Floor" and "Attention Diffusion." We must move to specialized tool scopes.
