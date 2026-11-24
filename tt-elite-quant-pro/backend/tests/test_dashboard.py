import json
from datetime import timedelta

from ttq.core.timeutil import utcnow
from ttq.services.dashboard import build_data, decrypt, encrypt, write_site
from ttq.services.summary import log_picks


def test_encrypt_roundtrip_and_wrong_password_fails():
    blob = encrypt({"a": 1}, "secret")
    assert decrypt(blob, "secret") == {"a": 1}
    assert '"a": 1' not in json.dumps(blob) and set(blob) == {"v", "iter", "salt", "iv", "ct"}
    import pytest
    with pytest.raises(Exception):
        decrypt(blob, "nope")


def test_build_data_grades_picks_and_real_bets(f, db):
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() - timedelta(hours=3))
    m.status, m.winner_id, m.sets_p1, m.sets_p2 = "FINISHED", m.player2_id, 1, 3
    db.flush()
    log_picks(db, [{"match_id": m.id, "side": "p2", "p": 0.52, "min_american": 105, "pick_name": "Gz Jurowicz"}],
              now=utcnow() - timedelta(hours=4))
    from ttq.models import AppSetting
    row = db.get(AppSetting, "picks_log")
    v = dict(row.value); v[str(m.id)] = {**v[str(m.id)], "hr_action": "bet", "hr_price": 110}; row.value = v
    db.flush()
    d = build_data(db)
    p = d["picks"][0]
    assert p["result"] == "won" and p["units"] == 1.05 and p["score"] == "1-3" and p["hr_price"] == 110
    r = d["record"]
    assert (r["w"], r["l"], r["bw"], r["bunits"], r["logged"], r["beat"]) == (1, 0, 1, 1.1, 1, 1)


def test_write_site_publishes_only_ciphertext(f, db, tmp_path):
    out = write_site(db, str(tmp_path), "pw")
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [".nojekyll", "data.json", "index.html"]
    blob = json.loads((tmp_path / "data.json").read_text())
    assert set(blob) == {"v", "iter", "salt", "iv", "ct"}
    assert decrypt(blob, "pw")["record"]["w"] == 0 and out["picks"] == 0


def test_stats_hit_rate_curve_and_buckets():
    from ttq.services.dashboard import _stats
    mk = lambda at, res, mn, u, p=0.55: {"_at": at, "result": res, "min": mn, "units": u, "prob": p,
                                         "pick": "X", "match_time": at}
    picks = [mk("2026-11-24T10:00", "won", 105, 1.05), mk("2026-11-24T11:00", "lost", -120, -1.0),
             mk("2026-11-25T10:00", "won", -120, 0.83), {**mk("2026-11-25T12:00", "pending", 110, None)}]
    s = _stats(picks)
    assert (s["settled"], s["wins"], s["losses"], s["pending"]) == (3, 2, 1, 1)
    assert abs(s["hit_rate"] - 2 / 3) < 1e-9 and s["units"] == 0.88 and s["streak"] == "W1" and s["last10"] == "WLW"
    assert [c["units"] for c in s["curve"]] == [1.05, 0.05, 0.88]
    assert s["by_day"][0] == {"date": "2026-11-25", "w": 1, "l": 0, "units": 0.83}
    fav = s["buckets"]["Favorites (minimum below +100)"]
    assert (fav["w"], fav["l"]) == (1, 1)
