import os
import json
import time
import requests
from goal_api import GoalAPI

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
KEY = os.environ["GOAL_API_KEY"]
MODE = os.getenv("MODE", "watch")  # "inspect" ou "watch"
POLL_SECONDS = 60
RUN_MINUTES = 27


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT, "text": text[:4000]},
        timeout=15,
    )


def name(m, side):
    return (m.get(side) or {}).get("name", "?")


def inspect(goal):
    live = goal.fixtures.live()["data"]
    send(f"INSPECT: {len(live)} jogos ao vivo")
    if live:
        send(json.dumps(live[0], ensure_ascii=False, indent=1))


def watch(goal):
    seen = {}
    end = time.time() + RUN_MINUTES * 60
    while time.time() < end:
        try:
            live = goal.fixtures.live()["data"]
            for m in live:
                fid = m.get("id") or m.get("fixtureId")
                total = (m.get("homeScore") or 0) + (m.get("awayScore") or 0)
                if fid in seen and total > seen[fid]:
                    send(
                        f"⚽ GOLO! {name(m, 'homeTeam')} {m.get('homeScore')}-"
                        f"{m.get('awayScore')} {name(m, 'awayTeam')}"
                    )
                seen[fid] = total
            rem = goal.rate_limit.remaining
            if rem is not None and rem < 5:
                send("⚠️ Limite da API quase esgotado, a parar.")
                break
        except Exception as e:
            print("erro:", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    goal = GoalAPI(KEY)
    inspect(goal) if MODE == "inspect" else watch(goal)
