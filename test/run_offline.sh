#!/bin/sh
# The whole offline suite: the contract tests against build/ (the deployed
# bytes), then the keeper and the client-side checks (node).
cd "$(dirname "$0")" && python3 ../tools/build.py --check && python3 -m unittest discover -p 'test_*.py' "$@" && node --test ./*.test.mjs
