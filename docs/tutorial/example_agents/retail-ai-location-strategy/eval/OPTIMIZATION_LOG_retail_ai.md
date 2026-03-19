# Workshop Iteration Log: Retail Location Strategy Agent

## 1. Metrics Comparison Table

| Metric Category | Metric Name | Baseline (v0) | Iteration 1 | Iteration 2 | Delta (v0 ⮕ v1) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Strategy (Judge)** | Strategic Rec Quality (General) | 0.08 | - | - | - |
| | Tool Use Quality (0-5) | 5.0 | - | - | - |
| | Trajectory Accuracy (0-5) | 4.0 | - | - | - |
| | Pipeline Integrity (0-5) | 2.0 | - | - | - |
| **Trust (Judge)** | Hallucinations (0-1) | 1.0 | - | - | - |
| | Safety (0-1) | 1.0 | - | - | - |
| **Scale (Det.)** | Avg Input Tokens | 135,448 | - | - | - |
| | Avg Turn Latency (s) | 325.48 | - | - | - |
| | KV-Cache Hit Rate (%) | 0.0% | - | - | - |
| | Total Cost ($) | 0.00 | - | - | - |

---

## 2. Iteration History

### Iteration 0: Baseline (Naive Monolith)
*   **Optimization Path:** Baseline (Initial State)
*   **Status:** 🔴 **Critical Failure**
*   **Implementation Details:**
    *   Initial evaluation of the unoptimized `SequentialAgent` pipeline.
    *   Full context history enabled (`include_contents='default'`).
    *   Tools (`search_places`) return raw JSON directly into the context window.
    *   No caching or event compaction configured.

*   **Analysis of Variance:**
    *   **Analyze Quality:** 🔴 **Critical Failure.** The agent got "dumber." `general_quality` scored **0.08** (Failing). It failed to produce *any* text analysis, returning only a meta-comment about an image.
    *   **Analyze Trust:** 🟢 **High Safety, Low Integrity.** `safety` scored **1.0**, but `pipeline_integrity` was **2.0**. The agent "hallucinated" that it had performed the `GapAnalysis` and `MarketResearch` steps without actually calling those tools.
    *   **Analyze Scale:** 🔴 **Bloated.** Input tokens reached **135,448**, causing a massive **325s** latency. `cache_hit_rate` was **0.0%**.
    *   **Evidence:** In question `seattle_coffee_001`, the user asked to "analyze location viability." The agent ignored this and replied: *"The infographic... has been successfully generated,"* effectively skipping the core analysis task because the context was flooded with `search_places` data.
    *   **Conclusion:** The agent suffers from severe **Context Saturation**. The strategy for the next step is **Reduce** (specifically **Offload**): modify the tools to save data to artifacts instead of dumping it into the prompt.
