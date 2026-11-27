"""Hard Rock screenshot scan: read lines, compare with fair price, send value picks."""
from datetime import timedelta

from ttq.core.timeutil import utcnow
from ttq.ocr.hardrock import Row
from ttq.services import hr_scan


class _P:
    def __init__(self, p1, lo, hi, dq="HIGH"):
        self.p1_win, self.p1_ci_low, self.p1_ci_high, self.data_quality = p1, lo, hi, dq


def test_evaluate_uses_blend_and_band():
    pred = _P(0.62, 0.57, 0.67)
    r = hr_scan.evaluate(pred, (1.80, 2.00), 0.60)       # fair 61% -> 1.80 gives +9.8%
    assert r["value"] and r["side"] == "p1" and r["ev"] > 0.09
    r = hr_scan.evaluate(pred, (1.55, 2.40), 0.64)       # fair 63% -> 1.55 = -2%
    assert not r["value"]
    r = hr_scan.evaluate(_P(0.85, 0.8, 0.9), (1.20, 4.5), 0.84)   # -500 favourite: never
    assert not r["value"]
    r = hr_scan.evaluate(pred, (1.80, 2.00), None)       # model only: 62% x 1.80 = +11.6%, low end 57% x 1.8 >= 1
    assert r["value"]


def test_scan_image_matches_and_sends(f, db, monkeypatch):
    a, b = f.player("Szymon Brud"), f.player("Rafal Stapor")
    m = f.match(a, b, at=utcnow() + timedelta(minutes=40))
    f.prediction(m, p1=0.64, lo=0.59, hi=0.69, dq="HIGH")
    c, d = f.player("Jan Kowal"), f.player("Piotr Nowak")
    m2 = f.match(c, d, at=utcnow() + timedelta(minutes=50))
    f.prediction(m2, p1=0.55, lo=0.50, hi=0.60, dq="HIGH")
    rows = [Row([("Szymon", 95, 10), ("Brud", 95, 80), ("+105", 95, 400)]),
            Row([("Rafal", 95, 10), ("Stapor", 95, 80), ("-140", 95, 400)]),
            Row([("Jan", 95, 10), ("Kowal", 95, 80), ("-150", 95, 400)]),
            Row([("Piotr", 95, 10), ("Nowak", 95, 80), ("+115", 95, 400)])]
    monkeypatch.setattr("ttq.ocr.hardrock.ocr_rows", lambda img: (rows, ""))
    monkeypatch.setattr("ttq.providers.oddspapi.from_sweep", lambda *a, **k: {"status": "no fresh sweep"})
    res = hr_scan.scan_image(db, b"img")
    assert res["read"] == 2 and res["matched"] == 2
    assert [r["match"].id for r in res["value"]] == [m.id]           # Brud 64% at +105 = +31% (model only)
    sent = []
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, body: sent.append(body) or True)
    monkeypatch.setattr("ttq.services.alerts._send_email", lambda t, b: False)
    assert hr_scan.send_value_picks(db, res) == 1 and "Source: your Hard Rock screenshot" in sent[0]
    assert hr_scan.send_value_picks(db, res) == 0                     # never twice
    txt = hr_scan.summary_text(res)
    assert "1 misplaced line" in txt and "Nowak" in txt or "Kowal" in txt
