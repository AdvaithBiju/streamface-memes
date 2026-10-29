"""Draw 5 simple placeholder meme templates + templates.json.

Run from the project root:  python scripts/make_placeholder_templates.py
Swap in real template images later; just keep the face_slots/captions in sync.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.meme import load_font  # noqa: E402

OUT = ROOT / "templates"
SKIN_NECK = (222, 170, 140)


def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def body(d, slot, color, floor, shoulders=1.6):
    """Neck + shoulders under a face slot (x, y, w, h), cut off at y=floor."""
    x, y, w, h = slot
    cx, bottom = x + w / 2, y + h
    d.rectangle([cx - w * 0.16, bottom - h * 0.15, cx + w * 0.16, bottom + h * 0.12], fill=SKIN_NECK)
    half = w * shoulders / 2
    d.rounded_rectangle([cx - half, bottom + h * 0.05, cx + half, floor],
                        radius=int(w * 0.3), fill=color, corners=(True, True, False, False))


def slot(x, y, w=170, h=210):
    return {"x": x, "y": y, "width": w, "height": h, "rotation": 0}


def cap(x, y, w, h, size, default, **style):
    return {"x": x, "y": y, "width": w, "height": h, "size": size, "default": default, **style}


def label(d, xy, text, size=22, fill=(60, 60, 60)):
    d.text(xy, text, font=load_font(size), fill=fill, anchor="mm")


def drake():
    img = Image.new("RGB", (800, 800), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 400, 400], fill=(244, 162, 97))
    d.rectangle([0, 400, 400, 800], fill=(250, 200, 120))
    slots = [slot(110, 50, 180, 220), slot(110, 450, 180, 220)]
    for s, floor in zip(slots, [400, 800]):
        body(d, (s["x"], s["y"], s["width"], s["height"]), (200, 60, 40), floor)
    # "nope" hand up in the top panel, "yep" pointing hand in the bottom one
    d.rounded_rectangle([300, 190, 345, 330], radius=20, fill=(200, 60, 40))
    d.ellipse([292, 140, 352, 205], fill=SKIN_NECK)
    d.rounded_rectangle([290, 690, 380, 730], radius=20, fill=(200, 60, 40))
    d.ellipse([355, 688, 395, 728], fill=SKIN_NECK)
    d.line([(400, 0), (400, 800)], fill="black", width=4)
    d.line([(0, 400), (800, 400)], fill="black", width=4)
    return img, {
        "id": "drake", "name": "Nope / Yep",
        "face_slots": slots,
        "captions": [cap(420, 30, 360, 340, 56, "HOMEWORK", color="#111111", stroke="#ffffff", outline=0),
                     cap(420, 430, 360, 340, 56, "GAMING", color="#111111", stroke="#ffffff", outline=0)],
    }


def brain():
    img = Image.new("RGB", (800, 1000), "white")
    d = ImageDraw.Draw(img)
    glows = [((70, 70, 90), (40, 40, 50)), ((60, 90, 160), (30, 50, 100)),
             ((120, 80, 220), (60, 30, 140)), ((255, 240, 160), (250, 140, 255))]
    slots, captions = [], []
    defaults = ["using a meme", "using your own face", "putting it on stream", "chat makes them for you"]
    for i, (top, bottom) in enumerate(glows):
        y = i * 250
        img.paste(gradient(400, 250, top, bottom), (400, y))
        s = slot(532, y + 15, 136, 165)
        body(d, (s["x"], s["y"], s["width"], s["height"]), (30, 30, 40), y + 250)
        for r in range(i * 2):  # more "glow" rings as the brain expands
            d.ellipse([600 - 110 - r * 12, y + 120 - 110 - r * 6, 600 + 110 + r * 12, y + 120 + 110 + r * 6],
                      outline=(255, 255, 255), width=1)
        slots.append(s)
        captions.append(cap(20, y + 20, 360, 210, 44, defaults[i], color="#111111", stroke="#ffffff", outline=0))
        d.line([(0, y), (800, y)], fill="black", width=3)
    d.line([(400, 0), (400, 1000)], fill="black", width=3)
    return img, {"id": "brain", "name": "Expanding Brain", "face_slots": slots, "captions": captions}


def fine():
    img = gradient(900, 520, (230, 190, 90), (200, 150, 60))
    d = ImageDraw.Draw(img)
    for x in range(-40, 900, 90):  # flames
        d.polygon([(x, 520), (x + 45, 330 + (x * 7) % 90), (x + 90, 520)], fill=(240, 110, 30))
        d.polygon([(x + 20, 520), (x + 45, 410 + (x * 3) % 50), (x + 70, 520)], fill=(255, 200, 60))
    s = slot(360, 110, 170, 210)
    body(d, (s["x"], s["y"], s["width"], s["height"]), (90, 140, 90), 520)
    d.rectangle([250, 430, 650, 450], fill=(120, 80, 50))       # table
    d.rounded_rectangle([560, 380, 610, 432], radius=8, fill="white")  # mug
    d.arc([598, 392, 628, 420], -90, 90, fill="white", width=6)
    return img, {"id": "fine", "name": "This Is Fine",
                 "face_slots": [s], "captions": [cap(40, 15, 820, 90, 64, "THIS IS FINE")]}


def changemymind():
    img = gradient(900, 560, (140, 200, 240), (200, 230, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 380, 900, 560], fill=(110, 170, 90))
    s = slot(130, 80, 170, 210)
    body(d, (s["x"], s["y"], s["width"], s["height"]), (60, 90, 140), 560)
    d.rectangle([60, 360, 860, 390], fill=(150, 110, 70))   # table top
    d.rectangle([90, 390, 110, 540], fill=(120, 85, 55))
    d.rectangle([810, 390, 830, 540], fill=(120, 85, 55))
    d.polygon([(430, 360), (820, 360), (800, 180), (450, 180)], fill="white", outline=(80, 80, 80))
    return img, {"id": "changemymind", "name": "Change My Mind", "face_slots": [s],
                 "captions": [cap(465, 190, 320, 160, 40, "chat is always right. change my mind",
                                  color="#111111", stroke="#ffffff", outline=0)]}


def distracted():
    img = gradient(900, 560, (170, 210, 235), (225, 225, 215))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 470, 900, 560], fill=(150, 150, 150))
    slots = [slot(70, 90), slot(370, 90), slot(660, 90)]
    for s, color in zip(slots, [(220, 60, 80), (60, 110, 200), (90, 160, 90)]):
        body(d, (s["x"], s["y"], s["width"], s["height"]), color, 560)
    captions = [cap(40, 330, 230, 110, 40, "NEW GAME"), cap(340, 330, 230, 110, 40, "ME"),
                cap(630, 330, 230, 110, 40, "MY BACKLOG")]
    return img, {"id": "distracted", "name": "Distracted", "face_slots": slots, "captions": captions}


def main():
    templates = []
    for make in (drake, brain, fine, changemymind, distracted):
        img, meta = make()
        filename = f"{meta['id']}.png"
        img.save(OUT / filename, optimize=True)
        templates.append({"id": meta["id"], "name": meta["name"], "file": filename,
                          "width": img.width, "height": img.height,
                          "face_slots": meta["face_slots"], "captions": meta["captions"]})
        print("wrote", filename)
    (OUT / "templates.json").write_text(json.dumps({"templates": templates}, indent=2), encoding="utf-8")
    print("wrote templates.json")


if __name__ == "__main__":
    main()
