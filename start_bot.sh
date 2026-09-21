#!/bin/sh
set -eu

cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
    echo "Python из виртуального окружения не найден: $PYTHON" >&2
    echo "Создайте окружение: python3 -m venv .venv" >&2
    exit 1
fi

exec "$PYTHON" main.py
