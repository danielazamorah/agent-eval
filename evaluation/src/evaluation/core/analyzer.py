from __future__ import annotations

import ast
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import pandas as pd
from google import genai
from google.genai.types import HttpOptions

from evaluation.core.gemini_prompt_builder import GeminiAnalysisPrompter


class LogEntry(TypedDict):
    """A structured representation of a single question's evaluation results."""

    question_id: str
    metadata: Dict[str, Any]
    user_inputs: List[str]
    final_response: str
    trace_summary: List[str]
    sub_agent_trace: List[Dict[str, Any]]
    tool_interactions: List[Dict[str, Any]]
    eval_results: Dict[str, Dict[str, Any]]
    latency_summary: Dict[str, Any]
    adk_scores: Dict[str, float]
    agents_evaluated: List[str]


def robust_json_loads(x: Any) -> Optional[Dict[str, Any]]:
    """Safely load JSON strings, handling various input types.

    Tries json.loads first, then ast.literal_eval for Python dict syntax.
    """
    if x is None:
        return None
    if isinstance(x, (dict, list)):
        return x
    if not isinstance(x, str) or not x:
        return None
    try:
        return json.loads(x)
    except (json.JSONDecodeError, TypeError):
        # Try ast.literal_eval for Python dict syntax (single quotes)
        try:
            result = ast.literal_eval(x)
            if isinstance(result, (dict, list)):
                return result
        except (ValueError, SyntaxError):
            pass
        return None


