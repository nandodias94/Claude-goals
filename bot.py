import os
import re
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
COOLDOWN_MIN = 12          # minutos sem repetir alerta no mesmo jogo
STATS_EVERY_SEC = 180      # de quanto em quanto tempo ir buscar stats de um jogo
WINDOW = (30, 85)          # só analisa jogos entre estes minutos

# Critérios (por minuto jogado) para o sinal estatístico
MIN_DANGEROUS_PER_MIN = 1.0    # ataques perigosos / minuto
MIN_SOT_PER_MIN = 0.08         # remates à baliza / minuto
MIN_SHOTS_PER_MIN = 0.30       # remates totais / minuto
MIN_CRITERIA = 3               # 3 = só sinais FORTES; 2 = também MÉDIOS
MIN_HEAT = 4                   # pontos mínimos no sinal por eventos (ligas sem stats)


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


def minute_of(value):
    mm = re.match(r"\d+", str(value or ""))
    return int(mm.group()) if mm else 0


def num(v):
    mm = re.search(r"-?\d+(\.\d+)?", str(v if v is not None else ""))
    return float(mm.group()) if mm else None


def period_label(m):
    p = str(m.get("matchPeriod") or "")
    if "SECOND" in p:
        return "2.ª parte"
    if "FIRST" in p:
        return "1.ª parte"
    return "2.ª parte" if (m.get("matchElapsed") or 0) > 45 else "1.ª parte"


# ---------- sinal por eventos (funciona em qualquer liga) ----------
def heat(m):
    el = m.get("matchElapsed") or 0
    h, a = score(m, "homeTeamScore"), score(m, "awayTeamScore")
    total, diff = h + a, abs(h - a)
    events = m.get("events") or []
    goals = [minute_of(e.get("time")) for e in events if e.get("type") == "GOAL"]
    reds = [e for e in events if "RED" in str(e.get("type", "")).upper()]
    pts, why = 0, []
    if el < 10:
        return 0, []
    if total and total / el * 90 >= 3:
        pts += 2
        why.append(f"ritmo de golos alto ({total} em {el}')")
    if goals and el - max(goals) <= 10:
        pts += 1
        why.append("golo nos últimos 10'")
    if diff <= 1 and el >= 65:
        pts += 1
        why.append("resultado apertado na fase final")
    if reds:
        pts += 1
        why.append("expulsão")
    if 35 <= el <= 44 or 70 <= el <= 88:
        pts += 1
        why.append("janela de maior probabilidade de golo")
    if total == 0 and el >= 60:
        pts -= 2
        why.append("0-0 tardio")
    return pts, why


# ---------- estatísticas (só ligas com cobertura) ----------
def parse_stats(resp):
    """Extrai ataques perigosos, remates à baliza e remates totais.
    O formato exato depende da API: confirma com o modo inspect."""
    d = (resp or {}).get("data") or {}
    if not d.get("hasStatistics"):
        return None
    rows = (d.get("match") or {}).get("fullTime") or []
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        label = ""
        for k in ("name", "type", "stat", "label", "statistic", "title"):
            if k in r:
                label = str(r[k]).lower()
                break
        hv = next((r[k] for k in ("home", "homeValue", "home_value") if k in r), None)
        av = next((r[k] for k in ("away", "awayValue", "away_value") if k in r), None)
        hv, av = num(hv), num(av)
        if hv is None or av is None:
            continue
        if "dangerous" in label:
            out["da"] = (hv, av)
        elif "on target" in label or "on goal" in label:
            out["sot"] = (hv, av)
        elif "shot" in label and not any(
            x in label for x in ("off", "block", "insid", "outsid", "target", "goal")
        ):
            out["shots"] = (hv, av)
    return out or None


def criteria(st, el):
    hits = 0
    if "da" in st and sum(st["da"]) / el >= MIN_DANGEROUS_PER_MIN:
        hits += 1
    if "sot" in st and sum(st["sot"]) / el >= MIN_SOT_PER_MIN:
        hits += 1
    if "shots" in st and sum(st["shots"]) / el >= MIN_SHOTS_PER_MIN:
        hits += 1
    return hits


