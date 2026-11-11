"""Собирает страницы для просмотра на Vercel из блоков GetCourse.

Правки вносим в site/<папка>/getcourse-block.html, потом запускаем:
    python3 site/build-vercel.py             — все страницы
    python3 site/build-vercel.py main pre-reg — только перечисленные
Скрипт обернёт каждый блок в полноценную страницу и положит её в admin/public/<папка>/index.html.
После пуша в GitHub Vercel сам выложит их на https://dari-malakhovskaya.vercel.app/<папка>/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = {
    "main": "Союз с собой — 5 сезон «Либидо жизни»",
    "pre-reg": "Союз с собой — анкета предзаписи",
    "pre-reg-lm": "Союз с собой — разрешение на жизнь",
    "thank-you": "Союз с собой — спасибо",
    "training-reg": "Союз с собой — регистрация на интенсив",
    "training-sales": "Союз с собой — тарифы",
}

HEAD = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
</head>
<body>
<!-- Собрано из site/{name}/getcourse-block.html скриптом site/build-vercel.py. Правки вносить там. -->
"""

selected = sys.argv[1:] or list(PAGES)
unknown = [n for n in selected if n not in PAGES]
if unknown:
    sys.exit(f"Нет таких страниц: {', '.join(unknown)}. Есть: {', '.join(PAGES)}")

for name in selected:
    title = PAGES[name]
    block = (ROOT / "site" / name / "getcourse-block.html").read_text(encoding="utf-8")
    out = ROOT / "admin" / "public" / name / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(HEAD.format(title=title, name=name) + block + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"{name}: {out.relative_to(ROOT)}")
