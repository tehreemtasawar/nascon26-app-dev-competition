#!/usr/bin/env bash
# Runs all unit tests. Teammates: adjust paths and options as the project grows.
set -e
cd "$(dirname "$0")"
python -m pytest tests -v
