"""Read Hard Rock Bet table-tennis list screenshots with free local OCR (Tesseract).

Nothing read here is saved automatically: the API returns *proposals* that the user confirms or fixes, then the
confirmed prices go through the normal manual-quote path (timestamped, validated, freshness-checked).

Layout assumptions (generic sportsbook list, to be tuned on real screenshots):
- each player is a text row: name, then optional Spread / Total cells, then Moneyline (rightmost American odds);
- two consecutive player rows form one match.
"""
from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass, field

ODDS_RE = re.compile(r"^[+\-−–]\d{3,5}$")
EVEN_RE = re.compile(r"^(EVEN|EV)$", re.I)
LINE_RE = re.compile(r"^[+\-−–]?\d{1,3}(\.\d)?$|^[OU]$|^[OU]\d")
NAME_RE = re.compile(r"^[A-Za-zÀ-žŁłŚśŻżŹźĆćŃńÓóĄąĘę.'\-]+$")
JUNK = {"MORE", "BETS", "SPREAD", "TOTAL", "MONEY", "MONEYLINE", "LIVE", "TODAY", "TOMORROW", "AM", "PM", "TT",
        "ELITE", "SERIES", "TABLE", "TENNIS", "POLAND", "BET", "SGP", "SETS", "SET", "MATCH"}


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class Row:
    words: list[tuple[str, float, int]]  # (text, confidence 0-100, left x)

    @property
    def conf(self) -> float:
        return min((c for _, c, _ in self.words), default=0)


@dataclass
class PlayerLine:
    name: str
    american: int | None
    conf: float
    notes: list[str] = field(default_factory=list)


def norm_odds(tok: str) -> int | None:
    t = tok.replace("−", "-").replace("–", "-").strip()
    if EVEN_RE.match(t):
        return 100
    if ODDS_RE.match(t):
        v = int(t)
        return v if v <= -100 or v >= 100 else None
    return None


def parse_rows(rows: list[Row]) -> list[PlayerLine]:
    """Turn OCR rows into player lines (name + moneyline). Rows without a name are ignored."""
    out = []
    for r in rows:
        name_parts, odds, notes = [], [], []
        for text, conf, left in sorted(r.words, key=lambda w: w[2]):
            o = norm_odds(text)
            if o is not None:
                odds.append(o)
                continue
            if LINE_RE.match(text.replace("−", "-")) or re.match(r"^\d{1,2}:\d{2}$", text):
                continue
            if NAME_RE.match(text) and text.upper().strip(".") not in JUNK and len(text.strip(".")) >= 1:
                name_parts.append(text)
        name = " ".join(name_parts).strip()
        if len(name.replace(".", "")) < 3:
            continue
        if not odds:
            out.append(PlayerLine(name, None, r.conf, ["no moneyline found"]))
            continue
        if len(odds) > 1:
            notes.append("several prices on the row; took the rightmost as moneyline")
        out.append(PlayerLine(name, odds[-1], r.conf, notes))
    return out


