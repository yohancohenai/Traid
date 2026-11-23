"""Hard Rock screenshot import: parser, OCR end-to-end on a synthetic image, matching, endpoint never auto-saves."""
import io
import shutil
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from ttq.core.timeutil import utcnow
from ttq.models import DataSource, OddsQuote, Tournament
from ttq.ocr.hardrock import PlayerLine, Row, norm_odds, pair_matches, parse_rows, propose

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "hardrock"))
from make_synthetic import render  # noqa: E402

needs_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract binary not installed")


def R(*toks, conf=90):
    return Row([(t, conf, i * 100) for i, t in enumerate(toks)])


def test_odds_tokens():
    assert norm_odds("-150") == -150 and norm_odds("+120") == 120 and norm_odds("−185") == -185
    assert norm_odds("EVEN") == 100 and norm_odds("-1.5") is None and norm_odds("+50") is None


def test_parse_rows_takes_rightmost_moneyline_and_skips_junk():
    rows = [R("Table", "Tennis", ">", "TT", "Elite", "Series"), R("Spread", "Total", "Money"), R("Today", "11:30", "AM"),
            R("Pawel", "Kurek", "-1.5", "+110", "O", "74.5", "-115", "-150"),
            R("Grzegorz", "Wichowski", "+1.5", "-140", "U", "74.5", "-105", "+120")]
    lines = parse_rows(rows)
    assert [(l.name, l.american) for l in lines] == [("Pawel Kurek", -150), ("Grzegorz Wichowski", 120)]
    assert lines[0].notes   # several prices on row -> noted for review
    assert len(pair_matches(lines)) == 1


def _upcoming(f, n1, n2, minutes=60):
    a, b = f.player(n1), f.player(n2)
    return f.match(a, b, at=utcnow() + timedelta(minutes=minutes))


def test_propose_matches_names_and_flips_order(f, db):
    m = _upcoming(f, "Pawel Kurek", "Grzegorz Wichowski")
    _upcoming(f, "Jakub Kosowski", "Tibor Spanik")
    pairs = [(PlayerLine("Wichowski G.", 120, 90), PlayerLine("Kurek P.", -150, 90))]   # reversed + abbreviated
    p = propose(db, pairs, False)[0]
    assert p["match_id"] == m.id
    assert (p["p1_american"], p["p2_american"]) == (-150, 120)     # flipped back to official order
    assert not p["needs_review"], p["reasons"]


def test_propose_flags_unknown_and_implausible(f, db):
    _upcoming(f, "Pawel Kurek", "Grzegorz Wichowski")
    p = propose(db, [(PlayerLine("Someone Else", -150, 90), PlayerLine("Another Guy", 120, 90))], False)[0]
    assert p["match_id"] is None and p["needs_review"]
    p = propose(db, [(PlayerLine("Pawel Kurek", 500, 90), PlayerLine("Grzegorz Wichowski", 500, 90))], False)[0]
    assert p["needs_review"] and any("overround" in r for r in p["reasons"])


