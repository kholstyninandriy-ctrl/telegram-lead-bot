#!/usr/bin/env bash
# Оновлює код бота до останньої версії з GitHub.
#
#   bash update.sh            — оновити з гілки main
#   bash update.sh НАЗВА_ГІЛКИ — оновити з конкретної гілки
#
# Твої файли notes.db і .env НЕ зачіпаються: їх немає в репозиторії.
set -e

REPO="kholstyninandriy-ctrl/telegram-lead-bot"
BRANCH="${1:-main}"
URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"

echo "⬇️  Завантажую гілку ${BRANCH}…"
curl -fsSL "$URL" -o /tmp/leadbot.tar.gz

echo "📦 Розпаковую…"
tar xzf /tmp/leadbot.tar.gz --strip-components=1
rm -f /tmp/leadbot.tar.gz

echo "📚 Ставлю залежності…"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo
echo "✅ Готово. Тепер перезапусти бота:  python main.py"
echo "   Перевірка: напиши боту /diag — має відповісти «версія 2.2»."
