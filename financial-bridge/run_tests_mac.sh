#!/bin/bash
# run_tests.sh — copia nella cartella financial-agent/ e lancia con: bash run_tests.sh

set -e
cd "$(dirname "$0")"

echo "=== Setup ==="
pip install flask flask-cors cachetools --quiet

echo "=== Avvio tool_server.py ==="
python tool_server.py &
SERVER_PID=$!
sleep 2

echo "=== Run test suite ==="
python "$(dirname "$0")/../claw-code/financial-bridge/test_env/stress_test.py"

echo "=== Stop server ==="
kill $SERVER_PID 2>/dev/null
