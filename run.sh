#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d venv ]; then
  echo "Setting up (first time only)..."
  python3 -m venv venv
  venv/bin/pip install -q -r requirements.txt
fi
venv/bin/python unfollow.py "$@"
