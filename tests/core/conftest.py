"""Shared test fixtures — mock Google Cloud / Vertex AI libraries.

These mocks must be installed before any agent_eval module is imported,
because vertexai triggers google.genai imports at module load time.
"""

import sys
from unittest.mock import MagicMock

# Mock the full chain that causes ImportError:
#   vertexai → vertexai._genai → google.genai._api_client
_vertexai_mock = MagicMock()
_google_cloud_mock = MagicMock()

for mod in [
    "google.genai",
    "google.genai.types",
    "google.genai._api_client",
    "google.cloud.aiplatform",
    "vertexai",
    "vertexai.types",
    "vertexai.preview",
    "vertexai.preview.evaluation",
]:
    sys.modules.setdefault(mod, MagicMock())
