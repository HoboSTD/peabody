#!/usr/bin/env bash
# Set up the extractor in this folder (README: Quick start; Running it on your own machine). Safe to run again.
#
#   ./setup.sh           create .venv, install requirements, create the working folders
#   ./setup.sh --cron    also add the hourly fetch to the user's crontab (only if it isn't there)
#
# Set PYTHON to use a specific interpreter, e.g. PYTHON=python3.12 ./setup.sh
set -euo pipefail

usage() { echo "Usage: $0 [--cron]" >&2; exit 2; }

WANT_CRON=0
for arg in "$@"; do
    case "$arg" in
        --cron) WANT_CRON=1 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $arg" >&2; usage ;;
    esac
done

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

# 1. Python version
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Error: $PYTHON not found. Install Python 3.10 or later, or set PYTHON=/path/to/python3." >&2
    exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "Error: Python 3.10 or later is required; $PYTHON is $("$PYTHON" -V 2>&1)." >&2
    exit 1
fi

# 2. Virtual environment and requirements
if [ ! -x .venv/bin/python ]; then
    echo "Creating .venv with $("$PYTHON" -V 2>&1)"
    if ! "$PYTHON" -m venv .venv; then
        echo "Error: could not create .venv. On Debian/Ubuntu, install the python3-venv package." >&2
        exit 1
    fi
fi
echo "Installing requirements"
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

# 3. Working folders (git-ignored)
mkdir -p data backups output state logs

# 4. Hourly cron entry
if [ "$WANT_CRON" -eq 1 ]; then
    if ! command -v crontab >/dev/null 2>&1; then
        echo "Error: crontab not found. Install cron, or run '.venv/bin/python -m extractor fetch' by hand." >&2
        exit 1
    fi
    CRON_LINE="0 * * * * cd '$REPO' && .venv/bin/python -m extractor fetch >> logs/fetch.log 2>&1"

    # 'crontab -l' fails when the user has no crontab yet; any other failure must stop us,
    # or writing back below would replace the user's existing entries.
    if CURRENT="$(crontab -l 2>&1)"; then
        :
    elif printf '%s' "$CURRENT" | grep -qi 'no crontab'; then
        CURRENT=""
    else
        echo "Error: could not read the current crontab: $CURRENT" >&2
        exit 1
    fi

    if printf '%s\n' "$CURRENT" | grep -qxF "$CRON_LINE"; then
        echo "Cron entry already present"
    else
        { [ -n "$CURRENT" ] && printf '%s\n' "$CURRENT"; printf '%s\n' "$CRON_LINE"; } | crontab -
        echo "Added cron entry: $CRON_LINE"
    fi
fi

echo "Setup complete."
echo "First run: .venv/bin/python -m extractor backfill --from 2023-01-01"
