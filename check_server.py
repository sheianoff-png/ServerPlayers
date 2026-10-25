"""Проверяет Minecraft-сервер и пишет в Telegram, если что-то изменилось.
Секреты берутся из переменных окружения: MC_SERVER, TG_TOKEN, TG_CHAT_ID.
В логи ничего лишнего не печатается (в публичном репозитории логи видны всем)."""
import json, os, sys, urllib.parse, urllib.request

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
            msgs[-1] += f"\nСейчас на сервере: {cur['count']}/{cur['max']}"
    return msgs


def send(token, chat_id, text):
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    urllib.request.urlopen(
        urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body), timeout=20
    ).read()


def main():
    try:
        server, token, chat = (os.environ[k] for k in ("MC_SERVER", "TG_TOKEN", "TG_CHAT_ID"))
    except KeyError as e:
        sys.exit(f"Не задан секрет: {e.args[0]}")
    try:
        cur = fetch(server)
    except Exception as e:  # сеть/API временно недоступны: состояние не меняем
        print("Не удалось получить статус:", type(e).__name__)
        return
    prev = None
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE))
        except ValueError:
            prev = None
    msgs = build_messages(prev, cur)
    try:
        for m in msgs:
            send(token, chat, m)
    except Exception as e:
        print("Не удалось отправить в Telegram:", type(e).__name__)
        return  # состояние не сохраняем, чтобы повторить в следующий раз
    os.makedirs("state", exist_ok=True)
    json.dump(cur, open(STATE, "w"))
    print(f"ok, сообщений отправлено: {len(msgs)}")


if __name__ == "__main__":
    main()
