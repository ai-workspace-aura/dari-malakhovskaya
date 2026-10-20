"""Сбор данных из GetCourse, Instagram и Telegram.

Каждая функция sync_* получает конфиг (config.json) и фабрику соединений с базой,
пишет данные в базу и возвращает короткое сообщение для журнала синхронизаций.
Как получить ключи и токены — в README.md, раздел «Интеграции».
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request

MSK = dt.timezone(dt.timedelta(hours=3))


def http_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "UnionAdmin/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code}: {body}") from None


def since_date(section, default_days=45):
    s = section.get("since")
    if s:
        return dt.date.fromisoformat(s)
    return dt.date.today() - dt.timedelta(days=default_days)


def save_media(db, items):
    """items: (id, source, channel, date, reach, permalink)"""
    now = dt.datetime.now(MSK).replace(microsecond=0).isoformat()
    with db() as c:
        for it in items:
            c.execute("""INSERT INTO media(id,source,channel,date,reach,permalink,fetched_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET reach=excluded.reach, date=excluded.date,
                         channel=excluded.channel, permalink=excluded.permalink, fetched_at=excluded.fetched_at""",
                      (*it, now))


# ---------- GetCourse: выгрузка заказов по API ----------

def sync_getcourse(cfg, db, import_table, max_wait=300, **_):
    """GetCourse готовит выгрузку асинхронно. Ждём до max_wait секунд; если не успела,
    номер выгрузки запоминаем и забираем её при следующем запуске."""
    g = cfg["getcourse"]
    base = f"https://{g['domain']}/pl/api/account"
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='gc_pending_export'").fetchone()
    export_id = json.loads(row["value"]) if row else None
    if not export_id:
        q = urllib.parse.urlencode({"key": g["api_key"], "created_at[from]": since_date(g).isoformat()})
        r = http_json(f"{base}/deals?{q}")
        if not r.get("success"):
            raise RuntimeError(r.get("error_message") or json.dumps(r, ensure_ascii=False)[:300])
        export_id = r["info"]["export_id"]
    info = None
    deadline = time.time() + max_wait
    while True:
        r = http_json(f"{base}/exports/{export_id}?" + urllib.parse.urlencode({"key": g["api_key"]}))
        if r.get("success") and "items" in (r.get("info") or {}):
            info = r["info"]
            break
        if time.time() + 10 > deadline:
            break
        time.sleep(10)
    with db() as c:
        if info is None:
            c.execute("INSERT INTO settings(key,value) VALUES('gc_pending_export',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(export_id),))
            return f"GetCourse ещё готовит выгрузку №{export_id}, заберём её при следующем запуске"
        c.execute("DELETE FROM settings WHERE key='gc_pending_export'")
        stats = import_table(c, info["fields"], info["items"], "getcourse")
    return f"Заказов в выгрузке: {len(info['items'])}; новых {stats['created']}, обновлено {stats['updated']}"


# ---------- Instagram Graph API: сторис и рилс ----------

def parse_ig_time(ts):
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(MSK).date()


def sync_instagram(cfg, db, **_):
    ig = cfg["instagram"]
    graph = f"https://{ig.get('graph_host', 'graph.facebook.com')}/{ig.get('version', 'v21.0')}"

    def get(path, **params):
        params["access_token"] = ig["access_token"]
        url = path if path.startswith("http") else f"{graph}/{path}?{urllib.parse.urlencode(params)}"
        return http_json(url)

    def insight(media_id, metrics):
        # набор доступных метрик у Meta меняется: пробуем по очереди
        for metric in metrics:
            try:
                data = get(f"{media_id}/insights", metric=metric).get("data") or []
            except RuntimeError:
                continue
            if data:
                d = data[0]
                if d.get("total_value"):
                    return int(d["total_value"].get("value") or 0)
                return int((d.get("values") or [{}])[0].get("value") or 0)
        return 0

    out = []
    # сторис живут 24 часа: забирать их нужно хотя бы раз в сутки, иначе охват потеряется
    stories = get(f"{ig['user_id']}/stories", fields="id,timestamp,permalink").get("data") or []
    for s in stories:
        out.append((f"ig:{s['id']}", "instagram", "stories", parse_ig_time(s["timestamp"]).isoformat(),
                    insight(s["id"], ["reach"]), s.get("permalink")))

    since = since_date(ig)
    page = get(f"{ig['user_id']}/media", fields="id,timestamp,media_product_type,permalink", limit=50)
    reels = 0
    while page:
        stop = False
        for m in page.get("data") or []:
            d = parse_ig_time(m["timestamp"])
            if d < since:
                stop = True
                break
            if m.get("media_product_type") == "REELS":
                reels += 1
                out.append((f"ig:{m['id']}", "instagram", "reels", d.isoformat(),
                            insight(m["id"], ["views", "plays", "reach"]), m.get("permalink")))
        nxt = (page.get("paging") or {}).get("next")
        page = None if stop or not nxt else get(nxt)
    save_media(db, out)
    return f"Сторис: {len(stories)}, рилс: {reels}"


# ---------- Telegram: просмотры постов через аккаунт админа (Telethon) ----------

def _telethon():
    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        raise RuntimeError("Не установлен telethon: выполните pip3 install telethon") from None
    return TelegramClient, StringSession


def telegram_login(cfg):
    TelegramClient, StringSession = _telethon()
    t = cfg["telegram"]
    with TelegramClient(StringSession(), int(t["api_id"]), t["api_hash"]) as client:
        print("\nСтрока сессии (вставьте в config.json → telegram.session):\n")
        print(client.session.save())


def telegram_channels(cfg):
    TelegramClient, StringSession = _telethon()
    t = cfg["telegram"]
    with TelegramClient(StringSession(t["session"]), int(t["api_id"]), t["api_hash"]) as client:
        print("\nКаналы этого аккаунта (скопируйте нужное значение из левой колонки):\n")
        for d in client.iter_dialogs():
            if d.is_channel and not d.is_group:
                username = getattr(d.entity, "username", None)
                print(f"{'@' + username if username else d.id:<22} {d.name}")


def sync_telegram(cfg, db, **_):
    TelegramClient, StringSession = _telethon()
    t = cfg["telegram"]
    since = dt.datetime.combine(since_date(t), dt.time.min, tzinfo=MSK)
    out = []
    counts = {}
    with TelegramClient(StringSession(t["session"]), int(t["api_id"]), t["api_hash"]) as client:
        for channel, ref in (("tg_open", t.get("open_channel")), ("tg_closed", t.get("closed_channel"))):
            if not ref:
                continue
            entity = client.get_entity(int(ref) if str(ref).lstrip("-").isdigit() else ref)
            seen_albums = set()
            counts[channel] = 0
            for msg in client.iter_messages(entity, offset_date=since, reverse=True):
                if msg.action:  # служебные сообщения: закреп, смена названия и т. п.
                    continue
                if msg.grouped_id:  # альбом из нескольких фото — это один пост
                    if msg.grouped_id in seen_albums:
                        continue
                    seen_albums.add(msg.grouped_id)
                key = f"tg:{entity.id}:{msg.grouped_id or msg.id}"
                username = getattr(entity, "username", None)
                link = f"https://t.me/{username}/{msg.id}" if username else None
                out.append((key, "telegram", channel, msg.date.astimezone(MSK).date().isoformat(),
                            msg.views or 0, link))
                counts[channel] += 1
    save_media(db, out)
    return ", ".join(f"{k}: {v} постов" for k, v in counts.items()) or "Каналы не указаны в config.json"
