import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

from evaluation.core.interactions import InteractionRunner
from evaluation.core.processor import InteractionProcessor
from evaluation.core.evaluator import Evaluator
from evaluation.core.analyzer import Analyzer
from evaluation.core.converters import AdkHistoryConverter, TestToGoldenConverter, write_jsonl, read_jsonl

def interact_command(args):
    """
    Handles the 'interact' command: InteractionRunner -> InteractionProcessor
    """
    # 1. Configuration
    config = {
        "app_name": args.app_name,
        "questions_file": args.questions_file,
        "base_url": args.base_url,
        "user_id": args.user_id,
        "num_questions": args.num_questions,
        "results_dir": args.results_dir,
        "runs": args.runs,
        "metadata_filters": args.metadata_filters,
        "state_variables": args.state_variables,
        "skip_traces": args.skip_traces,
        "user": args.user
    }

    # 2. Run Interactions
    print("\n=== Step 1: Running Interactions ===")
    runner = InteractionRunner(config)
    
    # We need to run async code here
    try:
        raw_df = asyncio.run(runner.run())
    except Exception as e:
        print(f"Error during interaction run: {e}")
        sys.exit(1)

    if raw_df.empty:
        print("No interactions were run.")
        sys.exit(0)

    # 3. Process/Enrich Data
    print("\n=== Step 2: Processing & Enriching Logs ===")
    processor = InteractionProcessor(config)
    try:
        enriched_df = asyncio.run(processor.process(raw_df))
    except Exception as e:
        print(f"Error during processing: {e}")
        sys.exit(1)

    # 4. Save Output as JSONL (in datetime-stamped folder structure)
    # Using JSONL instead of CSV to avoid serialization issues with nested JSON
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(args.results_dir, timestamp)
    raw_dir = os.path.join(run_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    output_path = os.path.join(raw_dir, f"processed_interaction_{args.app_name}.jsonl")

    # Convert DataFrame to list of dicts and write as JSONL
    records = enriched_df.to_dict(orient='records')
    # Parse JSON strings back to dicts for clean JSONL output
    for record in records:
        for key, value in record.items():
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, (dict, list)):
                        record[key] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

    write_jsonl(records, output_path)
    print(f"\nSUCCESS: Enriched data saved to: {output_path}")
    print(f"Run folder: {run_dir}")
    print("\nTo evaluate, run:")
    print(f"agent-eval evaluate --interaction-file {output_path} --metrics-files <metrics.json> --results-dir {run_dir}")

def evaluate_command(args):
    """
    Handles the 'evaluate' command: Evaluator
    """
    print("\n=== Step 3: Running Evaluation ===")
    
    config = {
        "metric_filters": None, # Could add arg for this
        "input_label": args.input_label,
        "test_description": args.test_description
    }
    
    # Parse metric filters if provided
    if args.metric_filter:
        filters = {}
        for f in args.metric_filter:
            k, v = f.split(":", 1)
            filters[k] = v.split(",")
        config["metric_filters"] = filters

    evaluator = Evaluator(config)
    
    try:
        evaluator.evaluate(
            interaction_file=Path(args.interaction_file),
            metrics_files=args.metrics_files,
            results_dir=Path(args.results_dir)
        )
        print(f"\nEvaluation complete. To analyze results, run:\nagent-eval analyze --results-dir {args.results_dir}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error during evaluation: {e}")
        sys.exit(1)

def analyze_command(args):
    """
    Handles the 'analyze' command: Analyzer
    """
    print("\n=== Step 4: Analyzing Results ===")

    config = {
        "results_dir": args.results_dir,
        "agent_dir": args.agent_dir,
        "model": args.model,
        "location": args.location,
        "skip_gemini": args.skip_gemini,
        "gcs_bucket": args.gcs_bucket,
        "strategy_file": args.strategy_file,
        "report_audience": args.report_audience,
        "report_tone": args.report_tone,
        "report_length": args.report_length
    }

    analyzer = Analyzer(config)
    analyzer.run()

def convert_command(args):
    """
    Handles the 'convert' command: AdkHistoryConverter
    Outputs JSONL format for clean handling of nested JSON data.
    """
    print("\n=== Converting ADK History to Dataset ===")

    try:
        converter = AdkHistoryConverter(args.agent_dir, args.questions_file)
        records = converter.run()

        if not records:
            print("No history found to convert.")
            return

        # Create datetime-stamped folder structure (same as run command)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(args.output_dir, timestamp)
        raw_dir = os.path.join(run_dir, "raw")
        os.makedirs(raw_dir, exist_ok=True)

        # Auto-name output if not provided - now using .jsonl extension
        if not args.output_file:
            output_path = os.path.join(raw_dir, f"processed_interaction_sim.jsonl")
        else:
            # Ensure .jsonl extension
            output_file = args.output_file
            if not output_file.endswith('.jsonl'):
                output_file = output_file.replace('.csv', '.jsonl')
                if not output_file.endswith('.jsonl'):
                    output_file += '.jsonl'
            output_path = os.path.join(raw_dir, output_file)

        write_jsonl(records, output_path)
        print(f"SUCCESS: Converted {len(records)} interactions to: {output_path}")
        print(f"Run folder: {run_dir}")
        print("\nTo evaluate, run:")
        print(f"agent-eval evaluate --interaction-file {output_path} --metrics-files <metrics.json> --results-dir {run_dir}")

    except Exception as e:
        print(f"Error converting history: {e}")
        sys.exit(1)

