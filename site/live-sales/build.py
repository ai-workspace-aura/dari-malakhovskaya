"""Собирает site/live-sales/getcourse-block.html — копию основного сайта (site/main) для эфира 28 ноября.
Отличия: в тарифах вместо оплаты одна кнопка «Забронировать место за 2 000 ₽», цены видны; кнопки «Выбрать тариф» → «Забронировать место».
Запуск из корня проекта: python3 site/live-sales/build.py
Правки общих блоков вносить в site/main, потом перезапускать этот скрипт.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
s = (ROOT / "main/getcourse-block.html").read_text(encoding="utf-8")

def rep(a, b, n=1):
    global s
    c = s.count(a)
    assert c == n, (c, a[:90])
    s = s.replace(a, b)

# Шапка-комментарий
s = re.sub(r'^<!--.*?-->\n<!--.*?-->\n', '''<!-- Союз с собой — страница для эфира 28 ноября (разборы и продажи 5 сезона). Копия основного сайта (site/main), собирается скриптом site/live-sales/build.py. Вставлять в HTML-блок GetCourse целиком.
     АДРЕС СТРАНИЦЫ: school.dari-malakhovskaya.ru/live-sales -->
<!-- БРОНЬ: у кнопок «Забронировать место за 2 000 ₽» в тарифах «Поток» и VIP в href стоит # — технарь ставит ссылки на предложения GetCourse (бронь 2 000 ₽ для каждого тарифа).
     ВИДЕО и ОТЗЫВЫ: как на основном сайте. ФОТО Алены: в блоке экспертов вместо заглушки «А». -->
''', s, count=1, flags=re.S)

# Тарифы: подзаголовок про бронь
rep('''        <h2 class="h2 rv">Выбери формат участия</h2>
      </div>''', '''        <h2 class="h2 rv">Выбери формат участия</h2>
        <p class="muted rv">Сегодня место можно забронировать за 2 000 ₽. Стоимость участия указана в каждом тарифе.</p>
      </div>''')

# Тарифы: одна кнопка брони вместо трёх
def cta(m):
    plan = "«Поток»" if "«Поток»" in m.group(1) else "VIP"
    arrow = re.search(r'<svg class="arr".*?</svg>', m.group(0), flags=re.S).group(0)
    return f'''<div class="plan-cta">
            <!-- БРОНЬ: ссылка на предложение GetCourse — бронь 2 000 ₽, тариф {plan} -->
            <a class="btn" href="#">Забронировать место за 2 000 ₽
              {arrow}
            </a>
          </div>'''
s, n = re.subn(r'<div class="plan-cta">\s*<!-- ОПЛАТА: (три ссылки[^>]*?)-->.*?</div>', cta, s, flags=re.S)
assert n == 2, n

rep('Нажимая кнопку оплаты или брони, ты принимаешь', 'Нажимая кнопку брони, ты принимаешь')

# Кнопки-переходы к тарифам
s, n = re.subn(r'(<a class="btn" href="#tariffs">)Выбрать тариф', r'\1Забронировать место', s)
assert n >= 1, n
rep('aria-hidden="true" tabindex="-1">Выбрать тариф</a>', 'aria-hidden="true" tabindex="-1">Забронировать место</a>')

(ROOT / "live-sales/getcourse-block.html").write_text(s, encoding="utf-8")
print("ok", len(s))
