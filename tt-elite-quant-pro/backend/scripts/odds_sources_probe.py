"""Which free odds APIs list table tennis? Keyless calls only."""
import json, requests
for name, url in (("odds-api.io sports", "https://api.odds-api.io/v3/sports"),
                  ("odds-api.io leagues table-tennis", "https://api.odds-api.io/v3/leagues?sport=table-tennis"),
                  ("the-odds-api sports (no key)", "https://api.the-odds-api.com/v4/sports")):
    try:
        r = requests.get(url, timeout=30)
        body = r.text
        hits = [ln for ln in body.replace("},", "},\n").splitlines() if "able" in ln and "enni" in ln][:15]
        print(f"== {name}: HTTP {r.status_code}, {len(body)} bytes")
        print("   table tennis entries:", hits if hits else "none")
        if "elite" in body.lower():
            print("   mentions Elite:", [ln for ln in body.replace("},", "},\n").splitlines() if "lite" in ln][:10])
    except Exception as e:  # noqa
        print(f"== {name}: {e.__class__.__name__}: {e}")
