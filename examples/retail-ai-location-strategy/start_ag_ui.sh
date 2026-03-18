#!/bin/bash
trap 'kill 0' INT

echo "Starting AG-UI servers..."
echo "Backend will run at http://localhost:8000"
echo "Frontend will run at http://localhost:3000"

# Run backend
(cd app/frontend/backend && uv run python main.py) &

# Run frontend
(cd app/frontend && npm run dev) &

wait
