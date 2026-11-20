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


def score(m, side):
    try:
        return int(m.get(side) or 0)
    except (TypeError, ValueError):
        return 0


def inspect(goal):
    live = goal.fixtures.live()["data"]
    send(f"INSPECT: {len(live)} jogos ao vivo")
    if live:
        # testa até 15 jogos e diz em quais há estatísticas
        com, sem, primeiro = [], [], None
        for m in live[:15]:
            nome = (f"{name(m, 'homeTeam')} - {name(m, 'awayTeam')} "
                    f"[{m.get('leagueName')}]")
            try:
                s = goal.fixtures.statistics(m["id"])
                if (s.get("data") or {}).get("hasStatistics"):
                    com.append(nome)
                    primeiro = primeiro or (nome, s)
                else:
                    sem.append(nome)
            except Exception as e:
                sem.append(f"{nome} (erro: {e})")
        send(f"COM estatísticas ({len(com)}):\n" + "\n".join(com))
        send(f"SEM estatísticas ({len(sem)}):\n" + "\n".join(sem))
        if primeiro:
            send(f"Exemplo: {primeiro[0]}")
            send(json.dumps(primeiro[1], ensure_ascii=False, indent=1))


def watch(goal):
    seen = {}
    end = time.time() + RUN_MINUTES * 60
    while time.time() < end:
        try:
            live = goal.fixtures.live()["data"]
            for m in live:
                fid = m.get("id")
                h, a = score(m, "homeTeamScore"), score(m, "awayTeamScore")
                total = h + a
                if fid in seen and total > seen[fid]:
                    send(
                        f"⚽ GOLO! {name(m, 'homeTeam')} {h}-{a} "
                        f"{name(m, 'awayTeam')} ({m.get('matchElapsed')}')"
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