class Analyzer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def _process_log_row(self, row: pd.Series, index: int) -> Optional[LogEntry]:
        """Processes a single DataFrame row to extract structured log data for Markdown reporting."""
        try:
            question_id = row.get("question_id", f"row_{index}")
            metadata = robust_json_loads(row.get("question_metadata", {})) or {}

            # User inputs (all conversation turns)
            user_inputs = robust_json_loads(row.get("user_inputs", []))
            if not isinstance(user_inputs, list):
                user_inputs = [str(user_inputs)] if user_inputs else []

            # Final agent response
            final_response = row.get("final_response", "")

            # Agent trajectory
            trace_summary = robust_json_loads(row.get("trace_summary", []))
            if not isinstance(trace_summary, list):
                trace_summary = []

            # Tool interactions and sub-agent trace (from extracted_data)
            extracted_data = robust_json_loads(row.get("extracted_data", {})) or {}
            tool_interactions = extracted_data.get("tool_interactions", [])
            if not isinstance(tool_interactions, list):
                tool_interactions = []
                
            sub_agent_trace = extracted_data.get("sub_agent_trace", [])
            if not isinstance(sub_agent_trace, list):
                sub_agent_trace = []

            # Evaluation results with scores and explanations
            eval_results = robust_json_loads(row.get("eval_results", "{}")) or {}

            # Latency summary (extract key metrics)
            latency_data = robust_json_loads(row.get("latency_data", []))
            latency_summary = {}
            if isinstance(latency_data, list) and latency_data:
                # Find the root invocation span for total latency
                for span in latency_data:
                    if span.get("name") == "invocation":
                        latency_summary["total_seconds"] = span.get("duration_seconds", 0)
                        break

            # ADK scores (hallucinations, safety)
            adk_scores = {}
            for col in row.index:
                if col.startswith("adk_score."):
                    metric_name = col.replace("adk_score.", "")
                    adk_scores[metric_name] = row[col]

            # Agents evaluated
            agents_evaluated = robust_json_loads(row.get("agents_evaluated", []))
            if not isinstance(agents_evaluated, list):
                agents_evaluated = [agents_evaluated] if agents_evaluated else []

            return LogEntry(
                question_id=question_id,
                metadata=metadata,
                user_inputs=user_inputs,
                final_response=final_response,
                trace_summary=trace_summary,
                sub_agent_trace=sub_agent_trace,
                tool_interactions=tool_interactions,
                eval_results=eval_results,
                latency_summary=latency_summary,
                adk_scores=adk_scores,
                agents_evaluated=agents_evaluated,
            )
        except Exception as e:
            print(f"Error processing row {index}: {e}")
            return None

    def _format_log_entry_markdown(self, entry: LogEntry, entry_num: int) -> str:
        """Formats a single log entry into a comprehensive markdown string."""
        agents = ", ".join(entry["agents_evaluated"])
        metadata_str = ", ".join([f"{k}: {v}" for k, v in entry["metadata"].items()]) or "None"
        latency = entry["latency_summary"].get("total_seconds", "N/A")
        latency_str = f"{latency:.2f}s" if isinstance(latency, (int, float)) else latency

        # Header with key info
        header = f"""## {entry_num}. Question: `{entry['question_id']}`

| Property | Value |
|----------|-------|
| **Agents** | {agents} |
| **Latency** | {latency_str} |
| **Metadata** | {metadata_str} |"""

        # Conversation (interleaved)
        conversation_md = "### Conversation\n\n"
        
        # Get text responses from trace
        text_responses = [t.get("text_response", "") for t in entry["sub_agent_trace"] if t.get("text_response")]
        
        for i, user_input in enumerate(entry["user_inputs"]):
            conversation_md += f"**User Turn {i+1}:**\n> {user_input}\n\n"
            if i < len(text_responses):
                # Indent agent response for clarity
                agent_resp = text_responses[i].replace("\n", "\n  ")
                conversation_md += f"**Agent Turn {i+1}:**\n  {agent_resp}\n\n"

        # Final agent response (summary block)
        final_response = entry["final_response"][:500] + "..." if len(entry["final_response"]) > 500 else entry["final_response"]
        response_md = f"### Final Response Summary\n\n{final_response}\n"

        # Agent trajectory
        trajectory = " → ".join(entry["trace_summary"]) if entry["trace_summary"] else "N/A"
        trajectory_md = f"### Agent Trajectory\n\n`{trajectory}`\n"

        # Tool interactions (concise)
        tools_md = "### Tool Calls\n\n"
        if entry["tool_interactions"]:
            tools_md += "| Tool | Arguments (key) | Result Summary |\n|------|-----------------|----------------|\n"
            for tool in entry["tool_interactions"][:10]:  # Limit to 10 tools
                tool_name = tool.get("tool_name", "unknown")
                args = tool.get("input_arguments", {})
                args_summary = ", ".join(f"{k}" for k in list(args.keys())[:3]) if args else "none"
                result = tool.get("output_result")
                result_summary = "success" if result else "no result"
                if isinstance(result, dict) and "error" in str(result).lower():
                    result_summary = "error"
                tools_md += f"| `{tool_name}` | {args_summary} | {result_summary} |\n"
        else:
            tools_md += "*No tool calls recorded*\n"

        # ADK Scores (if available)
        adk_md = ""
        if entry["adk_scores"]:
            adk_md = "### ADK Evaluation Scores\n\n"
            for metric, score in entry["adk_scores"].items():
                score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
                adk_md += f"- **{metric}:** {score_str}\n"

        # Evaluation metrics with explanations
        metrics_md = "### Evaluation Metrics\n\n"
        for m_name, m_val in entry["eval_results"].items():
            if isinstance(m_val, dict):
                score = m_val.get("score", "N/A")
                score_str = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
                expl = m_val.get("explanation", "")
                # Truncate long explanations
                expl_short = expl[:300] + "..." if len(expl) > 300 else expl
                metrics_md += f"#### {m_name}: **{score_str}**\n\n{expl_short}\n\n"
            else:
                metrics_md += f"- **{m_name}:** {m_val}\n"

        return f"""{header}

{conversation_md}
{response_md}
{trajectory_md}
{tools_md}
{adk_md}
{metrics_md}
"""

    def generate_question_answer_log(self, results_file: Path, output_path: Path) -> bool:
        """Generates a detailed log comparing questions, reference data, and agent output."""
        print(f"\n--- Generating Question-Answer Log from {results_file} ---")
        try:
            df = pd.read_csv(results_file)
            print(f"Loaded {len(df)} evaluation results.")

            log_entries = [
                entry
                for index, row in df.iterrows()
                if (entry := self._process_log_row(row, index)) is not None
            ]

            header = f"# Question-Answer Analysis Log\n\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n**Total Questions:** {len(log_entries)}\n"
            markdown_content = [header]
            markdown_content.extend(
                self._format_log_entry_markdown(entry, i)
                for i, entry in enumerate(log_entries, 1)
            )

            output_path.write_text("---".join(markdown_content), encoding="utf-8")
            print(f"Question-answer log saved to {output_path}")
            return True

        except Exception as e:
            print(f"Error generating question-answer log: {e}")
            return False

    def analyze_evaluation_results(
        self,
        summary_path: Path,
        results_path: Path,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Analyzes evaluation results and returns the content for the Gemini prompt."""
        try:
            summary_data = json.loads(summary_path.read_text())
            results_df = pd.read_csv(results_path)
        except FileNotFoundError as e:
            print(f"Error: Input file not found: {e}")
            return None, None

        # Use 'average_metrics' from summary_data (includes flattened sub-metrics)
        average_metrics = summary_data.get("overall_summary", {}).get("average_metrics", {})
        # Fallback if average_metrics missing (might need calculation if not in summary yet)
        if not average_metrics:
             # Try to reconstruct from deterministic/llm summaries
             overall = summary_data.get("overall_summary", {})
             average_metrics.update(overall.get("deterministic_metrics", {}))
             average_metrics.update(overall.get("llm_based_metrics", {}))

        all_explanations = {metric: [] for metric in average_metrics}

        for _, row in results_df.iterrows():
            try:
                eval_results = robust_json_loads(row["eval_results"])
                if not eval_results: continue
                
                for metric, details in eval_results.items():
                    if (
                        metric in all_explanations
                        and isinstance(details, dict)
                        and "explanation" in details
                        and "score" in details
                    ):
                        all_explanations[metric].append(
                            {
                                "score": details["score"],
                                "explanation": details["explanation"],
                            }
                        )
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        output_lines = ["--- Evaluation Analysis ---\n"]
        for metric, mean_score in average_metrics.items():
            output_lines.append(f"\n## Metric: `{metric}`\n")
            score_str = (
                f"{mean_score:.4f}"
                if isinstance(mean_score, (int, float))
                else str(mean_score)
            )
            output_lines.append(f"**Average Score:** {score_str}\n")

            if explanations := all_explanations.get(metric):
                # Show first 10 explanations as a sample
                explanation_summary = "\n".join(
                    f"- [Score: {exp['score']}] {exp['explanation']}"
                    for exp in explanations[:10]
                )
                output_lines.append(f"**Sample Explanations:**\n{explanation_summary}\n")

        return summary_data, "".join(output_lines)

    def _discover_agent_context(self, agent_dir: Optional[Path]) -> Dict[str, str]:
        """Discovers and loads agent source code and ADK context from agent directory."""
        context = {}
        if not agent_dir or not agent_dir.exists():
            return context

        # Patterns to exclude (virtual environments, caches, etc.)
        exclude_patterns = [".venv", "venv", "__pycache__", ".git", "node_modules", "site-packages"]

        def should_exclude(path: Path) -> bool:
            """Check if path should be excluded based on patterns."""
            path_str = str(path)
            return any(excl in path_str for excl in exclude_patterns)

        # 1. Find agent.py files (only in project source, not dependencies)
        for pattern in ["agent.py", "**/agent.py"]:
            for agent_file in agent_dir.glob(pattern):
                if agent_file.is_file() and not should_exclude(agent_file):
                    try:
                        context[str(agent_file)] = agent_file.read_text()
                        print(f"  Found agent source: {agent_file}")
                    except Exception:
                        pass

        # 2. Find tools.py if exists (only in project source)
        for pattern in ["tools.py", "**/tools.py"]:
            for tools_file in agent_dir.glob(pattern):
                if tools_file.is_file() and not should_exclude(tools_file):
                    try:
                        context[str(tools_file)] = tools_file.read_text()
                        print(f"  Found tools source: {tools_file}")
                    except Exception:
                        pass

        # 3. Load GEMINI.md (ADK context) - extract key sections to keep it concise
        gemini_md = agent_dir / "GEMINI.md"
        if gemini_md.exists():
            try:
                full_content = gemini_md.read_text()
                # Extract relevant sections for evaluation context (first ~4000 chars + key sections)
                # This keeps the context focused on ADK fundamentals
                lines = full_content.split('\n')
                key_sections = []
                in_relevant_section = False
                section_count = 0

                for line in lines:
                    # Include header and first few sections (Core Concepts, Agent Definitions, Tools, State)
                    if line.startswith('## 1.') or line.startswith('## 2.') or line.startswith('## 7.') or line.startswith('## 8.'):
                        in_relevant_section = True
                        section_count += 1
                    elif line.startswith('## ') and section_count > 0:
                        in_relevant_section = False

                    if in_relevant_section or len(key_sections) < 50:  # First 50 lines + key sections
                        key_sections.append(line)

                    if len('\n'.join(key_sections)) > 15000:  # Cap at ~15k chars
                        break

                adk_context = '\n'.join(key_sections)
                context["GEMINI.md (ADK Reference - Key Sections)"] = adk_context
                print(f"  Found ADK context: {gemini_md} ({len(adk_context)} chars)")
            except Exception:
                pass

        return context

    def generate_gemini_analysis(
        self,
        summary_data: dict,
        analysis_content: str,
        raw_dir: Path,
        output_path: Path,
    ) -> None:
        """Generates a detailed technical diagnosis using Gemini.

        Args:
            summary_data: The evaluation summary dict.
            analysis_content: Pre-formatted analysis content.
            raw_dir: Directory for raw/debug files (prompt goes here).
            output_path: Path for the analysis output file.
        """
        # Find relevant context files dynamically
        consolidated_metrics_file = raw_dir / "temp_consolidated_metrics.json"
        question_file = raw_dir / "temp_consolidated_questions.json"

        context_content = {}

        # Load standard context files
        for file_path in [consolidated_metrics_file, question_file]:
            if file_path.exists():
                try:
                    context_content[str(file_path)] = file_path.read_text()
                except Exception:
                    pass

        # Load deterministic metrics logic
        det_metrics_path = Path("src/evaluation/core/deterministic_metrics.py")
        if det_metrics_path.exists():
            try:
                context_content["evaluation/core/deterministic_metrics.py"] = det_metrics_path.read_text()
            except Exception:
                pass

        # Discover agent context from --agent-dir if provided
        agent_dir = self.config.get("agent_dir")
        custom_strategy_content = None
        
        if agent_dir:
            print("\n--- Discovering Agent Context ---")
            agent_context = self._discover_agent_context(Path(agent_dir))
            context_content.update(agent_context)
            
        # Load optimization strategy file if provided via CLI
        strategy_path = self.config.get("strategy_file")
        if strategy_path:
            strategy_file = Path(strategy_path)
            if strategy_file.exists():
                try:
                    custom_strategy_content = strategy_file.read_text()
                    print(f"  Found optimization strategy: {strategy_file}")
                except Exception as e:
                    print(f"  Warning: Could not read strategy file: {e}")
            else:
                print(f"  Warning: Strategy file not found: {strategy_file}")

        prompter = GeminiAnalysisPrompter(
            summary_data=summary_data,
            analysis_content=analysis_content,
            context_files=context_content,
            question_file_path=str(question_file),
            consolidated_metrics_path=str(consolidated_metrics_file),
            # Pass custom config params
            audience=self.config.get("report_audience"),
            tone=self.config.get("report_tone"),
            length=self.config.get("report_length"),
            custom_strategy_content=custom_strategy_content,
        )
        prompt = prompter.build_prompt()

        # Save prompt to raw/ folder for debugging
        (raw_dir / "gemini_prompt.txt").write_text(prompt, encoding="utf-8")

        # Get model from config (default: gemini-3-pro-preview)
        model = self.config.get("model", "gemini-3-pro-preview")

        # Validate model is a supported Gemini model
        supported_models = [
            "gemini-3-pro-preview", "gemini-3-flash-preview",
            "gemini-2.5-pro", "gemini-2.5-flash",
            "gemini-2.0-flash"
        ]
        if model not in supported_models:
            print(f"Warning: Model '{model}' may not be supported. Supported: {', '.join(supported_models)}")

        print(f"\n--- Calling Vertex AI ({model}) to generate root-cause analysis ---")
        try:
            # Use Vertex AI with project/location from environment
            project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")

            # Check for explicit config location first
            location = self.config.get("location")

            if not location:
                # Gemini 3 models require 'global' location, others use us-central1
                # See: https://cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions
                if model.startswith("gemini-3"):
                    location = "global"
                    print(f"  Using 'global' location for {model} (required for Gemini 3 models)")
                else:
                    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

            if not project:
                print("Warning: GOOGLE_CLOUD_PROJECT not set. Trying default credentials...")

            client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options=HttpOptions(api_version="v1")
            )

            response = client.models.generate_content(
                model=model, contents=prompt
            )

            analysis_text = response.text
            output_path.write_text(analysis_text, encoding="utf-8")
            print(f"Analysis report saved to {output_path}")

        except Exception as e:
            print(f"An error occurred while calling the Vertex AI API: {e}")
            print("Tip: Ensure GOOGLE_CLOUD_PROJECT is set and you're authenticated with gcloud.")

    def _find_run_folder(self, results_dir: Path) -> Optional[Path]:
        """
        Find the run folder to analyze. Supports two structures:
        1. Direct run folder: results_dir/raw/evaluation_results_*.csv
        2. Parent folder with timestamp subfolders: results_dir/{timestamp}/raw/...
        """
        # Check if this is a run folder (has raw/ subfolder with results)
        raw_dir = results_dir / "raw"
        if raw_dir.exists():
            results_files = list(raw_dir.glob("evaluation_results_*.csv"))
            if results_files:
                return results_dir

        # Check if this is a parent folder with timestamp subfolders
        subdirs = [d for d in results_dir.iterdir() if d.is_dir() and d.name.isdigit() or "_" in d.name]
        subdirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        for subdir in subdirs:
            raw_dir = subdir / "raw"
            if raw_dir.exists():
                results_files = list(raw_dir.glob("evaluation_results_*.csv"))
                if results_files:
                    return subdir

        # Legacy: Check for results directly in results_dir (old structure)
        results_files = list(results_dir.glob("evaluation_results_*.csv"))
        if results_files:
            print("Note: Found legacy folder structure (no raw/ subfolder)")
            return results_dir

        return None

    def run(self):
        """Main entry point for analysis."""
        results_dir = Path(self.config["results_dir"])
        skip_gemini = self.config.get("skip_gemini", False)
        gcs_bucket = self.config.get("gcs_bucket")

        # Find the run folder (supports datetime folder structure)
        run_folder = self._find_run_folder(results_dir)
        if not run_folder:
            print(f"Error: No evaluation results found in '{results_dir}'")
            return

        print(f"Analyzing run folder: {run_folder}")

        # Determine paths based on folder structure
        raw_dir = run_folder / "raw"
        if raw_dir.exists():
            results_files = list(raw_dir.glob("evaluation_results_*.csv"))
        else:
            # Legacy structure
            results_files = list(run_folder.glob("evaluation_results_*.csv"))
            raw_dir = run_folder  # Use run_folder for raw files in legacy mode

        if not results_files:
            print(f"Error: No 'evaluation_results_*.csv' file found")
            return

        # Sort by modification time, newest first
        results_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        results_file = results_files[0]
        print(f"Analyzing results file: {results_file.name}")

        summary_file = run_folder / "eval_summary.json"
        if not summary_file.exists():
            print(f"Error: summary file not found in '{run_folder}'")
            return

        # 1. Generate Q&A Log (save to run folder)
        qa_log_path = run_folder / "question_answer_log.md"
        self.generate_question_answer_log(results_file, qa_log_path)

        # 2. Generate Gemini Analysis
        if not skip_gemini:
            summary, analysis_content = self.analyze_evaluation_results(
                summary_file, results_file
            )
            if summary and analysis_content:
                analysis_path = run_folder / "gemini_analysis.md"
                self.generate_gemini_analysis(
                    summary, analysis_content, raw_dir, analysis_path
                )

        # 3. GCS Upload (Placeholder)
        if gcs_bucket:
            print(f"\n--- [PLACEHOLDER] Uploading Results to GCS: gs://{gcs_bucket} ---")
