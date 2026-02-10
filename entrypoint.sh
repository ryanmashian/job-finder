#!/usr/bin/env bash
set -e
# Optional: install Playwright deps if not already in image
python -m playwright install-deps chromium 2>/dev/null || true
exec python main.py
