"""Operational CLI: python -m ttq.cli <command>"""
import argparse
import json

from ttq.core.logging import setup_logging
from ttq.services import jobs


def main():
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed-demo", "ingest", "predict", "settle", "monitor", "retrain", "train-force", "hash-password"])
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--live", action="store_true", help="operate on live (non-demo) data where applicable")
    ap.add_argument("--password")
    a = ap.parse_args()
    if a.cmd == "hash-password":
        import bcrypt
        print(bcrypt.hashpw(a.password.encode(), bcrypt.gensalt()).decode()); return
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