def fmt(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def build_message(m, st=None, hits=0, heat_pts=0, why=None):
    h, a = score(m, "homeTeamScore"), score(m, "awayTeamScore")
    total = h + a
    lines = [
        "⚽ CLAUDE BOT — SINAL DE GOLO",
        "",
        f"🏆 {m.get('leagueName', '?')}",
        f"🏟 {name(m, 'homeTeam')} - {name(m, 'awayTeam')}",
        f"📊 Resultado: {h}-{a}",
        f"⏱ Minuto: {m.get('matchElapsed')}' ({period_label(m)})",
        "",
    ]
    if st:
        if "da" in st:
            lines.append(f"🔥 Ataques perigosos: {fmt(sum(st['da']))} "
                         f"({fmt(st['da'][0])}-{fmt(st['da'][1])})")
        if "sot" in st:
            lines.append(f"🎯 Remates à baliza: {fmt(sum(st['sot']))} "
                         f"({fmt(st['sot'][0])}-{fmt(st['sot'][1])})")
        if "shots" in st:
            lines.append(f"🥅 Remates totais: {fmt(sum(st['shots']))}")
        lines.append("")
        nivel = "FORTE" if hits >= 3 else "MÉDIO"
        sinal = f"{nivel} ({hits}/3 critérios)"
    else:
        lines.append("ℹ️ Sem estatísticas nesta liga — sinal pelo ritmo do jogo:")
        lines += [f"- {w}" for w in (why or [])]
        lines.append("")
        sinal = f"MÉDIO ({heat_pts} pts)"
    lines.append(f"📌 Mercado indicativo: Mais de {total}.5 golos")
    lines.append(f"{'🟢' if st and hits >= 3 else '🟡'} Sinal estatístico: {sinal}")
    lines.append("")
    lines.append("⚠️ Alerta estatístico. Não garante golo.")
    return "\n".join(lines)


def inspect(goal):
    live = goal.fixtures.live()["data"]
    send(f"INSPECT: {len(live)} jogos ao vivo")
    com, sem, primeiro = [], [], None
    for m in live[:15]:
        nome = (f"{name(m, 'homeTeam')} - {name(m, 'awayTeam')} "
                f"[{m.get('leagueName')}] {m.get('matchElapsed')}'")
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
        send("parse_stats dá: " + json.dumps(parse_stats(primeiro[1])))


def watch(goal):
    goals_seen, last_alert, no_stats, stats_at = {}, {}, set(), {}
    end = time.time() + RUN_MINUTES * 60
    while time.time() < end:
        try:
            live = goal.fixtures.live()["data"]
            now = time.time()
            for m in live:
                fid = m.get("id")
                el = m.get("matchElapsed") or 0
                h, a = score(m, "homeTeamScore"), score(m, "awayTeamScore")
                total = h + a
                goals_seen[fid] = total

                if not (WINDOW[0] <= el <= WINDOW[1]):
                    continue
                if now - last_alert.get(fid, 0) < COOLDOWN_MIN * 60:
                    continue

                st = None
                if fid not in no_stats and now - stats_at.get(fid, 0) >= STATS_EVERY_SEC:
                    stats_at[fid] = now
                    try:
                        st = parse_stats(goal.fixtures.statistics(fid))
                    except Exception as e:
                        print("erro stats:", e)
                    if st is None:
                        no_stats.add(fid)
                if st:
                    hits = criteria(st, max(el, 1))
                    if hits >= MIN_CRITERIA:
                        last_alert[fid] = now
                        send(build_message(m, st=st, hits=hits))
                elif fid in no_stats:
                    pts, why = heat(m)
                    if pts >= MIN_HEAT:
                        last_alert[fid] = now
                        send(build_message(m, heat_pts=pts, why=why))
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