def pair_matches(lines: list[PlayerLine]) -> list[tuple[PlayerLine, PlayerLine]]:
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def ocr_rows(image_bytes: bytes) -> tuple[list[Row], str]:
    if not shutil.which("tesseract"):
        raise OcrUnavailable("Tesseract is not installed. On Mac: `brew install tesseract`; Docker images include it.")
    import pytesseract
    from PIL import Image, ImageOps, ImageStat
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("L")
    if ImageStat.Stat(img).mean[0] < 128:          # dark app theme -> dark text on light background
        img = ImageOps.invert(img)
    img = ImageOps.autocontrast(img)
    if img.width < 1600:
        img = img.resize((img.width * 2, img.height * 2))
    d = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    groups: dict[tuple, list] = {}
    for i, txt in enumerate(d["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        groups.setdefault(key, []).append((txt, float(d["conf"][i]), int(d["left"][i]), int(d["top"][i])))
    rows = [Row([(t, c, l) for t, c, l, _ in ws]) for _, ws in sorted(groups.items(), key=lambda kv: min(w[3] for w in kv[1]))]
    text = "\n".join(" ".join(w[0] for w in r.words) for r in rows)
    return rows, text


# ---------------------------------------------------------------- matching to the official schedule
def name_score(raw: str, canonical: str) -> float:
    from ttq.identity.names import normalize_name, similarity, surname_initial_key
    s = similarity(raw, canonical)
    abbr = surname_initial_key(raw)
    if abbr:
        sur, ini = abbr.split("|")
        toks = normalize_name(canonical).split()
        if sur in toks and any(t.startswith(ini) for t in toks if t != sur):
            s = max(s, 0.92)
    return s


def propose(db, pairs: list[tuple[PlayerLine, PlayerLine]], is_demo: bool, now=None, horizon_hours: int = 36) -> list[dict]:
    """Match each OCR'd pair to an upcoming scheduled match. Returns proposals for user confirmation (never saved)."""
    from datetime import timedelta
    from sqlalchemy import select
    from ttq.core.timeutil import utcnow
    from ttq.models import Match
    from ttq.odds.math import american_to_decimal, overround
    now = now or utcnow()
    ups = db.scalars(select(Match).where(Match.is_demo == is_demo, Match.status == "SCHEDULED",
                                         Match.scheduled_at > now - timedelta(minutes=5),
                                         Match.scheduled_at <= now + timedelta(hours=horizon_hours))
                     .order_by(Match.scheduled_at)).all()
    out = []
    for a, b in pairs:
        scored = []
        for m in ups:
            n1, n2 = m.player1.canonical_name, m.player2.canonical_name
            straight = (name_score(a.name, n1) + name_score(b.name, n2)) / 2
            flipped = (name_score(a.name, n2) + name_score(b.name, n1)) / 2
            scored.append((max(straight, flipped), flipped > straight, m))
        scored.sort(key=lambda x: (-x[0], x[2].scheduled_at))
        reasons = list(a.notes + b.notes)
        best = scored[0] if scored and scored[0][0] >= 0.75 else None
        if best is None:
            reasons.append("no upcoming official match found for these names")
        elif len(scored) > 1 and scored[1][0] >= best[0] - 0.05 and \
                {scored[1][2].player1_id, scored[1][2].player2_id} != {best[2].player1_id, best[2].player2_id}:
            reasons.append("names match more than one upcoming match; check the selection")
        elif len(scored) > 1 and {scored[1][2].player1_id, scored[1][2].player2_id} == {best[2].player1_id, best[2].player2_id}:
            reasons.append("same pairing scheduled more than once; picked the earliest")
        p1_odds, p2_odds = (a.american, b.american)
        if best and best[1]:            # screenshot order is reversed relative to the official listing
            p1_odds, p2_odds = p2_odds, p1_odds
        if a.american is None or b.american is None:
            reasons.append("missing a price")
        else:
            ov = overround([american_to_decimal(a.american), american_to_decimal(b.american)])
            if not (0.0 <= ov <= 0.15):
                reasons.append(f"overround {ov:.1%} looks implausible (misread price?)")
        if min(a.conf, b.conf) < 50:
            reasons.append("low OCR confidence")
        m = best[2] if best else None
        out.append({
            "read": {"p1": a.name, "p1_american": a.american, "p2": b.name, "p2_american": b.american},
            "match_id": m.id if m else None,
            "match": ({"player1": m.player1.canonical_name, "player2": m.player2.canonical_name,
                       "scheduled_at": m.scheduled_at.isoformat()} if m else None),
            "p1_american": p1_odds, "p2_american": p2_odds, "name_score": round(best[0], 3) if best else None,
            "ocr_confidence": round(min(a.conf, b.conf), 1), "needs_review": bool(reasons), "reasons": reasons,
            "alternatives": [{"match_id": x[2].id, "label": f"{x[2].player1.canonical_name} vs {x[2].player2.canonical_name}",
                              "scheduled_at": x[2].scheduled_at.isoformat(), "score": round(x[0], 3)} for x in scored[:5]],
        })
    return out
