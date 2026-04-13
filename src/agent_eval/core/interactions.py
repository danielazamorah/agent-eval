import json
import logging
import os
import asyncio
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional

from agent_eval.core.agent_client import AgentClient

logger = logging.getLogger("agent_eval.interactions")

def get_golden_questions(filepath: str) -> List[Dict[str, Any]]:
    """Loads questions from a JSON file."""
    try:
        with open(filepath) as f:
            data = json.load(f)
            # Support both 'questions' (consolidated) and 'golden_questions' (source)
            return data.get("questions") or data.get("golden_questions", [])
    except FileNotFoundError:
        raise FileNotFoundError(f"Questions file not found at '{filepath}'")

def filter_questions_by_metadata(questions: List[Dict[str, Any]], filters: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Filters questions based on metadata key-value pairs."""
    if not filters:
        return questions

    filtered_questions = []
    for question in questions:
        metadata = question.get("metadata", {})
        matches_all_filters = True
        for filter_key, filter_values in filters.items():
            # Check if metadata key exists and value is in the allowed list
            # We treat metadata values as strings for comparison
            if filter_key not in metadata or str(metadata[filter_key]) not in filter_values:
                matches_all_filters = False
                break
        if matches_all_filters:
            filtered_questions.append(question)
    return filtered_questions

def parse_metadata_filters(filter_strings: Optional[List[str]]) -> Dict[str, List[str]]:
    """Parses filter strings like 'key:val1,val2' into a dictionary."""
    filters = {}
    if not filter_strings:
        return filters
    for filter_string in filter_strings:
        if ":" not in filter_string:
            logger.warning("Invalid filter format '%s'. Expected 'key:value1,value2'", filter_string)
            continue
        key, values_str = filter_string.split(":", 1)
        values = [v.strip() for v in values_str.split(",")]
        if key in filters:
            filters[key].extend(values)
        else:
            filters[key] = values
    return filters

def parse_state_variables(state_var_strings: Optional[List[str]]) -> Dict[str, Any]:
    """Parses state variable strings like 'key:value' into a dictionary."""
    state_vars = {}
    if not state_var_strings:
        return state_vars
    for s in state_var_strings:
        if ":" not in s:
            logger.warning("Invalid state variable format '%s'. Expected 'key:value'", s)
            continue
        key, value = s.split(":", 1)
        state_vars[key.strip()] = value.strip()
    return state_vars

async def process_single_question(
    question_data: Dict[str, Any],
    agent_client: AgentClient,
    run_id: int,
    user_ldap: str,
    state_vars: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Runs a single question against the agent.
    """
    user_inputs = question_data["user_inputs"]
    agents_evaluated = question_data.get("agents_evaluated", [])
    question_id = question_data["id"]
    question_metadata = question_data.get("metadata", {})
    reference_data = question_data.get("reference_data", {})

    logger.debug("Running question ID: %s (Run %d)...", question_id, run_id)

    try:
        interaction_datetime = datetime.now().isoformat()
        
        # Create session
        session_id = await asyncio.to_thread(agent_client.create_session, **state_vars)

        # Send all turns
        for turn in user_inputs:
            await asyncio.to_thread(agent_client.run_interaction, session_id, turn)

        return {
            "status": json.dumps({"boolean": "success"}),
            "run_id": run_id,
            "question_id": question_id,
            "agents_evaluated": json.dumps(agents_evaluated),
            "user_inputs": json.dumps(user_inputs),
            "question_metadata": json.dumps(question_metadata),
            "interaction_datetime": interaction_datetime,
            "session_id": session_id,
            "base_url": agent_client.base_url,
            "source_type": "interaction",
            "app_name": agent_client.app_name,
            "ADK_USER_ID": agent_client.user_id,
            "USER": user_ldap,
            "reference_data": json.dumps(reference_data),
        }

    except Exception as e:
        error_message = str(e)
        logger.error("Error in question %s: %s", question_id, error_message)
        return {
            "status": json.dumps({"boolean": "failed", "error_message": error_message}),
            "run_id": run_id,
            "question_id": question_id,
            "agents_evaluated": json.dumps(agents_evaluated),
            "user_inputs": json.dumps(user_inputs),
            "question_metadata": json.dumps(question_metadata),
            "interaction_datetime": None,
            "session_id": None,
            "base_url": agent_client.base_url,
            "source_type": "interaction",
            "app_name": agent_client.app_name,
            "ADK_USER_ID": agent_client.user_id,
            "USER": user_ldap,
            "reference_data": json.dumps(reference_data),
        }

class InteractionRunner:
    """
    Orchestrates the running of interactions for a set of questions.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.user_ldap = config.get("user") or os.environ.get("USER") or "unknown"
        self.agent_client = AgentClient(
            base_url=config["base_url"],
            app_name=config["app_name"],
            user_id=config.get("user_id", "eval_user")
        )

    async def run(self) -> pd.DataFrame:
        questions_file = self.config["questions_file"]
        all_questions = get_golden_questions(questions_file)
        
        # Filter
        filters = parse_metadata_filters(self.config.get("metadata_filters"))
        filtered_questions = filter_questions_by_metadata(all_questions, filters)

        # Limit
        num_questions = self.config.get("num_questions", -1)
        if num_questions != -1:
            filtered_questions = filtered_questions[:num_questions]

        state_vars = parse_state_variables(self.config.get("state_variables"))
        runs = self.config.get("runs", 1)

        logger.debug("Starting execution for %d questions, %d runs each.", len(filtered_questions), runs)
        
        tasks = []
        for q in filtered_questions:
            for r in range(1, runs + 1):
                tasks.append(
                    process_single_question(q, self.agent_client, r, self.user_ldap, state_vars)
                )

        results = await asyncio.gather(*tasks)
        return pd.DataFrame(results)
