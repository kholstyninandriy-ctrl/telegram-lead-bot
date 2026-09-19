#!/usr/bin/env bash
# Запуск бота: ставить залежності і стартує. Працює всюди — Replit, Railway, VPS.
set -e
python -m pip install --quiet --disable-pip-version-check --upgrade pip
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
exec python main.py
