# Agent Optimization & Evaluation Workshop Dashboard

This interactive dashboard allows users to visualize and compare metrics from multiple JSON log files. It is designed for use in the Accelerate '26 workshop to analyze agent execution trajectories and performance.

## Features

- **Dynamic Metric Discovery:** Automatically flattens nested JSON structures to find all numeric metrics.
- **Interactive Visualization:** Uses Plotly for zoomable, hover-capable charts.
- **Multi-Directory Support:** Load logs from one or multiple paths simultaneously.
- **Native File Browser:** Explore your system to find log files directly within the UI.
- **Reactive Scorecards:** Instantly view Cost, Latency, and Quality deltas as soon as logs are selected.
- **Production Ready:** Managed with `uv` for reproducible builds, including linting and type-checking configurations.

## Setup & Running

### Option 1: Using `uv` (Recommended)
`uv` is a fast, reproducible dependency manager.

1. **Launch the application**:
   ```bash
   uv run dashboard.py
   ```

### Option 2: Using standard Python
If you cannot use `uv`, you can use standard `pip` and `python`.

1. **Install Dependencies**:
   ```bash
   pip install gradio pandas plotly
   ```
2. **Launch the application**:
   ```bash
   python dashboard.py
   ```

Open the URL provided in the console (typically `http://127.0.0.1:7860`).

## Usage

1. **Locate Logs**: Use the **File Browser** accordion to navigate your system. Selecting `.json` files will automatically populate their parent directories. Alternatively, you can **manually copy and paste** directory paths directly into the **Directory Path(s)** box.
2. **Load Data**: Click **Load / Update Data** to parse all JSON files in the specified directories.
3. **Compare Experiments**:
    - Select a **Baseline** experiment.
    - Choose one or more **Candidate(s)**.
    - **Note**: The **Scorecard Metrics** at the top will update **instantly** to show deltas between the baseline and the latest candidate.
4. **Customize Scorecards**: Use the **Metric** dropdowns inside the Cost, Latency, and Quality boxes to toggle which specific data point (e.g., Total Latency vs. Time to First Token) is featured.
5. **Generate Deep Dive**: 
    - Use **Pin Metrics (Charts)** to select values for the bar chart.
    - Toggle **Normalize Data** to scale values to a 0-1 range.
    - Click **Generate Charts & Data Table** to view detailed visualizations and the full raw data grid.

## Development

The project includes pre-configured tools for code quality (requires `uv`):

- **Linting & Formatting**: `uv run ruff check .`
- **Type Checking**: `uv run mypy .`