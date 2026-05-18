#!/bin/bash
cd /Users/romanhoyos94/Documents/Desarrollos-claude/Detector-anomailias-claude
python3 -m streamlit run app.py --server.port "${PORT:-8501}" --server.headless true