@needs_tesseract
def test_endpoint_reads_synthetic_screenshot_and_saves_nothing(f, db, client):
    m1 = _upcoming(f, "Pawel Kurek", "Grzegorz Wichowski", 30)
    m2 = _upcoming(f, "Jakub Kosowski", "Tibor Spanik", 55)
    db.commit()
    buf = io.BytesIO()
    render([(("Pawel Kurek", "-1.5", "O 74.5", "-150"), ("Grzegorz Wichowski", "+1.5", "U 74.5", "+120"), "Today 11:30 AM"),
            (("Jakub Kosowski", "-1.5", "O 76.5", "−185"), ("Tibor Spanik", "+1.5", "U 76.5", "+145"), "Today 11:55 AM")]).save(buf, "PNG")
    r = client.post("/api/odds/screenshot", files={"file": ("hr.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    props = {p["match_id"]: p for p in r.json()["proposals"]}
    assert (props[m1.id]["p1_american"], props[m1.id]["p2_american"]) == (-150, 120)
    assert (props[m2.id]["p1_american"], props[m2.id]["p2_american"]) == (-185, 145)
    assert db.query(OddsQuote).count() == 0                     # proposals only
    # user confirms -> existing manual endpoint stores verified quotes
    body = [{"match_id": m1.id, "selection": "p1", "american": -150}, {"match_id": m1.id, "selection": "p2", "american": 120}]
    assert client.post("/api/odds/manual", json=body).status_code == 200
    assert {q["freshness"] for q in client.get(f"/api/odds/{m1.id}").json()["books"]["hardrock"]["quotes"].values()} == {"VERIFIED"}


def test_endpoint_rejects_garbage(client):
    assert client.post("/api/odds/screenshot", files={"file": ("x.png", b"not an image", "image/png")}).status_code in (422, 503)


def test_catch_up_after_downtime(db):
    from ttq.services.jobs import catch_up_ttseries
    db.add(DataSource(key="ttseries", name="t", kind="results", last_success_at=utcnow() - timedelta(days=3)))
    db.add(Tournament(name="t", source_key="ttseries", source_ref="tts-400"))
    db.flush()
    called = []
    assert catch_up_ttseries(db, backfill=lambda start: called.append(start) or {"ok": 1}) == {"ok": 1}
    assert called == [370]
    db.query(DataSource).one().last_success_at = utcnow()
    assert catch_up_ttseries(db, backfill=lambda s: called.append(s)) is None and called == [370]


def test_real_layout_junk_rows_dont_shift_pairing():
    """Reproduces the first real Hard Rock import: an 'EST wagers' label row used to shift every pair after it."""
    rows = [R("Artur", "-800"), R("Dariusz", "+475"),
            R("EST", "wagers"),
            R("Adam", "-300"), R("Aleksander", "+190"),
            R("Slawomir", "+115"), R("Andrzej", "Krezel", "-165"),
            R("EST", "wagers"),
            R("Henryk", "-185"), R("Jakub", "Nowak", "+130")]
    pairs = [(a.name, a.american, b.name, b.american) for a, b in pair_matches(parse_rows(rows))]
    assert pairs == [("Artur", -800, "Dariusz", 475), ("Adam", -300, "Aleksander", 190),
                     ("Slawomir", 115, "Andrzej Krezel", -165), ("Henryk", -185, "Jakub Nowak", 130)]


def test_surname_on_next_line_is_joined():
    lines = parse_rows([R("Artur", "-140"), R("Sobel"), R("Mikolaj", "Lukaszewski", "+100")])
    assert [l.name for l in lines] == ["Artur Sobel", "Mikolaj Lukaszewski"]


def test_first_name_pairs_match_official_schedule(f, db):
    m = _upcoming(f, "Artur Sobel", "Dariusz Dytko")
    _upcoming(f, "Pawel Kurek", "Grzegorz Wichowski")
    p = propose(db, [(PlayerLine("Artur", -800, 90), PlayerLine("Dariusz", 475, 90))], False)[0]
    assert p["match_id"] == m.id and (p["p1_american"], p["p2_american"]) == (-800, 475)


def test_one_strong_name_cannot_carry_a_wrong_partner(f, db):
    _upcoming(f, "Artur Sobel", "Dariusz Dytko")
    p = propose(db, [(PlayerLine("Artur Sobel", -800, 90), PlayerLine("Zbigniew", 475, 90))], False)[0]
    assert p["match_id"] is None and p["needs_review"]


def test_ambiguous_first_names_stay_flagged(f, db):
    _upcoming(f, "Artur Sobel", "Dariusz Dytko", 30)
    _upcoming(f, "Artur Nowak", "Dariusz Krol", 50)
    p = propose(db, [(PlayerLine("Artur", -800, 90), PlayerLine("Dariusz", 475, 90))], False)[0]
    assert p["needs_review"] and any("more than one" in r for r in p["reasons"])
