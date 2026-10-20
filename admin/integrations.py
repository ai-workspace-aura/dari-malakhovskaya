"""Сбор данных из GetCourse, Instagram и Telegram.

Каждая функция sync_* получает конфиг (config.json) и фабрику соединений с базой,
пишет данные в базу и возвращает короткое сообщение для журнала синхронизаций.
Как получить ключи и токены — в README.md, раздел «Интеграции».
"""
import asyncio
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


def require(section, *keys):
    missing = [k for k in keys if not section.get(k)]
    if missing:
        raise RuntimeError("Не заполнено: " + ", ".join(missing))


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
    g = cfg.get("getcourse", {})
    require(g, "domain", "api_key")
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
    ig = cfg.get("instagram", {})
    require(ig, "user_id", "access_token")
    graph = f"https://{ig.get('graph_host', 'graph.instagram.com')}/{ig.get('version', 'v21.0')}"

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
        from telethon import TelegramClient, errors
        from telethon.sessions import StringSession
    except ImportError:
        raise RuntimeError("Не установлен telethon: выполните pip3 install telethon") from None
    return TelegramClient, StringSession, errors


def _client(t, session=""):
    TelegramClient, StringSession, _ = _telethon()
    if not t.get("api_id") or not t.get("api_hash"):
        raise RuntimeError("Сначала сохраните api_id и api_hash")
    return TelegramClient(StringSession(session or ""), int(t["api_id"]), t["api_hash"])


def _is_admin(entity):
    return bool(getattr(entity, "creator", False) or getattr(entity, "admin_rights", None))


def tg_send_code(t, phone):
    """Шаг 1 входа: Telegram присылает код в приложение. Возвращает состояние для шага 2."""
    async def run():
        client = _client(t)
        await client.connect()
        try:
            r = await client.send_code_request(phone)
            return {"session": client.session.save(), "phone": phone, "hash": r.phone_code_hash}
        finally:
            await client.disconnect()
    return asyncio.run(run())


def tg_sign_in(t, pending, code=None, password=None):
    """Шаг 2 входа: код из Telegram, а при облачном пароле — ещё и пароль."""
    _, _, errors = _telethon()

    async def run():
        client = _client(t, pending["session"])
        await client.connect()
        try:
            if password:
                await client.sign_in(password=password)
            else:
                try:
                    await client.sign_in(phone=pending["phone"], code=code, phone_code_hash=pending["hash"])
                except errors.SessionPasswordNeededError:
                    return {"need_password": True, "session": client.session.save()}
            me = await client.get_me()
            name = " ".join(x for x in (me.first_name, me.last_name) if x) or me.username or me.phone
            return {"session": client.session.save(), "name": name}
        finally:
            await client.disconnect()
    return asyncio.run(run())


async def _channels(client):
    out = []
    async for d in client.iter_dialogs():
        if d.is_channel and not d.is_group:
            username = getattr(d.entity, "username", None)
            out.append({"ref": "@" + username if username else str(d.id), "title": d.name,
                        "admin": _is_admin(d.entity), "entity": d.entity})
    return out


def tg_channels(t):
    async def run():
        client = _client(t, t.get("session"))
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("Аккаунт Telegram не подключён или сессия завершена")
            return [{k: v for k, v in ch.items() if k != "entity"} for ch in await _channels(client)]
        finally:
            await client.disconnect()
    return asyncio.run(run())


def sync_telegram(cfg, db, **_):
    t = cfg.get("telegram", {})
    require(t, "api_id", "api_hash", "session")
    since = dt.datetime.combine(since_date(t), dt.time.min, tzinfo=MSK)
    wanted = [(ch, t.get(key)) for ch, key in (("tg_open", "open_channel"), ("tg_closed", "closed_channel")) if t.get(key)]
    if not wanted:
        return "Каналы не выбраны"

    async def run():
        client = _client(t, t.get("session"))
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("Аккаунт Telegram не подключён или сессия завершена")
            # каналы ищем среди диалогов аккаунта: так находятся и закрытые каналы по числовому ID
            found = {ch["ref"].lower(): ch for ch in await _channels(client)}
            out, counts = [], {}
            for channel, ref in wanted:
                ch = found.get(str(ref).lower())
                if not ch:
                    raise RuntimeError(f"Аккаунт не подписан на канал {ref}")
                if ch["admin"]:
                    # защита: аккаунт с правами админа мог бы менять канал, такой не используем
                    raise RuntimeError(f"У аккаунта есть права админа в «{ch['title']}». Снимите их: "
                                       "для статистики достаточно обычной подписки")
                entity = ch["entity"]
                username = getattr(entity, "username", None)
                seen_albums = set()
                counts[ch["title"]] = 0
                async for msg in client.iter_messages(entity, offset_date=since, reverse=True):
                    if msg.action:  # служебные сообщения: закреп, смена названия и т. п.
                        continue
                    if msg.grouped_id:  # альбом из нескольких фото — это один пост
                        if msg.grouped_id in seen_albums:
                            continue
                        seen_albums.add(msg.grouped_id)
                    out.append((f"tg:{entity.id}:{msg.grouped_id or msg.id}", "telegram", channel,
                                msg.date.astimezone(MSK).date().isoformat(), msg.views or 0,
                                f"https://t.me/{username}/{msg.id}" if username else None))
                    counts[ch["title"]] += 1
            return out, counts
        finally:
            await client.disconnect()

    out, counts = asyncio.run(run())
    save_media(db, out)
    return "; ".join(f"{k}: {v} постов" for k, v in counts.items())
