import os
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
