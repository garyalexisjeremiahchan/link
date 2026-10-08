#!/usr/bin/env bash
# Wrapper pointing to root deploy.sh
exec "$(dirname "$0")/../deploy.sh" "$@"
