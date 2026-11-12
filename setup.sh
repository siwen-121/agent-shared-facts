#!/bin/sh
set -eu
if [ "${1:-}" = "--install-python" ]; then
    if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
        exec brew install python@3.12
    fi
    printf '%s\n' 'Install Python 3.12+ from https://www.python.org/downloads/' >&2
    exit 1
fi
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if command -v python3.12 >/dev/null 2>&1; then
    exec python3.12 "$script_dir/setup-devices.py" "$@"
fi
exec python3 "$script_dir/setup-devices.py" "$@"
