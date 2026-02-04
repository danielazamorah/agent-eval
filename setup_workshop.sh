#!/bin/bash
# Workshop Environment Verification Script
# Run this to verify your environment is ready for the workshop

echo "=============================================="
echo "  Workshop Environment Verification"
echo "=============================================="
echo ""

ERRORS=0

# Check Python version
echo "Checking Python..."
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
if [[ "$PYTHON_VERSION" =~ ^3\.(10|11|12)$ ]]; then
    echo "  [OK] Python $PYTHON_VERSION"
else
    echo "  [ERROR] Python 3.10-3.12 required (found: $PYTHON_VERSION)"
    ERRORS=$((ERRORS + 1))
fi

# Check uv
echo "Checking uv..."
if command -v uv &> /dev/null; then
    echo "  [OK] uv $(uv --version 2>&1 | head -1)"
else
    echo "  [ERROR] uv not installed"
    echo "          Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    ERRORS=$((ERRORS + 1))
fi

# Check gcloud auth
echo "Checking Google Cloud authentication..."
if gcloud auth list 2>/dev/null | grep -q ACTIVE; then
    ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null)
    echo "  [OK] Authenticated as $ACCOUNT"
else
    echo "  [ERROR] Not authenticated with gcloud"
    echo "          Run: gcloud auth login && gcloud auth application-default login"
    ERRORS=$((ERRORS + 1))
fi

# Check GOOGLE_CLOUD_PROJECT
echo "Checking GOOGLE_CLOUD_PROJECT..."
if [ -n "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "  [OK] GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT"
else
    echo "  [WARNING] GOOGLE_CLOUD_PROJECT not set"
    echo "            Run: export GOOGLE_CLOUD_PROJECT=your-project-id"
    ERRORS=$((ERRORS + 1))
fi

# CRITICAL: Check for API Key (should NOT be set)
echo "Checking for API Key (should NOT be set)..."
if [ -n "$GOOGLE_API_KEY" ]; then
    echo "  [ERROR] GOOGLE_API_KEY is set - this will NOT work with evaluation!"
    echo "          The evaluation pipeline requires Vertex AI traces."
    echo "          Run: unset GOOGLE_API_KEY"
    ERRORS=$((ERRORS + 1))
else
    echo "  [OK] GOOGLE_API_KEY not set (correct)"
fi

# Check Vertex AI API
echo "Checking Vertex AI API..."
if [ -n "$GOOGLE_CLOUD_PROJECT" ]; then
    # Try to check enabled services (may fail if auth tokens need refresh)
    SERVICES_OUTPUT=$(gcloud services list --enabled 2>&1)
    if echo "$SERVICES_OUTPUT" | grep -q "aiplatform.googleapis.com"; then
        echo "  [OK] Vertex AI API enabled"
    elif echo "$SERVICES_OUTPUT" | grep -qi "error\|reauthentication"; then
        echo "  [WARNING] Could not verify Vertex AI API (auth token may need refresh)"
        echo "            If you encounter errors, run: gcloud services enable aiplatform.googleapis.com"
    else
        echo "  [WARNING] Vertex AI API may not be enabled"
        echo "            Run: gcloud services enable aiplatform.googleapis.com"
    fi
else
    echo "  [SKIP] Cannot check - GOOGLE_CLOUD_PROJECT not set"
fi

echo ""
echo "=============================================="
if [ $ERRORS -eq 0 ]; then
    echo "  Environment check PASSED"
    echo "=============================================="
    echo ""
    echo "Next steps:"
    echo "  1. cd customer-service && cp .env.example .env"
    echo "  2. Edit .env with your GOOGLE_CLOUD_PROJECT"
    echo "  3. cd ../evaluation && uv sync"
    echo "  4. See HOW_TO_USE_REPO.md for evaluation commands"
    echo ""
    echo "Note: You don't need to run 'make playground' for evaluation."
    echo "      The 'adk eval' command runs against source code directly."
else
    echo "  Environment check FAILED ($ERRORS errors)"
    echo "=============================================="
    echo ""
    echo "Please fix the errors above before continuing."
fi
