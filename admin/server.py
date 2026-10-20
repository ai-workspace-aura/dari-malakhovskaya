#!/usr/bin/env python3
"""Админка запуска «Союз с собой»: контент-план, статистика, финансы.

Без внешних зависимостей: Python 3.9+ и SQLite. Запуск и команды — в README.md.
"""
import csv
import datetime as dt
import getpass
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "public"
DB_PATH = Path(os.environ.get("ADMIN_DB", ROOT / "data" / "admin.db"))
# На Vercel база — Postgres (Neon): адрес приходит в DATABASE_URL. Без него работаем на локальном SQLite.
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
ON_VERCEL = bool(os.environ.get("VERCEL"))
CONFIG_PATH = Path(os.environ.get("ADMIN_CONFIG", ROOT / "config.json"))
PLAN_SEED = ROOT / "data" / "content-plan-v3.json"
SESSION_DAYS = 30
MSK = dt.timezone(dt.timedelta(hours=3))

CHANNELS = ["tg_open", "tg_closed", "stories", "reels", "email"]
ITEM_STATUSES = ["planned", "in_work", "ready", "published"]
DEFAULT_SETTINGS = {
    "revenue_plan": 22000000,
    "period_from": "2026-10-17",
    "period_to": "2026-11-24",
    "tariffs": ["Поток", "VIP"],
    "methods": ["Карта", "Рассрочка", "Кредит", "Другое"],
    "managers": [],
    "statuses": ["Оплачен", "Частично", "Ожидает", "Отменён", "Возврат"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id {pk}, email TEXT UNIQUE NOT NULL, name TEXT, pw_hash TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS plan_days(
  date TEXT PRIMARY KEY, title TEXT, stage INTEGER, audience TEXT, scene TEXT, belief TEXT,
  bridge TEXT, case_note TEXT, needed TEXT);
CREATE TABLE IF NOT EXISTS content_items(
  id {pk}, date TEXT NOT NULL, channel TEXT NOT NULL, title TEXT, format TEXT,
  script TEXT, cta TEXT, status TEXT DEFAULT 'planned', link TEXT, notes TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS content_items_date ON content_items(date);
CREATE TABLE IF NOT EXISTS metrics(
  date TEXT NOT NULL, channel TEXT NOT NULL, posts INTEGER, reach INTEGER, clicks INTEGER,
  PRIMARY KEY(date, channel));
CREATE TABLE IF NOT EXISTS media(
  id TEXT PRIMARY KEY, source TEXT, channel TEXT, date TEXT, reach INTEGER, permalink TEXT, fetched_at TEXT);
CREATE INDEX IF NOT EXISTS media_date ON media(date, channel);
CREATE TABLE IF NOT EXISTS links(
  id {pk}, slug TEXT UNIQUE NOT NULL, target TEXT NOT NULL, channel TEXT, date TEXT,
  note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS clicks(
  id {pk}, link_id INTEGER NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS clicks_link ON clicks(link_id);
CREATE TABLE IF NOT EXISTS payments(
  id {pk}, gc_id TEXT UNIQUE, date TEXT, client TEXT, email TEXT, tariff TEXT,
  method TEXT, manager TEXT, status TEXT, amount {real}, paid {real}, note TEXT, source TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sync_log(
  id {pk}, source TEXT, ts TEXT, ok INTEGER, message TEXT);
"""


# ---------- база ----------

class Result:
    def __init__(self, rows_):
        self._rows = rows_

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class Conn:
    """Одна обёртка над SQLite и Postgres: запросы пишем с «?», строки получаем словарями."""

    def __init__(self):
        if DATABASE_URL:
            import ssl
            import pg8000.dbapi
            u = urllib.parse.urlparse(DATABASE_URL)
            local = u.hostname in ("localhost", "127.0.0.1")
            self.raw = pg8000.dbapi.connect(
                user=urllib.parse.unquote(u.username or ""), password=urllib.parse.unquote(u.password or ""),
                host=u.hostname, port=u.port or 5432, database=u.path.lstrip("/"),
                ssl_context=None if local else ssl.create_default_context(), timeout=20)
        else:
            self.raw = sqlite3.connect(DB_PATH, timeout=10)
            self.raw.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql, params=()):
        if DATABASE_URL:
            sql = sql.replace("?", "%s")
        cur = self.raw.cursor()
        cur.execute(sql, tuple(params))
        if cur.description is None:
            return Result([])
        names = [d[0] for d in cur.description]
        return Result([dict(zip(names, r)) for r in cur.fetchall()])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        try:
            self.raw.commit() if exc_type is None else self.raw.rollback()
        finally:
            self.raw.close()


def db():
    return Conn()


def integrity_errors():
    errs = [sqlite3.IntegrityError]
    if DATABASE_URL:
        import pg8000.dbapi
        errs.append(pg8000.dbapi.IntegrityError)
    return tuple(errs)


_inited = False


def init_db():
    global _inited
    if _inited:
        return
    if not DATABASE_URL:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA.format(pk="SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY",
                           real="DOUBLE PRECISION" if DATABASE_URL else "REAL")
    with db() as c:
        if DATABASE_URL:
            c.execute("SELECT pg_advisory_xact_lock(4242)")  # две функции не засеют план одновременно
        else:
            c.execute("PRAGMA journal_mode=WAL")
        for stmt in schema.split(";"):
            if stmt.strip():
                c.execute(stmt)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
                      (k, json.dumps(v, ensure_ascii=False)))
        if not c.execute("SELECT 1 FROM plan_days LIMIT 1").fetchone() and PLAN_SEED.exists():
            seed_plan(c)
        boot_email = os.environ.get("ADMIN_BOOTSTRAP_EMAIL")
        boot_pw = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
        if boot_email and boot_pw and not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            c.execute("INSERT INTO users(email,name,pw_hash,created_at) VALUES(?,?,?,?)",
                      (boot_email.strip().lower(), "", hash_password(boot_pw), now_iso()))
    _inited = True


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def now_iso():
    return dt.datetime.now(MSK).replace(microsecond=0).isoformat()


def load_config():
    # на Vercel весь конфиг лежит JSON-строкой в переменной окружения ADMIN_CONFIG_JSON
    if os.environ.get("ADMIN_CONFIG_JSON"):
        return json.loads(os.environ["ADMIN_CONFIG_JSON"])
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def get_settings(c):
    return {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT key,value FROM settings")}


def log_sync(source, ok, message):
    with db() as c:
        c.execute("INSERT INTO sync_log(source,ts,ok,message) VALUES(?,?,?,?)",
                  (source, now_iso(), 1 if ok else 0, str(message)[:2000]))


# ---------- контент-план: первичная загрузка ----------

def seed_plan(c):
    data = json.loads(PLAN_SEED.read_text(encoding="utf-8"))
    year = data.get("year", 2026)
    stage_of = {}
    for i, s in enumerate(data["stages"]):
        for idx in range(s["from"], s["to"]):
            stage_of[idx] = i
    c.execute("INSERT INTO settings(key,value) VALUES('stages',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps(data["stages"], ensure_ascii=False),))
    ts = now_iso()
    for idx, r in enumerate(data["rows"]):
        d, m = r["date"].split(".")
        date = f"{year}-{m}-{d}"
        c.execute("""INSERT INTO plan_days(date,title,stage,audience,scene,belief,bridge,case_note,needed)
                     VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET title=excluded.title,
                     stage=excluded.stage, audience=excluded.audience, scene=excluded.scene, belief=excluded.belief,
                     bridge=excluded.bridge, case_note=excluded.case_note, needed=excluded.needed""",
                  (date, r["title"], stage_of.get(idx, 0), r["audience"], r["scene"], r["belief"],
                   r["bridge"], r["case"], r["needed"]))
        pub = r["pub_format"]
        open_channels = []
        if "Telegram" in pub or "Telegram" in r["pub_script"]:
            open_channels.append("tg_open")
        if "Stories" in pub:
            open_channels.append("stories")
        if "Reels" in pub:
            open_channels.append("reels")
        if not open_channels:
            open_channels.append("tg_open")
        for ch in open_channels:
            c.execute("""INSERT INTO content_items(date,channel,title,format,script,cta,status,updated_at)
                         VALUES(?,?,?,?,?,?,'planned',?)""",
                      (date, ch, r["title"], pub, r["pub_script"], r["pub_cta"], ts))
        if "не открыт" not in r["priv_format"]:
            c.execute("""INSERT INTO content_items(date,channel,title,format,script,cta,status,updated_at)
                         VALUES(?,?,?,?,?,?,'planned',?)""",
                      (date, "tg_closed", r["title"], r["priv_format"], r["priv_script"], r["priv_cta"], ts))


# ---------- пароли и сессии ----------

def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${h}"


def check_password(pw, stored):
    try:
        _, salt, _h = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, salt), stored)


def add_user(email, password, name=""):
    init_db()
    with db() as c:
        c.execute("INSERT INTO users(email,name,pw_hash,created_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(email) DO UPDATE SET pw_hash=excluded.pw_hash, name=excluded.name",
                  (email.strip().lower(), name, hash_password(password), now_iso()))


# ---------- статистика ----------

def daterange(a, b):
    d = dt.date.fromisoformat(a)
    end = dt.date.fromisoformat(b)
    out = []
    while d <= end and len(out) < 400:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def metrics_report(c, date_from, date_to):
    manual = {(r["date"], r["channel"]): r for r in rows(c.execute(
        "SELECT * FROM metrics WHERE date BETWEEN ? AND ?", (date_from, date_to)))}
    media = {(r["date"], r["channel"]): r for r in rows(c.execute(
        "SELECT date, channel, COUNT(*) n, SUM(reach) reach FROM media WHERE date BETWEEN ? AND ? "
        "GROUP BY date, channel", (date_from, date_to)))}
    published = {(r["date"], r["channel"]): r["n"] for r in rows(c.execute(
        "SELECT date, channel, COUNT(*) n FROM content_items WHERE status='published' AND date BETWEEN ? AND ? "
        "GROUP BY date, channel", (date_from, date_to)))}
    # переход засчитывается дню публикации ссылки, а если дата у ссылки не указана — дню клика
    tracked = {(r["d"], r["channel"]): r["n"] for r in rows(c.execute(
        "SELECT COALESCE(l.date, substr(k.ts,1,10)) d, l.channel, COUNT(*) n FROM clicks k "
        "JOIN links l ON l.id=k.link_id GROUP BY d, l.channel"))}
    out = []
    for d in daterange(date_from, date_to):
        for ch in CHANNELS:
            key = (d, ch)
            m = media.get(key)
            auto = {
                "posts": m["n"] if m else published.get(key, 0),
                "reach": (m["reach"] or 0) if m else 0,
                "clicks": tracked.get(key, 0),
            }
            man = manual.get(key) or {}
            row = {"date": d, "channel": ch, "auto": auto,
                   "manual": {k: man.get(k) for k in ("posts", "reach", "clicks")}}
            for k in ("posts", "reach", "clicks"):
                row[k] = man.get(k) if man.get(k) is not None else auto[k]
            out.append(row)
    return out


# ---------- оплаты ----------

STATUS_MAP = [
    ("частич", "Частично"), ("возврат", "Возврат"), ("отмен", "Отменён"), ("ложн", "Отменён"),
    ("заверш", "Оплачен"), ("оплачен", "Оплачен"), ("paid", "Оплачен"), ("payed", "Оплачен"),
]


def norm_status(s):
    s = (s or "").strip()
    low = s.lower()
    for needle, val in STATUS_MAP:
        if needle in low:
            return val
    return "Ожидает" if s else ""


def norm_tariff(s, tariffs):
    s = (s or "").strip()
    low = s.lower()
    for t in tariffs:
        if t.lower() in low:
            return t
    return s


def norm_method(s, methods):
    s = (s or "").strip()
    low = s.lower()
    if not s:
        return ""
    if "рассроч" in low or "долями" in low or "сплит" in low:
        return "Рассрочка"
    if "кредит" in low:
        return "Кредит"
    if "карт" in low or "card" in low or "сбп" in low:
        return "Карта"
    return s if s in methods else s


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).replace("\xa0", "")).replace(",", ".")
    if s.count(".") > 1:
        s = s.replace(".", "", s.count(".") - 1)
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def norm_date(v):
    s = (v or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:19], fmt).date().isoformat()
        except ValueError:
            continue
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else ""


# Колонки выгрузки заказов GetCourse ищем по подстроке в заголовке: первое совпадение побеждает.
HEADER_RULES = {
    "gc_id": ["номер", "id заказа", "order_id", "id"],
    "date": ["дата оплаты", "дата создания", "создан", "дата"],
    "client": ["пользователь", "фио", "имя", "client"],
    "email": ["email", "e-mail", "почта"],
    "tariff": ["состав заказа", "предложени", "продукт", "тариф", "title"],
    "amount": ["стоимость", "сумма", "cost"],
    "paid": ["оплачено", "получено", "payed"],
    "status": ["статус", "status"],
    "manager": ["менеджер", "manager"],
    "method": ["способ оплаты", "платежная система", "платёжная система", "тип оплаты", "method"],
}


def map_headers(headers):
    low = [h.strip().lower() for h in headers]
    found = {}
    for key, needles in HEADER_RULES.items():
        for needle in needles:
            for i, h in enumerate(low):
                if i in found.values():
                    continue
                if (h == needle) if needle == "id" else (needle in h):
                    found[key] = i
                    break
            if key in found:
                break
    return found


def payment_from_raw(raw, settings, source):
    p = {
        "gc_id": (str(raw.get("gc_id") or "").strip() or None),
        "date": norm_date(raw.get("date")) or dt.date.today().isoformat(),
        "client": (raw.get("client") or "").strip(),
        "email": (raw.get("email") or "").strip(),
        "tariff": norm_tariff(raw.get("tariff"), settings.get("tariffs", [])),
        "method": norm_method(raw.get("method"), settings.get("methods", [])),
        "manager": (raw.get("manager") or "").strip(),
        "status": norm_status(raw.get("status")),
        "amount": num(raw.get("amount")),
        "paid": num(raw.get("paid")),
        "source": source,
    }
    if p["paid"] is None and p["status"] == "Оплачен":
        p["paid"] = p["amount"]
    return p


def upsert_payment(c, p):
    """Новые заказы добавляет, существующие (по номеру GetCourse) обновляет.
    Пустые значения из выгрузки не затирают то, что команда вписала руками."""
    p = dict(p, updated_at=now_iso())
    if p.get("gc_id"):
        cur = c.execute("SELECT * FROM payments WHERE gc_id=?", (p["gc_id"],)).fetchone()
        if cur:
            fields = {k: v for k, v in p.items() if v not in (None, "") and k != "gc_id"}
            sets = ",".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE payments SET {sets} WHERE id=?", (*fields.values(), cur["id"]))
            return "updated"
    cols = ",".join(p)
    c.execute(f"INSERT INTO payments({cols}) VALUES({','.join('?' * len(p))})", tuple(p.values()))
    return "created"


def import_table(c, headers, data_rows, source):
    settings = get_settings(c)
    idx = map_headers(headers)
    if "amount" not in idx and "paid" not in idx:
        raise ValueError("Не нашёл колонку со стоимостью или суммой оплаты. Заголовки: " + ", ".join(headers[:30]))
    stats = {"created": 0, "updated": 0, "skipped": 0}
    for r in data_rows:
        if not any(str(x).strip() for x in r):
            continue
        raw = {k: (r[i] if i < len(r) else "") for k, i in idx.items()}
        p = payment_from_raw(raw, settings, source)
        if p["amount"] is None and p["paid"] is None:
            stats["skipped"] += 1
            continue
        stats[upsert_payment(c, p)] += 1
    return stats


def import_csv_text(c, text):
    text = text.lstrip("﻿")
    sample = text[:5000]
    delim = max([";", ",", "\t"], key=sample.count)
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    if len(reader) < 2:
        raise ValueError("В файле нет строк с данными")
    return import_table(c, reader[0], reader[1:], "csv")


def finance_summary(c):
    s = get_settings(c)
    pays = rows(c.execute("SELECT * FROM payments"))
    counted = [p for p in pays if (p["paid"] or 0) > 0 and p["status"] not in ("Отменён", "Возврат")]
    revenue = sum(p["paid"] or 0 for p in counted)
    by = {}
    for key in ("tariff", "manager", "method"):
        agg = {}
        for p in counted:
            k = p[key] or "—"
            a = agg.setdefault(k, {"name": k, "count": 0, "sum": 0})
            a["count"] += 1
            a["sum"] += p["paid"] or 0
        by[key] = sorted(agg.values(), key=lambda x: -x["sum"])
    return {
        "plan": s.get("revenue_plan", 0),
        "revenue": revenue,
        "count": len(counted),
        "avg": revenue / len(counted) if counted else 0,
        "by": by,
    }


# ---------- интеграции ----------

def run_sync(source):
    import integrations  # noqa: E402 — модуль лежит рядом, импорт ленивый
    cfg = load_config()
    fn = {"getcourse": integrations.sync_getcourse, "instagram": integrations.sync_instagram,
          "telegram": integrations.sync_telegram}[source]
    try:
        msg = fn(cfg, db, upsert_payment=upsert_payment, import_table=import_table,
                 max_wait=40 if ON_VERCEL else 300)
        log_sync(source, True, msg)
        return True, msg
    except Exception as e:  # noqa: BLE001 — любую ошибку пишем в журнал синхронизаций
        log_sync(source, False, f"{type(e).__name__}: {e}")
        return False, str(e)


def sync_all():
    cfg = load_config()
    results = {}
    for source in ("getcourse", "instagram", "telegram"):
        if cfg.get(source, {}).get("enabled"):
            results[source] = run_sync(source)
    return results


def scheduler_loop(minutes):
    while True:
        time.sleep(minutes * 60)
        sync_all()


# ---------- HTTP ----------

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


ROUTES = []


def route(method, pattern, auth=True):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, auth))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version = "UnionAdmin/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # -- ответы
    def send_json(self, obj, status=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, path):
        types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
        f = (STATIC / path).resolve()
        if STATIC not in f.parents or not f.is_file():
            f = STATIC / "index.html"
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", types.get(f.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- запрос
    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            raise ApiError(413, "Слишком большой запрос")
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        if not raw:
            return {}
        if "application/json" in ctype:
            return json.loads(raw.decode())
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode(errors="replace")).items()}

    def current_user(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        tok = cookie.get("sid")
        if not tok:
            return None
        with db() as c:
            r = c.execute("SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id "
                          "WHERE s.token=? AND s.expires_at>?", (tok.value, int(time.time()))).fetchone()
        return dict(r) if r else None

    def dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        path = parsed.path
        try:
            if ON_VERCEL and not DATABASE_URL:
                raise ApiError(503, "База не подключена: в Vercel откройте Storage и подключите Neon (Postgres)")
            init_db()
            for m, rx, fn, auth in ROUTES:
                mt = rx.match(path)
                if mt and m == method:
                    self.user = self.current_user() if auth else None
                    if auth and not self.user:
                        raise ApiError(401, "Нужно войти")
                    if auth and method != "GET" and self.headers.get("X-Requested-With") != "admin":
                        raise ApiError(403, "Запрос без заголовка X-Requested-With")
                    result = fn(self, *mt.groups())
                    if result is not None:
                        self.send_json(result)
                    return
            if method == "GET" and not path.startswith("/api/"):
                return self.send_static(path.lstrip("/") or "index.html")
            raise ApiError(404, "Не найдено")
        except ApiError as e:
            self.send_json({"error": str(e)}, e.status)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self.send_json({"error": f"Неверные данные: {e}"}, 400)
        except Exception as e:  # noqa: BLE001
            self.log_message("ERROR %s", repr(e))
            self.send_json({"error": "Внутренняя ошибка сервера"}, 500)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")


def secure_cookie():
    return ON_VERCEL or load_config().get("base_url", "").startswith("https://")


# -- вход

@route("POST", "/api/login", auth=False)
def api_login(h, b=None):
    b = b or h.body_json()
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", ((b.get("email") or "").strip().lower(),)).fetchone()
        if not u or not check_password(b.get("password") or "", u["pw_hash"]):
            time.sleep(1)
            raise ApiError(401, "Неверная почта или пароль")
        tok = secrets.token_urlsafe(32)
        c.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, u["id"], int(time.time()) + SESSION_DAYS * 86400))
    flags = "; Secure" if secure_cookie() else ""
    h.send_json({"ok": True}, headers={
        "Set-Cookie": f"sid={tok}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}{flags}"})


@route("GET", "/api/setup", auth=False)
def api_setup_state(h):
    with db() as c:
        return {"needs_setup": not c.execute("SELECT 1 FROM users LIMIT 1").fetchone()}


@route("POST", "/api/setup", auth=False)
def api_setup(h):
    """Первую учётку можно создать прямо со страницы, пока в базе нет ни одного пользователя."""
    b = h.body_json()
    email = (b.get("email") or "").strip().lower()
    pw = b.get("password") or ""
    if "@" not in email or len(pw) < 8:
        raise ApiError(400, "Нужна почта и пароль не короче 8 символов")
    with db() as c:
        if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise ApiError(403, "Учётка уже создана, войдите")
        c.execute("INSERT INTO users(email,name,pw_hash,created_at) VALUES(?,?,?,?)",
                  (email, b.get("name") or "", hash_password(pw), now_iso()))
    return api_login(h, {"email": email, "password": pw})


@route("POST", "/api/logout")
def api_logout(h):
    tok = SimpleCookie(h.headers.get("Cookie", "")).get("sid")
    with db() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (tok.value if tok else "",))
    h.send_json({"ok": True}, headers={"Set-Cookie": "sid=; Path=/; Max-Age=0"})


@route("GET", "/api/me")
def api_me(h):
    with db() as c:
        return {"user": h.user, "settings": get_settings(c), "channels": CHANNELS, "item_statuses": ITEM_STATUSES}


# -- настройки

@route("PUT", "/api/settings")
def api_settings(h):
    b = h.body_json()
    allowed = set(DEFAULT_SETTINGS)
    with db() as c:
        for k, v in b.items():
            if k in allowed:
                c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k, json.dumps(v, ensure_ascii=False)))
        return get_settings(c)


# -- контент-план

ITEM_FIELDS = ["date", "channel", "title", "format", "script", "cta", "status", "link", "notes"]
DAY_FIELDS = ["title", "audience", "scene", "belief", "bridge", "case_note", "needed"]


@route("GET", "/api/plan")
def api_plan(h):
    a = h.query.get("from", "2000-01-01")
    b = h.query.get("to", "2100-01-01")
    with db() as c:
        return {
            "days": rows(c.execute("SELECT * FROM plan_days WHERE date BETWEEN ? AND ? ORDER BY date", (a, b))),
            "items": rows(c.execute("SELECT * FROM content_items WHERE date BETWEEN ? AND ? ORDER BY date, id", (a, b))),
        }


@route("PUT", r"/api/plan/days/(\d{4}-\d{2}-\d{2})")
def api_day_put(h, date):
    b = h.body_json()
    fields = {k: b[k] for k in DAY_FIELDS if k in b}
    with db() as c:
        c.execute("INSERT INTO plan_days(date) VALUES(?) ON CONFLICT(date) DO NOTHING", (date,))
        if fields:
            c.execute(f"UPDATE plan_days SET {','.join(k + '=?' for k in fields)} WHERE date=?", (*fields.values(), date))
        return dict(c.execute("SELECT * FROM plan_days WHERE date=?", (date,)).fetchone())


def check_item(b):
    if "channel" in b and b["channel"] not in CHANNELS:
        raise ApiError(400, "Неизвестный канал")
    if "status" in b and b["status"] not in ITEM_STATUSES:
        raise ApiError(400, "Неизвестный статус")
    if "date" in b:
        dt.date.fromisoformat(b["date"])


@route("POST", "/api/items")
def api_item_create(h):
    b = h.body_json()
    check_item(b)
    fields = {k: b.get(k) for k in ITEM_FIELDS}
    fields["status"] = fields["status"] or "planned"
    fields["updated_at"] = now_iso()
    with db() as c:
        return c.execute(f"INSERT INTO content_items({','.join(fields)}) VALUES({','.join('?' * len(fields))}) "
                         "RETURNING *", tuple(fields.values())).fetchone()


@route("PUT", r"/api/items/(\d+)")
def api_item_update(h, item_id):
    b = h.body_json()
    check_item(b)
    fields = {k: b[k] for k in ITEM_FIELDS if k in b}
    fields["updated_at"] = now_iso()
    with db() as c:
        c.execute(f"UPDATE content_items SET {','.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), item_id))
        r = c.execute("SELECT * FROM content_items WHERE id=?", (item_id,)).fetchone()
        if not r:
            raise ApiError(404, "Публикация не найдена")
        return dict(r)


@route("DELETE", r"/api/items/(\d+)")
def api_item_delete(h, item_id):
    with db() as c:
        c.execute("DELETE FROM content_items WHERE id=?", (item_id,))
    return {"ok": True}


# -- статистика

@route("GET", "/api/metrics")
def api_metrics(h):
    with db() as c:
        s = get_settings(c)
        a = h.query.get("from") or s["period_from"]
        b = h.query.get("to") or s["period_to"]
        dt.date.fromisoformat(a), dt.date.fromisoformat(b)
        return {"from": a, "to": b, "rows": metrics_report(c, a, b)}


@route("PUT", "/api/metrics")
def api_metrics_put(h):
    b = h.body_json()
    dt.date.fromisoformat(b["date"])
    if b["channel"] not in CHANNELS:
        raise ApiError(400, "Неизвестный канал")
    field = b["field"]
    if field not in ("posts", "reach", "clicks"):
        raise ApiError(400, "Неизвестное поле")
    val = b.get("value")
    val = None if val in (None, "") else int(float(val))
    with db() as c:
        c.execute("INSERT INTO metrics(date,channel) VALUES(?,?) ON CONFLICT(date,channel) DO NOTHING",
                  (b["date"], b["channel"]))
        c.execute(f"UPDATE metrics SET {field}=? WHERE date=? AND channel=?", (val, b["date"], b["channel"]))
    return {"ok": True}


# -- трекинг-ссылки

@route("GET", "/api/links")
def api_links(h):
    with db() as c:
        return {"links": rows(c.execute(
            "SELECT l.*, (SELECT COUNT(*) FROM clicks k WHERE k.link_id=l.id) clicks FROM links l ORDER BY l.id DESC")),
            "base_url": load_config().get("base_url", "")}


@route("POST", "/api/links")
def api_link_create(h):
    b = h.body_json()
    target = (b.get("target") or "").strip()
    if not re.match(r"^https?://", target):
        raise ApiError(400, "Ссылка должна начинаться с http:// или https://")
    if b.get("channel") not in CHANNELS:
        raise ApiError(400, "Выберите канал")
    if b.get("date"):
        dt.date.fromisoformat(b["date"])
    slug = (b.get("slug") or "").strip().lower() or secrets.token_urlsafe(4).lower().replace("_", "").replace("-", "")
    if not re.match(r"^[a-z0-9-]{2,40}$", slug):
        raise ApiError(400, "Короткое имя: латиница, цифры и дефис")
    with db() as c:
        try:
            c.execute("INSERT INTO links(slug,target,channel,date,note,created_at) VALUES(?,?,?,?,?,?)",
                      (slug, target, b["channel"], b.get("date") or None, b.get("note") or "", now_iso()))
        except integrity_errors():
            raise ApiError(409, "Такое короткое имя уже занято")
    return {"ok": True}


@route("DELETE", r"/api/links/(\d+)")
def api_link_delete(h, link_id):
    with db() as c:
        c.execute("DELETE FROM clicks WHERE link_id=?", (link_id,))
        c.execute("DELETE FROM links WHERE id=?", (link_id,))
    return {"ok": True}


BOT_UA = re.compile(r"bot|crawl|spider|preview|telegram|whatsapp|facebookexternalhit|vkshare|slack", re.I)


@route("GET", r"/go/([a-z0-9-]+)", auth=False)
def go(h, slug):
    with db() as c:
        link = c.execute("SELECT * FROM links WHERE slug=?", (slug,)).fetchone()
        if not link:
            raise ApiError(404, "Ссылка не найдена")
        # превью ссылок в мессенджерах — не переход человека
        if not BOT_UA.search(h.headers.get("User-Agent", "")):
            c.execute("INSERT INTO clicks(link_id,ts) VALUES(?,?)", (link["id"], now_iso()))
    h.send_response(302)
    h.send_header("Location", link["target"])
    h.send_header("Cache-Control", "no-store")
    h.end_headers()


# -- финансы

PAY_FIELDS = ["gc_id", "date", "client", "email", "tariff", "method", "manager", "status", "amount", "paid", "note"]


@route("GET", "/api/finance")
def api_finance(h):
    with db() as c:
        return {"summary": finance_summary(c),
                "payments": rows(c.execute("SELECT * FROM payments ORDER BY date DESC, id DESC"))}


def clean_payment(b):
    p = {k: b[k] for k in PAY_FIELDS if k in b}
    for k in ("amount", "paid"):
        if k in p:
            p[k] = num(p[k])
    if p.get("date"):
        dt.date.fromisoformat(p["date"])
    if "gc_id" in p:
        p["gc_id"] = (str(p["gc_id"]).strip() or None) if p["gc_id"] is not None else None
    return p


@route("POST", "/api/payments")
def api_payment_create(h):
    p = clean_payment(h.body_json())
    p.setdefault("date", dt.date.today().isoformat())
    p.setdefault("status", "Оплачен")
    p["source"] = "manual"
    p["updated_at"] = now_iso()
    with db() as c:
        try:
            c.execute(f"INSERT INTO payments({','.join(p)}) VALUES({','.join('?' * len(p))})", tuple(p.values()))
        except integrity_errors():
            raise ApiError(409, "Заказ с таким номером уже есть")
    return {"ok": True}


@route("PUT", r"/api/payments/(\d+)")
def api_payment_update(h, pid):
    p = clean_payment(h.body_json())
    p["updated_at"] = now_iso()
    with db() as c:
        try:
            c.execute(f"UPDATE payments SET {','.join(k + '=?' for k in p)} WHERE id=?", (*p.values(), pid))
        except integrity_errors():
            raise ApiError(409, "Заказ с таким номером уже есть")
    return {"ok": True}


@route("DELETE", r"/api/payments/(\d+)")
def api_payment_delete(h, pid):
    with db() as c:
        c.execute("DELETE FROM payments WHERE id=?", (pid,))
    return {"ok": True}


@route("POST", "/api/payments/import")
def api_payment_import(h):
    b = h.body_json()
    with db() as c:
        return import_csv_text(c, b.get("text") or "")


# -- интеграции

@route("GET", "/api/integrations")
def api_integrations(h):
    cfg = load_config()
    with db() as c:
        last = {}
        for r in rows(c.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 60")):
            last.setdefault(r["source"], r)
    return {
        "base_url": cfg.get("base_url", ""),
        "sources": {s: {"enabled": bool(cfg.get(s, {}).get("enabled")), "last": last.get(s)}
                    for s in ("getcourse", "instagram", "telegram")},
        "webhook": bool(cfg.get("getcourse", {}).get("webhook_token")),
    }


@route("POST", r"/api/sync/(getcourse|instagram|telegram)")
def api_sync(h, source):
    if ON_VERCEL:  # фоновых потоков на Vercel нет: функция живёт, пока отвечает
        ok, msg = run_sync(source)
        return {"ok": ok, "message": msg}
    threading.Thread(target=run_sync, args=(source,), daemon=True).start()
    return {"ok": True, "message": "Синхронизация запущена, результат появится в журнале через минуту-другую"}


@route("GET", "/api/cron", auth=False)
def api_cron(h):
    """Запускает все включённые интеграции. Вызывает Vercel Cron (заголовок Authorization)
    или внешний планировщик вроде cron-job.org (параметр ?key=)."""
    secret = os.environ.get("CRON_SECRET", "")
    given = (h.headers.get("Authorization") or "").replace("Bearer ", "", 1) or h.query.get("key", "")
    if not secret or not hmac.compare_digest(given, secret):
        raise ApiError(403, "Неверный ключ")
    return {k: {"ok": v[0], "message": v[1]} for k, v in sync_all().items()}


def hook_getcourse(h):
    token = load_config().get("getcourse", {}).get("webhook_token")
    params = dict(h.query)
    if h.command == "POST":
        params.update(h.body_json())
    if not token or not hmac.compare_digest(str(params.get("token", "")), token):
        raise ApiError(403, "Неверный токен")
    with db() as c:
        p = payment_from_raw({
            "gc_id": params.get("id") or params.get("number"),
            "date": params.get("date") or params.get("payed_at") or dt.date.today().isoformat(),
            "client": params.get("client") or params.get("name"),
            "email": params.get("email"),
            "tariff": params.get("tariff") or params.get("offer"),
            "amount": params.get("cost") or params.get("amount"),
            "paid": params.get("payed") or params.get("paid"),
            "status": params.get("status"),
            "manager": params.get("manager"),
            "method": params.get("method"),
        }, get_settings(c), "webhook")
        result = upsert_payment(c, p)
    return {"ok": True, "result": result}


route("GET", "/hooks/getcourse", auth=False)(hook_getcourse)
route("POST", "/hooks/getcourse", auth=False)(hook_getcourse)


# ---------- CLI ----------

def main(argv):
    cmd = argv[1] if len(argv) > 1 else "serve"
    init_db()
    if cmd == "serve":
        cfg = load_config()
        host = os.environ.get("HOST", cfg.get("host", "127.0.0.1"))
        port = int(os.environ.get("PORT", cfg.get("port", 8787)))
        every = cfg.get("sync_interval_minutes")
        if every:
            threading.Thread(target=scheduler_loop, args=(int(every),), daemon=True).start()
        print(f"Админка: http://{host}:{port}")
        ThreadingHTTPServer((host, port), Handler).serve_forever()
    elif cmd == "adduser":
        email = argv[2] if len(argv) > 2 else input("Почта: ")
        name = argv[3] if len(argv) > 3 else ""
        pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Пароль: ")
        if len(pw) < 8:
            sys.exit("Пароль должен быть не короче 8 символов")
        add_user(email, pw, name)
        print("Готово:", email)
    elif cmd == "sync":
        what = argv[2] if len(argv) > 2 else "all"
        print(sync_all() if what == "all" else run_sync(what))
    elif cmd == "telegram-login":
        import integrations
        integrations.telegram_login(load_config())
    elif cmd == "telegram-channels":
        import integrations
        integrations.telegram_channels(load_config())
    elif cmd == "reseed-plan":
        with db() as c:
            c.execute("DELETE FROM content_items")
            c.execute("DELETE FROM plan_days")
            seed_plan(c)
        print("Контент-план загружен заново из", PLAN_SEED.name)
    else:
        sys.exit("Команды: serve | adduser <почта> [имя] | sync [all|getcourse|instagram|telegram] | "
                 "telegram-login | telegram-channels | reseed-plan")


if __name__ == "__main__":
    main(sys.argv)
