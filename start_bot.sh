#!/bin/sh
set -eu

cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"
LOCK_FILE="${LOCK_FILE:-.bot.lock}"

if [ ! -x "$PYTHON" ]; then
    echo "Python из виртуального окружения не найден: $PYTHON" >&2
    echo "Создайте окружение: python3 -m venv .venv" >&2
    exit 1
fi

mkdir -p data
if command -v flock >/dev/null 2>&1; then
    exec flock -n "$LOCK_FILE" "$PYTHON" main.py
fi
exec "$PYTHON" main.py
