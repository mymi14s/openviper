#!/bin/bash

# OpenViper Quality Check Script
# Runs ruff, mypy, black, and flake8 to ensure code quality.

echo "--- Running Ruff ---"
ruff check openviper
RUFF_EXIT=$?

echo -e "\n--- Running Mypy ---"
mypy -p openviper
MYPY_EXIT=$?

echo -e "\n--- Running Black (check) ---"
black --check openviper
BLACK_EXIT=$?

echo -e "\n--- Running Flake8 ---"
flake8 openviper
FLAKE8_EXIT=$?

echo -e "\n--- Summary ---"
[ $RUFF_EXIT -eq 0 ] && echo "✓ Ruff: Passed" || echo "✗ Ruff: Failed"
[ $MYPY_EXIT -eq 0 ] && echo "✓ Mypy: Passed" || echo "✗ Mypy: Failed"
[ $BLACK_EXIT -eq 0 ] && echo "✓ Black: Passed" || echo "✗ Black: Failed"
[ $FLAKE8_EXIT -eq 0 ] && echo "✓ Flake8: Passed" || echo "✗ Flake8: Failed"

# Exit with error if any tool failed
if [ $RUFF_EXIT -ne 0 ] || [ $MYPY_EXIT -ne 0 ] || [ $BLACK_EXIT -ne 0 ] || [ $FLAKE8_EXIT -ne 0 ]; then
    exit 1
fi
