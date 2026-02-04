import argparse
import concurrent.futures
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from google.cloud import aiplatform
from vertexai import Client, types
from vertexai.preview.evaluation import PointwiseMetric

from evaluation.core.config import CONFIG
from evaluation.core.deterministic_metrics import DETERMINISTIC_METRICS, evaluate_deterministic_metrics
from evaluation.core.data_mapper import map_dataset_columns, robust_json_loads

# Setup Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent_eval")

def serialize_rubric_verdicts(rubric_verdicts: Any) -> Optional[List[Dict]]:
    """Serialize rubric verdicts to JSON-compatible format."""
    if not rubric_verdicts:
        return None
    try:
        verdicts = []
        for verdict in rubric_verdicts:
            if hasattr(verdict, "model_dump"):
                verdicts.append(verdict.model_dump(mode="json", exclude_none=True))
            elif isinstance(verdict, dict):
                verdicts.append(verdict)
            else:
                verdicts.append(str(verdict))
        return verdicts if verdicts else None
    except Exception:
        return None


def parse_eval_result(
    result: Any, metric_name: str, metric_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Standardizes result parsing across different Vertex AI SDK versions.
    Now captures rubric_verdicts for managed rubric-based metrics.
    """
    rows = []

    # Standard SDK / Legacy Path
    if hasattr(result, "metrics_table"):
        df = result.metrics_table
        df["original_index"] = metric_df.index
        return df

    # Preview SDK Path
    if hasattr(result, "eval_case_results"):
        found_key = metric_name
        if result.eval_case_results:
            first_case = result.eval_case_results[0]
            available_metrics = {}
            if hasattr(first_case, "metrics") and first_case.metrics:
                available_metrics = first_case.metrics
            elif (
                hasattr(first_case, "response_candidate_results")
                and first_case.response_candidate_results
            ):
                available_metrics = getattr(
                    first_case.response_candidate_results[0], "metric_results", {}
                )

            for k in [metric_name, metric_name.lower(), metric_name.upper()]:
                if k in available_metrics:
                    found_key = k
                    break
            else:
                if available_metrics:
                    found_key = list(available_metrics.keys())[0]

        for idx, case_result in enumerate(result.eval_case_results):
            original_idx = metric_df.index[idx]
            val = None

            if (
                hasattr(case_result, "response_candidate_results")
                and case_result.response_candidate_results
            ):
                val = getattr(
                    case_result.response_candidate_results[0], "metric_results", {}
                ).get(found_key)
            if val is None:
                val = getattr(case_result, "metrics", {}).get(found_key)

            row_data = {
                "original_index": original_idx,
                f"{metric_name}/score": getattr(val, "score", None) if val else None,
                f"{metric_name}/explanation": getattr(val, "explanation", None) if val else None,
            }

            # Capture rubric_verdicts for managed rubric-based metrics
            if val and hasattr(val, "rubric_verdicts") and val.rubric_verdicts:
                row_data[f"{metric_name}/rubric_verdicts"] = serialize_rubric_verdicts(val.rubric_verdicts)

            # Capture error_message if present
            if val and hasattr(val, "error_message") and val.error_message:
                row_data[f"{metric_name}/error"] = val.error_message

            rows.append(row_data)

    return pd.DataFrame(rows)


def run_single_metric_evaluation(
    task_args: Tuple,
) -> Tuple[Optional[pd.DataFrame], str, Optional[pd.DataFrame]]:
    """Worker function for parallel evaluation.

    Returns:
        Tuple of (parsed_results_df, metric_name, input_dataset_df)
    """
    eval_dataset, metric_obj, metric_df, metric_name, client, retries, delay = task_args

    for attempt in range(retries):
        try:
            logger.info(f"Starting evaluation: {metric_name} (Attempt {attempt + 1})")
            result = client.evals.evaluate(dataset=eval_dataset, metrics=[metric_obj])
            parsed_df = parse_eval_result(result, metric_name, metric_df)
            logger.info(f"Finished evaluation: {metric_name}")
            # Return input dataset along with results for full traceability
            return parsed_df, metric_name, eval_dataset
        except Exception as e:
            logger.error(f"Failed '{metric_name}': {e}")
            if attempt < retries - 1:
                time.sleep(delay * (2**attempt))
            else:
                logger.critical(f"'{metric_name}' exhausted retries.")

    return None, metric_name, None


def load_and_consolidate_metrics(metric_files: List[str]) -> Dict[str, Any]:
    """Load and consolidate metric definitions from multiple JSON files."""
    consolidated = {}
    logger.info("--- Consolidating Metric Definitions ---")
    for file_path in metric_files:
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                prefix = data.get("metric_prefix", "").lstrip("_")
                metrics = data.get("metrics", {})
                for name, definition in metrics.items():
                    # Skip comment entries (strings starting with _comment)
                    if name.startswith("_comment") or not isinstance(definition, dict):
                        continue
                    full_name = f"{prefix}_{name}".lstrip("_")
                    consolidated[full_name] = definition
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            sys.exit(1)
    logger.info(f"Consolidated {len(consolidated)} metrics.")
    return consolidated


def filter_metrics_by_criteria(
    metric_definitions: Dict[str, Any], filters: Dict[str, List[str]]
) -> Dict[str, Any]:
    """Filter metric definitions based on specified criteria."""
    if not filters:
        return metric_definitions
    filtered = {}
    for name, info in metric_definitions.items():
        match = True
        for key, vals in filters.items():
            val_to_check = (
                info.get("metric_type", "llm")
                if key == "metric_type"
                else info.get("agents", ["data_explorer_agent"])
                if key == "agents"
                else name
                if key == "metrics"
                else info.get(key)
            )
            if val_to_check is None:
                match = False
                break
            check_list = (
                val_to_check if isinstance(val_to_check, list) else [str(val_to_check)]
            )
            if not any(str(v) in vals for v in check_list):
                match = False
                break
        if match:
            filtered[name] = info
    return filtered


def save_metrics_summary(
    df: pd.DataFrame,
    results_dir: Path,
    experiment_id: str,
    run_type: str,
    test_description: str,
    metric_definitions: Dict[str, Any] = None,
) -> None:
    """Calculate and save a comprehensive summary of metrics including full input/output."""
    logger.info("--- Generating Metrics Summary ---")

    # Build score_range lookup from metric definitions
    score_ranges = {}
    if metric_definitions:
        for name, info in metric_definitions.items():
            if isinstance(info, dict) and "score_range" in info:
                score_ranges[name] = info["score_range"]

    grouped = df.groupby("question_id")
    all_question_summaries = []
    per_metric_scores = defaultdict(list)

    for question_id, group in grouped:
        group["eval_results"] = group["eval_results"].apply(robust_json_loads)
        det_metrics, llm_metrics = {}, {}
        for result_dict in group["eval_results"].dropna():
            if not isinstance(result_dict, dict):
                continue
            for metric, val in result_dict.items():
                if not isinstance(val, dict):
                    continue
                is_det = metric in DETERMINISTIC_METRICS or any(
                    metric.endswith(f"_{k}") for k in DETERMINISTIC_METRICS
                )
                if "score" in val and val["score"] is not None:
                    try:
                        s = float(val["score"])
                        if not math.isnan(s):
                            per_metric_scores[metric].append(s)
                            if "details" in val and isinstance(val["details"], dict):
                                for k, v in val["details"].items():
                                    if isinstance(v, (int, float)) and not isinstance(
                                        v, bool
                                    ):
                                        per_metric_scores[f"{metric}.{k}"].append(v)
                    except (ValueError, TypeError):
                        pass
                if is_det:
                    det_metrics[metric] = val.get("details") or val.get("score")
                else:
                    # Include all available fields for LLM metrics (full input/output)
                    llm_metric_data = {}

                    # Core output fields
                    if "score" in val:
                        llm_metric_data["score"] = val["score"]
                    if "explanation" in val:
                        llm_metric_data["explanation"] = val["explanation"]

                    # Rubric verdicts for managed rubric-based metrics
                    if "rubric_verdicts" in val:
                        llm_metric_data["rubric_verdicts"] = val["rubric_verdicts"]

                    # Error if present
                    if "error" in val:
                        llm_metric_data["error"] = val["error"]

                    # Input data for full traceability
                    if "input" in val:
                        llm_metric_data["input"] = val["input"]

                    llm_metrics[metric] = llm_metric_data

        metadata = robust_json_loads(group.iloc[0].get("question_metadata", "{}")) or {}
        summary = {
            "question_id": question_id,
            "runs": len(group),
            "deterministic_metrics": det_metrics,
            "llm_metrics": llm_metrics,
        }
        summary.update(metadata)
        all_question_summaries.append(summary)

    det_summary, llm_summary = {}, {}
    for metric, scores in per_metric_scores.items():
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        if any(metric.startswith(f"{k}.") for k in DETERMINISTIC_METRICS):
            det_summary[metric] = avg
        elif metric in DETERMINISTIC_METRICS:
            continue
        else:
            # Include score_range if available
            metric_data = {"average": avg}
            if metric in score_ranges:
                metric_data["score_range"] = score_ranges[metric]
            llm_summary[metric] = metric_data

    output = {
        "experiment_id": experiment_id,
        "run_type": run_type,
        "test_description": test_description,
        "interaction_datetime": datetime.now().isoformat(),
        "overall_summary": {
            "deterministic_metrics": det_summary,
            "llm_based_metrics": llm_summary,
        },
        "per_question_summary": all_question_summaries,
    }
    with open(results_dir / "eval_summary.json", "w") as f:
        json.dump(output, f, indent=4, default=str)
    logger.info(f"Metrics summary saved to {results_dir / 'eval_summary.json'}")


class Evaluator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.project_id = CONFIG.GOOGLE_CLOUD_PROJECT or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = CONFIG.GOOGLE_CLOUD_LOCATION
        
        if not self.project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is not set.")

        aiplatform.init(project=self.project_id, location=self.location)
        self.client = Client(project=self.project_id, location=self.location)

    def evaluate(self, interaction_file: Path, metrics_files: List[str], results_dir: Path):
        logger.info(f"Starting evaluation on {interaction_file}")

        # Load Data - support both CSV and JSONL formats
        file_ext = interaction_file.suffix.lower()
        if file_ext == '.jsonl':
            # JSONL format: use standard json module to avoid ujson "Value is too big" errors
            # with large response payloads (e.g., retail AI full analysis)
            from evaluation.core.converters import read_jsonl
            records = read_jsonl(str(interaction_file))
            interaction_results = pd.DataFrame(records)
            # Ensure question_id is string
            if 'question_id' in interaction_results.columns:
                interaction_results['question_id'] = interaction_results['question_id'].astype(str)
            is_jsonl = True
        else:
            # CSV format: nested structures are JSON strings
            interaction_results = pd.read_csv(interaction_file, dtype={"question_id": str})
            is_jsonl = False

        results_dir.mkdir(parents=True, exist_ok=True)

        # Load Metrics
        metric_definitions = load_and_consolidate_metrics(metrics_files)

        # Apply Filters
        if self.config.get("metric_filters"):
            metric_definitions = filter_metrics_by_criteria(
                metric_definitions, self.config["metric_filters"]
            )

        # Preprocess JSON columns (only needed for CSV format)
        original_df = interaction_results.copy()
        if not is_jsonl:
            json_cols = [
                "extracted_data", "reference_data", "latency_data",
                "agents_evaluated", "user_inputs", "session_trace", "final_session_state"
            ]
            for col in json_cols:
                if col in interaction_results.columns:
                    interaction_results[col] = interaction_results[col].apply(robust_json_loads)

        # Expand data for easy mapping
        dfs = [interaction_results]
        for prefix in [CONFIG.EXTRACTED_DATA_PREFIX, CONFIG.REFERENCE_DATA_PREFIX]:
            if prefix in interaction_results.columns:
                dfs.append(pd.json_normalize(interaction_results[prefix]).add_prefix(f"{prefix}."))
        
        expanded_df = pd.concat(dfs, axis=1)

        # --- Phase 1: Deterministic Metrics ---
        logger.info("--- Phase 1: Deterministic Metrics ---")
        det_results_map = defaultdict(dict)
        
        for index, row in expanded_df.iterrows():
            try:
                if not row.get("final_session_state"):
                    continue
                
                res = evaluate_deterministic_metrics(
                    session_state=row.get("final_session_state") or {},
                    session_trace=row.get("session_trace") or [],
                    agents_evaluated=row.get("agents_evaluated") or [],
                    reference_data=row.get("reference_data") or {},
                    question_metadata=row.get("question_metadata") or {}, # Assuming this is dict from load
                    metrics_to_run=list(DETERMINISTIC_METRICS.keys()),
                    latency_data=row.get("latency_data") or []
                )
                det_results_map[index].update(res)
            except Exception as e:
                logger.error(f"Row {index} deterministic error: {e}")

        # --- Phase 2: Parallel LLM Evaluation ---
        logger.info("--- Phase 2: Parallel LLM Evaluation ---")
        all_llm_results = []
        
        metrics_by_agent = defaultdict(list)
        for name, info in metric_definitions.items():
            # Skip comment entries (strings) and non-dict entries
            if not isinstance(info, dict):
                continue
            for agent in info.get("agents", ["data_explorer_agent"]):
                metrics_by_agent[agent].append((name, info))

        eval_tasks = []
        
        for agent, metrics in metrics_by_agent.items():
            # Filter rows relevant to this agent
            mask = expanded_df["agents_evaluated"].apply(
                lambda x: agent in (x if isinstance(x, list) else [x]) if x else False
            )
            # If default agent, include all if not specified
            if agent == "data_explorer_agent" and not any(mask):
                 mask = [True] * len(expanded_df)

            agent_df = expanded_df[mask].copy()
            if agent_df.empty:
                continue

            for metric_name, info in metrics:
                if info.get("metric_type") == "deterministic":
                    continue

                # For API Predefined metrics, check if we should use raw GEMINI format
                is_managed = info.get("is_managed", False)
                use_gemini_format = info.get("use_gemini_format", False)

                if is_managed and use_gemini_format:
                    # Use raw data with request/response - SDK will auto-detect GEMINI schema
                    # This allows proper parsing of conversation_history from request.contents
                    eval_dataset = original_df[["request", "response"]].copy()
                    logger.info(f"Using GEMINI format for API Predefined metric: {metric_name}")
                else:
                    eval_dataset = map_dataset_columns(
                        agent_df,
                        original_df,
                        info.get("dataset_mapping", {}),
                        metric_name,
                        CONFIG.METRIC_TOOL_USE_QUALITY,
                        is_managed_metric=is_managed,
                    )

                if eval_dataset.empty or len(eval_dataset.columns) == 0:
                    continue

                # Create Metric Object
                if is_managed:
                    m_name = info.get("managed_metric_name", "").upper()
                    metric_obj = getattr(types.RubricMetric, m_name, None) or PointwiseMetric(
                        metric=metric_name, metric_prompt_template=info.get("template", "")
                    )
                else:
                    # Use template directly for custom LLM metrics
                    # The SDK will substitute placeholders from dataset columns
                    template = info.get("template", "")
                    if not template:
                        logger.warning(f"Metric '{metric_name}' has no template defined, skipping")
                        continue
                    metric_obj = types.LLMMetric(
                        name=metric_name,
                        prompt_template=template,
                    )

                eval_tasks.append((
                    eval_dataset, metric_obj, agent_df, metric_name, self.client,
                    CONFIG.MAX_RETRIES, CONFIG.RETRY_DELAY_SECONDS
                ))

        # Run Parallel Execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.MAX_WORKERS) as executor:
            future_to_metric = {
                executor.submit(run_single_metric_evaluation, t): t[3]
                for t in eval_tasks
            }
            for future in concurrent.futures.as_completed(future_to_metric):
                res, m_name, input_df = future.result()
                if res is not None:
                    all_llm_results.append((res, m_name, input_df))

        # --- Consolidate Results ---
        final_df = original_df.copy()
        eval_results_list = [{} for _ in range(len(final_df))]

        # Add Pre-calculated ADK scores from simulation (if present)
        adk_score_cols = [c for c in original_df.columns if c.startswith("adk_score.")]
        for col in adk_score_cols:
            metric_name = col.replace("adk_score.", "")
            for idx, val in original_df[col].items():
                if idx < len(eval_results_list):
                    # Handle potential NaN values from pandas
                    try:
                        if pd.notna(val):
                            eval_results_list[idx][metric_name] = {
                                "score": float(val),
                                "explanation": "Extracted from ADK simulation history."
                            }
                    except (ValueError, TypeError):
                        continue

        # Add Deterministic
        for index, results in det_results_map.items():
            if index < len(eval_results_list):
                eval_results_list[index].update(results)

        # Add LLM with full input/output traceability
        for result_df, metric_name, input_df in all_llm_results:
            for result_idx, row in result_df.iterrows():
                idx = int(row["original_index"])
                if idx < len(eval_results_list):
                    # Get score, handling NaN
                    score = row.get(f"{metric_name}/score")
                    try:
                        if pd.isna(score):
                            score = None
                    except (ValueError, TypeError):
                        pass

                    # Build comprehensive metric result with full output
                    metric_result = {"score": score}

                    # Only include explanation if it has actual content
                    explanation = row.get(f"{metric_name}/explanation")
                    if explanation is not None:
                        try:
                            if pd.isna(explanation):
                                explanation = None
                        except (ValueError, TypeError):
                            pass
                    # Skip empty string explanations (some metrics don't return explanations)
                    if explanation and explanation != "":
                        # Try to parse JSON explanations (HALLUCINATION, GROUNDING return JSON strings)
                        if isinstance(explanation, str) and explanation.startswith("["):
                            try:
                                explanation = json.loads(explanation)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        metric_result["explanation"] = explanation

                    # Include rubric_verdicts if present (managed rubric metrics)
                    rubric_verdicts_key = f"{metric_name}/rubric_verdicts"
                    if rubric_verdicts_key in row and row[rubric_verdicts_key] is not None:
                        metric_result["rubric_verdicts"] = row[rubric_verdicts_key]

                    # Include error if present (check for NaN)
                    error_key = f"{metric_name}/error"
                    if error_key in row:
                        error_val = row[error_key]
                        try:
                            if error_val is not None and not pd.isna(error_val):
                                metric_result["error"] = str(error_val)
                        except (ValueError, TypeError):
                            if error_val is not None:
                                metric_result["error"] = str(error_val)

                    # Include input data for full traceability
                    if isinstance(input_df, pd.DataFrame) and result_idx < len(input_df):
                        input_row = input_df.iloc[result_idx]
                        input_data = {}
                        for col in input_df.columns:
                            val = input_row[col]
                            # Truncate long strings for summary (keep first 500 chars)
                            if isinstance(val, str) and len(val) > 500:
                                input_data[col] = val[:500] + "... [truncated]"
                            elif isinstance(val, (list, dict)):
                                # Handle lists and dicts directly
                                input_data[col] = val
                            elif val is not None:
                                # Use try/except for pd.isna since it can fail on complex types
                                try:
                                    if not pd.isna(val):
                                        input_data[col] = val
                                except (ValueError, TypeError):
                                    input_data[col] = val
                        if input_data:
                            metric_result["input"] = input_data

                    eval_results_list[idx][metric_name] = metric_result

        def json_serializer(obj):
            """Custom serializer that handles NaN, numpy types, and other edge cases."""
            if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                return None
            if hasattr(obj, 'tolist'):  # numpy arrays
                return obj.tolist()
            if hasattr(obj, 'item'):  # numpy scalars
                return obj.item()
            return str(obj)

        final_df["eval_results"] = [json.dumps(r, default=json_serializer) for r in eval_results_list]

        # Use the provided results_dir directly (folder was created by run/convert)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_dir = results_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        # Save raw evaluation results to raw/ subfolder
        out_path = raw_dir / f"evaluation_results_{timestamp}.csv"
        final_df.to_csv(out_path, index=False)
        logger.info(f"Evaluation complete. Results saved to {out_path}")

        # Summary goes to main run folder
        save_metrics_summary(
            final_df,
            results_dir,
            f"eval-{timestamp}",
            self.config.get("input_label", "manual"),
            self.config.get("test_description", "Automated run"),
            metric_definitions=metric_definitions,
        )

        logger.info(f"Run folder: {results_dir}")
        return results_dir
