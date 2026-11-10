#!/usr/bin/env bash
# Runs the PCB Inspector test suite (Linux / macOS). Extra args go to pytest.
cd "$(dirname "$0")"
PYTEST_ARGS="${*:--q}" exec ./run.sh --test
