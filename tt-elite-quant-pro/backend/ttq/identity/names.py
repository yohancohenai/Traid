"""Polish-aware player name normalisation and conservative identity matching.

Policy
- Exact normalised match (or known source player id) -> link automatically.
- Anything fuzzy -> IdentityReview queue. Ambiguous identities are NEVER merged automatically.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

POLISH_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N", "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
})


def strip_diacritics(s: str) -> str:
    s = s.translate(POLISH_MAP)  # Ł/ł do not decompose under NFKD, map explicitly
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(raw: str) -> str:
    """'Kowalski, Łukasz' / 'ŁUKASZ  KOWALSKI' / 'Lukasz Kowalski' -> 'kowalski lukasz' (sorted tokens)."""
    s = strip_diacritics(raw).lower()
    s = re.sub(r"\(.*?\)", " ", s)          # drop "(POL)" etc.
    s = re.sub(r"[^a-z\s\-]", " ", s)
    s = s.replace("-", " ")
    tokens = [t for t in s.split() if t]
    return " ".join(sorted(tokens))


def surname_initial_key(raw: str) -> str | None:
    """'Kowalski L.' style abbreviations -> ('kowalski', 'l'). Returns None if not abbreviated."""
    s = strip_diacritics(raw).lower().replace(".", " ")
    toks = [t for t in re.split(r"[\s,]+", s) if t]
    singles = [t for t in toks if len(t) == 1]
    longs = [t for t in toks if len(t) > 1]
    if len(singles) == 1 and len(longs) == 1:
        return f"{longs[0]}|{singles[0]}"
    return None


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def find_candidates(raw: str, players: list[tuple[int, str]], threshold: float = 0.78) -> list[dict]:
    """Fuzzy candidates for manual review. players: [(id, canonical_name)]."""
    out = []
    abbr = surname_initial_key(raw)
    for pid, name in players:
        score = similarity(raw, name)
        if abbr:
            n = normalize_name(name).split()
            sur, ini = abbr.split("|")
            if sur in n and any(t.startswith(ini) for t in n if t != sur):
                score = max(score, 0.9)
        if score >= threshold:
            out.append({"player_id": pid, "name": name, "score": round(score, 3)})
    return sorted(out, key=lambda c: -c["score"])
