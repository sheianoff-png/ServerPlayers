"""Проверяет Minecraft-сервер и пишет в Telegram, если что-то изменилось.
Секреты берутся из переменных окружения: MC_SERVER, TG_TOKEN, TG_CHAT_ID.
В логи ничего лишнего не печатается (в публичном репозитории логи видны всем)."""
import datetime, json, os, sys, urllib.parse, urllib.request

STATE = "state/state.json"
API = "https://api.mcstatus.io/v2/status/java/"
HEADERS = {"User-Agent": "mc-notify-bot/1.0"}


def fetch(server):
    req = urllib.request.Request(API + urllib.parse.quote(server, safe=":"), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    players = data.get("players") or {}
    sample = players.get("list") or players.get("sample") or []
    names = sorted({(p.get("name_clean") or p.get("name") or "").strip() for p in sample} - {""})
    return {
        "online": bool(data.get("online")),
        "count": int(players.get("online") or 0),
        "max": int(players.get("max") or 0),
        "names": names,
    }


def status_text(cur):
    if not cur["online"]:
        return "🔴 Сервер оффлайн"
    text = f"🟢 Онлайн: {cur['count']}/{cur['max']}"
    if cur["names"]:
        text += "\nИграют: " + ", ".join(cur["names"])
    elif cur["count"]:
        text += "\nИмена игроков сервер не показывает"
    return text


def build_messages(prev, cur):
    msgs = []
    if prev is None:
        state = "онлайн 🟢" if cur["online"] else "оффлайн 🔴"
        return [f"Бот запущен. Сервер сейчас {state}, игроков: {cur['count']}/{cur['max']}"]
    if cur["online"] != prev["online"]:
        msgs.append("🟢 Сервер включился" if cur["online"] else "🔴 Сервер выключился")
    if cur["online"] and prev["online"]:
        # имена надёжны только если список не обрезан и не пустой
        full = cur["names"] and len(cur["names"]) >= cur["count"] and prev["names"]
        if full:
            joined = [n for n in cur["names"] if n not in prev["names"]]
            left = [n for n in prev["names"] if n not in cur["names"]]
            if joined:
                msgs.append("➕ Зашёл: " + ", ".join(joined))
            if left:
                msgs.append("➖ Вышел: " + ", ".join(left))
        elif cur["count"] != prev["count"]:
            msgs.append(f"👥 Онлайн: {prev['count']} → {cur['count']}")
        if msgs and cur["count"]:
            msgs[-1] += "\n" + status_text(cur)
    return msgs


def send(token, chat_id, text, silent=False, url=None):
    params = {"chat_id": chat_id, "text": text}
    if url:  # кнопка под сообщением: открывает живую страницу статуса сервера
        params["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": "🌐 Онлайн сейчас", "url": url}]]})
    if silent:
        params["disable_notification"] = "true"  # сообщение придёт без звука
    body = urllib.parse.urlencode(params).encode()
    urllib.request.urlopen(
        urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body), timeout=20
    ).read()


def tg(token, method, **params):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["result"]


def pc_alive(token, max_age=420):
    """Бот на ПК раз в 2 минуты пишет в описание бота «🟢 ПК онлайн · дата время UTC».
    Если отметка свежая, ПК работает и сам шлёт уведомления, а мы молчим.
    Если отметка устарела, берём уведомления на себя и меняем описание."""
    try:
        text = tg(token, "getMyShortDescription").get("short_description", "")
        if not text.startswith("🟢"):
            return False
        stamp = text.split("·")[-1].replace("UTC", "").strip()
        t = datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
        if age < max_age:
            return True
        tg(token, "setMyShortDescription", short_description="☁️ ПК выключен, бот работает через GitHub")
    except Exception:
        pass
    return False


def main():
    try:
        server, token, chat = (os.environ[k] for k in ("MC_SERVER", "TG_TOKEN", "TG_CHAT_ID"))
    except KeyError as e:
        sys.exit(f"Не задан секрет: {e.args[0]}")
    server = server.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not server or not token.strip() or not chat.strip():
        sys.exit("Один из секретов пустой: проверь MC_SERVER, TG_TOKEN и TG_CHAT_ID")
    token, chat = token.strip(), chat.strip()
    try:
        cur = fetch(server)
    except Exception as e:  # сеть/API временно недоступны: состояние не меняем
        print("Не удалось получить статус:", type(e).__name__, getattr(e, "code", ""))
        return
    status_url = "https://mcsrvstat.us/server/" + urllib.parse.quote(server, safe=":")
    prev = None
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE))
        except ValueError:
            prev = None
    msgs = build_messages(prev, cur)
    changes = bool(msgs)
    manual = os.environ.get("REPORT") == "1"  # ручной запуск из вкладки Actions
    always = manual or os.environ.get("ALWAYS_REPORT") == "1"  # писать при каждой проверке
    if always and not any("Онлайн:" in m for m in msgs):
        msgs.append(status_text(cur))
    if not manual and pc_alive(token):
        msgs = []  # бот на ПК жив и сам пишет, мы только обновляем сохранённое состояние
    try:
        for m in msgs:
            send(token, chat, m, silent=(not changes and not manual), url=status_url)
    except Exception as e:
        print("Не удалось отправить в Telegram:", type(e).__name__, getattr(e, "code", ""))
        return  # состояние не сохраняем, чтобы повторить в следующий раз
    os.makedirs("state", exist_ok=True)
    json.dump(cur, open(STATE, "w"))
    print(f"ok, сообщений отправлено: {len(msgs)}")


if __name__ == "__main__":
    main()
