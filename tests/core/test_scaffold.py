"""Tests for scaffold.py — focused on dataset.jsonl AI-content derivation."""

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval.core.scaffold import _rows_from_recommendations, scaffold_dataset_jsonl


class TestRowsFromRecommendations(unittest.TestCase):
    """`_rows_from_recommendations` converts Gemini's recs into JSONL rows."""

    SESSION = {"app_name": "app", "user_id": "eval_user", "state": {}}

    def test_empty_recommendations_returns_empty(self):
        assert _rows_from_recommendations(None, self.SESSION) == []
        assert _rows_from_recommendations({}, self.SESSION) == []

    def test_scenario_becomes_prompt_row(self):
        recs = {
            "scenarios": [
                {"starting_prompt": "Plan a trip", "conversation_plan": "Then refine"},
            ],
        }
        rows = _rows_from_recommendations(recs, self.SESSION)
        assert len(rows) == 1
        assert rows[0]["prompt"] == "Plan a trip"
        assert rows[0]["conversation_plan"] == "Then refine"
        assert rows[0]["session_inputs"] == self.SESSION

    def test_golden_data_with_reference_behavior_maps_to_reference(self):
        recs = {
            "golden_data": [
                {
                    "user_inputs": ["What's the weather in SF?"],
                    "reference_data": {"expected_behavior": "60 and foggy"},
                },
            ],
        }
        rows = _rows_from_recommendations(recs, self.SESSION)
        assert len(rows) == 1
        assert rows[0]["prompt"] == "What's the weather in SF?"
        assert rows[0]["reference"] == "60 and foggy"
        assert rows[0]["session_inputs"] == self.SESSION
        assert rows[0]["id"] == "ai_generated_001"

    def test_golden_data_multi_turn_history(self):
        recs = {
            "golden_data": [
                {"user_inputs": ["First", "Second", "Third"]},
            ],
        }
        rows = _rows_from_recommendations(recs, self.SESSION)
        assert rows[0]["prompt"] == "Third"
        assert rows[0]["conversation_history"] == [
            {"role": "user", "parts": [{"text": "First"}]},
            {"role": "user", "parts": [{"text": "Second"}]},
        ]

    def test_extra_reference_fields_flatten_to_top_level(self):
        recs = {
            "golden_data": [
                {
                    "user_inputs": ["List docs"],
                    "reference_data": {
                        "expected_behavior": "Returns docs",
                        "expected_docs": ["a", "b"],
                    },
                },
            ],
        }
        rows = _rows_from_recommendations(recs, self.SESSION)
        assert rows[0]["reference"] == "Returns docs"
        assert rows[0]["expected_docs"] == ["a", "b"]


class TestScaffoldDatasetJsonl(unittest.TestCase):
    """End-to-end check that scaffold_dataset_jsonl writes the expected file."""

    def test_falls_back_to_boilerplate_without_recommendations(self):
        with tempfile.TemporaryDirectory() as td:
            scaffold_dataset_jsonl(Path(td), agent_name="my_agent")
            out = Path(td) / "tests" / "eval" / "dataset.jsonl"
            rows = [json.loads(l) for l in out.read_text().splitlines() if l]
            assert len(rows) == 2
            assert rows[0]["session_inputs"]["app_name"] == "my_agent"

    def test_uses_recommendations_when_present(self):
        recs = {
            "scenarios": [{"starting_prompt": "Trip", "conversation_plan": "Refine"}],
            "golden_data": [
                {
                    "user_inputs": ["Weather?"],
                    "reference_data": {"expected_behavior": "Foggy"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            scaffold_dataset_jsonl(Path(td), agent_name="app", recommendations=recs)
            out = Path(td) / "tests" / "eval" / "dataset.jsonl"
            rows = [json.loads(l) for l in out.read_text().splitlines() if l]
            assert len(rows) == 2
            assert rows[0]["prompt"] == "Trip"
            assert rows[1]["prompt"] == "Weather?"
            assert rows[1]["reference"] == "Foggy"

    def test_existing_file_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "tests" / "eval" / "dataset.jsonl"
            out.parent.mkdir(parents=True)
            out.write_text('{"prompt": "untouched"}\n')
            scaffold_dataset_jsonl(Path(td), agent_name="app")
            assert out.read_text() == '{"prompt": "untouched"}\n'


if __name__ == "__main__":
    unittest.main()