def create_dataset_command(args):
    """
    Handles the 'create-dataset' command: TestToGoldenConverter
    """
    print("\n=== Creating Golden Dataset from Test Data ===")
    
    try:
        converter = TestToGoldenConverter()
        converter.convert(
            input_path=args.input,
            output_path=args.output,
            agent_name=args.agent_name,
            metadata_pairs=args.metadata,
            id_prefix=args.prefix
        )
        print(f"SUCCESS: Dataset created at: {args.output}")
    except Exception as e:
        print(f"Error creating dataset: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Agent Evaluation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- Command: interact ---
    interact_parser = subparsers.add_parser("interact", help="Run interactions against a live agent and process logs.")
    interact_parser.add_argument("--app-name", required=True, help="Name of the agent application.")
    interact_parser.add_argument("--questions-file", required=True, help="Path to the Golden Dataset JSON.")
    interact_parser.add_argument("--base-url", default="http://localhost:8080", help="Agent API URL.")
    interact_parser.add_argument("--user-id", default="eval_user", help="Session User ID.")
    interact_parser.add_argument("--results-dir", default="results", help="Directory for outputs.")
    interact_parser.add_argument("--num-questions", type=int, default=-1, help="Limit number of questions.")
    interact_parser.add_argument("--runs", type=int, default=1, help="Runs per question.")
    interact_parser.add_argument("--skip-traces", action="store_true", help="Skip trace retrieval (faster).")
    interact_parser.add_argument("--filter", action="append", dest="metadata_filters", help="Metadata filters (key:val).")
    interact_parser.add_argument("--state", action="append", dest="state_variables", help="State variables (key:val).")
    interact_parser.add_argument("--user", default=os.environ.get("USER"), help="Operator username.")
    interact_parser.set_defaults(func=interact_command)

    # --- Command: evaluate ---
    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation metrics on processed logs.")
    eval_parser.add_argument("--interaction-file", required=True, help="Path to processed_interaction CSV.")
    eval_parser.add_argument("--metrics-files", nargs="+", required=True, help="Paths to metric definition JSONs.")
    eval_parser.add_argument("--results-dir", required=True, help="Directory for outputs.")
    eval_parser.add_argument("--input-label", default="manual", help="Label for this run.")
    eval_parser.add_argument("--test-description", default="Automated evaluation", help="Description.")
    eval_parser.add_argument("--filter", action="append", dest="metric_filter", help="Metric filters (key:val).")
    eval_parser.set_defaults(func=evaluate_command)

    # --- Command: analyze ---
    analyze_parser = subparsers.add_parser("analyze", help="Analyze evaluation results and generate reports.")
    analyze_parser.add_argument("--results-dir", required=True, help="Directory containing evaluation results.")
    analyze_parser.add_argument("--agent-dir", help="Path to agent directory (for source code context). Auto-discovers agent.py and GEMINI.md.")
    analyze_parser.add_argument("--strategy-file", help="Path to a custom optimization strategy Markdown file to guide the analysis.")
    analyze_parser.add_argument("--report-audience", help="Customize the target audience for the Gemini analysis.")
    analyze_parser.add_argument("--report-tone", help="Customize the tone of the Gemini analysis.")
    analyze_parser.add_argument("--report-length", help="Customize the length of the Gemini analysis.")
    analyze_parser.add_argument("--model", default="gemini-3-pro-preview",
                                help="Gemini model for analysis (default: gemini-3-pro-preview).")
    analyze_parser.add_argument("--location", help="Vertex AI location (e.g., us-central1, global).")
    analyze_parser.add_argument("--skip-gemini", action="store_true", help="Skip AI-powered analysis.")
    analyze_parser.add_argument("--gcs-bucket", help="GCS bucket for upload.")
    analyze_parser.set_defaults(func=analyze_command)

    # --- Command: convert ---
    convert_parser = subparsers.add_parser("convert", help="Convert ADK simulation history to evaluation format.")
    convert_parser.add_argument("--agent-dir", required=True, help="Path to the agent directory (containing .adk/eval_history).")
    convert_parser.add_argument("--questions-file", help="Optional: Path to Golden Dataset to merge reference data.")
    convert_parser.add_argument("--output-dir", default="results", help="Directory for outputs.")
    convert_parser.add_argument("--output-file", help="Custom output filename.")
    convert_parser.set_defaults(func=convert_command)

    # --- Command: create-dataset ---
    create_dataset_parser = subparsers.add_parser("create-dataset", help="Convert raw test turns (JSON) to Golden Dataset format.")
    create_dataset_parser.add_argument("--input", required=True, help="Path to raw JSON input (list of turns).")
    create_dataset_parser.add_argument("--output", required=True, help="Path to output Golden Dataset JSON.")
    create_dataset_parser.add_argument("--agent-name", required=True, help="Name of the agent.")
    create_dataset_parser.add_argument("--metadata", action="append", help="Metadata (key:value).")
    create_dataset_parser.add_argument("--prefix", default="q", help="Question ID prefix.")
    create_dataset_parser.set_defaults(func=create_dataset_command)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
