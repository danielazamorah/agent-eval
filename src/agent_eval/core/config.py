from typing import Optional
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Automatically load environment variables from .env file
load_dotenv(override=True)


class EvalConfig(BaseSettings):
    """
    Centralized configuration for the evaluation pipeline using Pydantic.
    Reads from environment variables and provides type safety.
    """

    model_config = SettingsConfigDict(
        env_prefix="EVAL_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Managed Metric Names
    METRIC_TOOL_USE_QUALITY: str = "TOOL_USE_QUALITY"
    METRIC_GENERAL_QUALITY: str = "GENERAL_QUALITY"

    # Standard Dataset Column Names
    COL_PROMPT: str = "prompt"
    COL_RESPONSE: str = "response"
    COL_INTERMEDIATE_EVENTS: str = "intermediate_events"
    COL_TOOL_USAGE: str = "tool_usage"

    # Execution Settings
    GOOGLE_CLOUD_PROJECT: Optional[str] = Field(
        default=None, description="GCP Project ID"
    )
    GOOGLE_CLOUD_LOCATION: str = Field(default="us-central1", description="GCP Region")
    MAX_RETRIES: int = Field(default=3, description="Max retries for LLM calls")
    RETRY_DELAY_SECONDS: int = Field(default=5, description="Base delay for retries")
    MAX_WORKERS: int = Field(default=4, description="Threads for parallel evaluation")

    # Data Mappings
    EXTRACTED_DATA_PREFIX: str = "extracted_data"
    REFERENCE_DATA_PREFIX: str = "reference_data"


# Initialize Shared Config
CONFIG = EvalConfig()
