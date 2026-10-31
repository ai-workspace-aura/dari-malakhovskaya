"""Собирает страницы для просмотра на Vercel из блоков GetCourse.

Правки вносим в site/<папка>/getcourse-block.html, потом запускаем:
    python3 site/build-vercel.py
Скрипт обернёт каждый блок в полноценную страницу и положит её в admin/public/<папка>/index.html.
После пуша в GitHub Vercel сам выложит их на https://dari-malakhovskaya.vercel.app/<папка>/
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = {
    "main": "Союз с собой — 5 сезон «Либидо жизни»",
    "predzapis": "Союз с собой — анкета предзаписи",
    "lead-magnet": "Союз с собой — разрешение на жизнь",
    "spasibo": "Союз с собой — спасибо",
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

for name, title in PAGES.items():
    block = (ROOT / "site" / name / "getcourse-block.html").read_text(encoding="utf-8")
    out = ROOT / "admin" / "public" / name / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(HEAD.format(title=title, name=name) + block + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"{name}: {out.relative_to(ROOT)}")
