"""Render a SYNTHETIC Hard Rock-style table-tennis list screenshot for tests (dark theme, Spread/Total/Money columns).
Not a real Hard Rock screenshot; replaced/augmented by real ones once provided."""
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def render(matches, path=None, width=1170):
    """matches: [((name1, spread1, total1, ml1), (name2, spread2, total2, ml2), time_text)]"""
    h = 260 + len(matches) * 330
    img = Image.new("RGB", (width, h), (18, 20, 26))
    d = ImageDraw.Draw(img)
    f, fb, fs = ImageFont.truetype(FONT, 40), ImageFont.truetype(FONT, 44), ImageFont.truetype(FONT, 32)
    d.text((40, 60), "Table Tennis  >  TT Elite Series", font=fb, fill=(235, 235, 235))
    d.text((620, 170), "Spread", font=fs, fill=(150, 150, 150))
    d.text((820, 170), "Total", font=fs, fill=(150, 150, 150))
    d.text((990, 170), "Money", font=fs, fill=(150, 150, 150))
    y = 240
    for p1, p2, when in matches:
        d.text((40, y), when, font=fs, fill=(150, 150, 150))
        for k, (name, spread, total, ml) in enumerate((p1, p2)):
            yy = y + 60 + k * 110
            d.text((40, yy + 20), name, font=f, fill=(240, 240, 240))
            for x, val in ((600, spread), (800, total), (980, ml)):
                d.rounded_rectangle((x, yy, x + 170, yy + 90), 14, fill=(40, 44, 54))
                d.text((x + 18, yy + 22), val, font=f, fill=(240, 240, 240))
        y += 330
    if path:
        img.save(path)
    return img


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) == 3:   # make_synthetic.py '<json [[p1, ml1, p2, ml2], ...]>' out.png  (used by Playwright)
        rows = json.loads(sys.argv[1])
        render([((a, "-1.5", "O 74.5", m1), (b, "+1.5", "U 74.5", m2), "Today") for a, m1, b, m2 in rows], sys.argv[2])
        sys.exit(0)
    render([(("Pawel Kurek", "-1.5", "O 74.5", "-150"), ("Grzegorz Wichowski", "+1.5", "U 74.5", "+120"), "Today 11:30 AM"),
            (("Jakub Kosowski", "-1.5", "O 76.5", "−185"), ("Tibor Spanik", "+1.5", "U 76.5", "+145"), "Today 11:55 AM")],
           "/tmp/claude-0/hr_synth.png")
