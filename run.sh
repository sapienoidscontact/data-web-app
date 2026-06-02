#!/bin/bash
echo "========================================="
echo "  Sapienoids Analytics Portal - Starting"
echo "========================================="
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not found. Please install Python from https://python.org"
    exit 1
fi

# Install requirements
echo "Checking dependencies..."
pip3 install -r requirements.txt --quiet

echo "Launching app..."
streamlit run D1.py --server.runOnSave=true
