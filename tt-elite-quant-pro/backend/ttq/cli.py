"""Operational CLI: python -m ttq.cli <command>"""
import argparse
import json

from ttq.core.logging import setup_logging
from ttq.services import jobs


def main():
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "picks-preview", "test-alert", "price-targets", "backfill-ttseries", "seed-demo", "ingest", "predict", "settle", "monitor", "retrain", "train-force", "hash-password", "cloud-run"])
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--live", action="store_true", help="operate on live (non-demo) data where applicable")
    ap.add_argument("--password")
    ap.add_argument("--from-id", type=int, default=1)
    ap.add_argument("--to-id", type=int)
    ap.add_argument("--window", type=int, default=35, help="cloud-run: release each pick when its match is this many minutes away")
    ap.add_argument("--hold", type=float, default=0, help="cloud-run: keep releasing picks every minute for this many minutes")
    a = ap.parse_args()
    if a.cmd == "hash-password":
        import bcrypt
        print(bcrypt.hashpw(a.password.encode(), bcrypt.gensalt()).decode()); return
    if a.cmd == "cloud-run":
        from ttq.services.cloud import cloud_cycle
        print(json.dumps(cloud_cycle(a.window, hold_minutes=a.hold), indent=2, default=str)[:20000]); return
    if a.cmd == "status":
        from ttq.services.status import system_status
        res = system_status()
        for k, v in res["checks"]:
            print(f"{'OK  ' if v['ok'] else 'FIX '} {k}: {v['detail']}")
        print("\nREADY: picks will be sent to Telegram when a match passes." if res["ready"]
              else "\nNOT READY: fix the items marked FIX above.")
        return
    if a.cmd == "picks-preview":
        from ttq.core.db import SessionLocal
        from ttq.services.messages import conditional_pick_text
        from ttq.services.targets import build_picks
        db = SessionLocal()
        try:
            picks = build_picks(db)
            print(f"{len(picks)} pick(s) would be sent right now (preview only; nothing sent or marked).")
            for pk in picks:
                t, b = conditional_pick_text(db, pk["match"], pk["pred"], pk["side"], pk["p"], pk["min_american"])
                print("\n" + t + "\n" + b)
        finally:
            db.rollback(); db.close()
        return
    if a.cmd == "test-alert":
        from ttq.services.alerts import send_test_alert
        res = send_test_alert()
        print(json.dumps(res, indent=2))
        if "sent" not in res.values():
            print("Nothing was sent. For Telegram set TTQ_TELEGRAM_BOT_TOKEN and TTQ_TELEGRAM_CHAT_ID in .env, then "
                  "run: docker compose up -d --force-recreate api worker")
        return
    if a.cmd == "price-targets":
        r = jobs.run_job("price_targets", lambda db: __import__("ttq.services.targets", fromlist=["x"]).price_targets_job(db))
        print(json.dumps(r, indent=2, default=str)); return
    if a.cmd == "backfill-ttseries":
        print(json.dumps(jobs.backfill_ttseries(a.from_id, a.to_id), indent=2)); return
    if a.cmd == "seed-demo":
        r = jobs.run_job("seed_demo", jobs.seed_demo, fast=a.fast)
    elif a.cmd == "ingest":
        r = {"results": jobs.run_job("ingest_results", jobs.ingest_results_job), "odds": jobs.run_job("ingest_odds", jobs.ingest_odds_job)}
    elif a.cmd == "predict":
        r = jobs.run_job("predict_scan", jobs.predict_scan_job)
    elif a.cmd == "settle":
        r = jobs.run_job("settle", jobs.settle_job)
    elif a.cmd == "monitor":
        r = jobs.run_job("monitor", jobs.monitor_job)
    elif a.cmd == "retrain":
        r = jobs.run_job("retrain", jobs.retrain_job)
    else:
        from ttq.services.modeling import train_and_register
        r = jobs.run_job("train_force", lambda db: train_and_register(db, not a.live, actor="cli", promote="force", fast=a.fast))
    print(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
