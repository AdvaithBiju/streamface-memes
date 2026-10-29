"""Meme renderer: template image + face/text layers -> finished PNG.

Layer coordinates are in template-image pixels. (x, y) is the top-left of the
unrotated box; rotation is degrees clockwise around the box centre. The editor
canvas (static/js/editor.js) uses the exact same model and wrapping rules so
the preview matches the render.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

MAX_LAYERS = 20
MAX_TEXT = 200
LINE_HEIGHT = 1.1
MIN_FONT = 10
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

FONT_CANDIDATES = [
    "impact.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    "/Library/Fonts/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


class MemeError(ValueError):
    pass


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    for candidate in FONT_CANDIDATES:
        try:
            ImageFont.truetype(candidate, 10)
            return candidate
        except OSError:
            continue
    return None


@lru_cache(maxsize=64)
def load_font(size: int) -> ImageFont.FreeTypeFont:
    path = _font_path()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


# ---------------------------------------------------------------- validation

def _num(layer: dict, key: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(layer.get(key, default))
    except (TypeError, ValueError):
        raise MemeError(f"'{key}' must be a number.")
    if value != value:  # NaN
        raise MemeError(f"'{key}' must be a number.")
    return max(lo, min(hi, value))


def _color(layer: dict, key: str, default: str) -> str:
    value = layer.get(key, default)
    if not isinstance(value, str) or not COLOR_RE.match(value):
        raise MemeError(f"'{key}' must be a #rrggbb colour.")
    return value


def parse_layers(raw, tpl_w: int, tpl_h: int) -> list[dict]:
    """Validate and normalise layers coming from the browser."""
    if not isinstance(raw, list):
        raise MemeError("'layers' must be a list.")
    if len(raw) > MAX_LAYERS:
        raise MemeError(f"Too many layers (max {MAX_LAYERS}).")

    span = max(tpl_w, tpl_h)
    layers = []
    for item in raw:
        if not isinstance(item, dict):
            raise MemeError("Each layer must be an object.")
        box = {
            "x": _num(item, "x", 0, -span, span * 2),
            "y": _num(item, "y", 0, -span, span * 2),
            "width": _num(item, "width", 100, 4, span * 3),
            "height": _num(item, "height", 100, 4, span * 3),
            "rotation": _num(item, "rotation", 0, -360, 360),
        }
        if item.get("type") == "face":
            try:
                face_id = int(item.get("face_id"))
            except (TypeError, ValueError):
                raise MemeError("Face layer needs a face_id.")
            layers.append({**box, "type": "face", "face_id": face_id,
                           "flip": bool(item.get("flip")),
                           "color_match": bool(item.get("color_match", True))})
        elif item.get("type") == "text":
            text = str(item.get("text", ""))[:MAX_TEXT]
            layers.append({**box, "type": "text", "text": text,
                           "size": int(_num(item, "size", 48, MIN_FONT, 400)),
                           "outline": int(_num(item, "outline", 4, 0, 30)),
                           "color": _color(item, "color", "#ffffff"),
                           "stroke": _color(item, "stroke", "#000000"),
                           "uppercase": bool(item.get("uppercase", True))})
        else:
            raise MemeError("Layer type must be 'face' or 'text'.")
    return layers


# ----------------------------------------------------------------- rendering

def _paste_centered(base: Image.Image, layer_img: Image.Image, layer: dict) -> None:
    if layer["rotation"]:
        # Pillow rotates counter-clockwise; our model is clockwise like canvas.
        layer_img = layer_img.rotate(-layer["rotation"], resample=Image.BICUBIC, expand=True)
    cx = layer["x"] + layer["width"] / 2
    cy = layer["y"] + layer["height"] / 2
    pos = (round(cx - layer_img.width / 2), round(cy - layer_img.height / 2))
    # alpha_composite can't take negative offsets, so go via a full-size layer.
    tmp = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tmp.paste(layer_img, pos, layer_img)
    base.alpha_composite(tmp)


def color_match(face: Image.Image, region: Image.Image, strength: float = 0.2) -> Image.Image:
    """Nudge the face's average colour slightly toward the area it sits on."""
    f = np.asarray(face, dtype=np.float32).copy()
    alpha = f[..., 3:4] / 255.0
    if alpha.sum() < 1 or region.width == 0 or region.height == 0:
        return face
    face_mean = (f[..., :3] * alpha).sum(axis=(0, 1)) / alpha.sum()
    region_mean = np.asarray(region.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0)
    f[..., :3] = np.clip(f[..., :3] + (region_mean - face_mean) * strength, 0, 255)
    return Image.fromarray(f.astype(np.uint8), "RGBA")


def _render_face(base: Image.Image, layer: dict, face_path: Path) -> None:
    w, h = max(1, round(layer["width"])), max(1, round(layer["height"]))
    face = Image.open(face_path).convert("RGBA")
    if layer["flip"]:
        face = ImageOps.mirror(face)
    face = face.resize((w, h), Image.LANCZOS)
    if layer["color_match"]:
        x0, y0 = max(0, round(layer["x"])), max(0, round(layer["y"]))
        x1, y1 = min(base.width, x0 + w), min(base.height, y0 + h)
        if x1 > x0 and y1 > y0:
            face = color_match(face, base.crop((x0, y0, x1, y1)))
    _paste_centered(base, face, layer)


def wrap_text(text: str, font, max_width: float) -> list[str]:
    """Greedy word wrap; mirrors wrap() in editor.js."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            test = f"{line} {word}" if line else word
            if line and font.getlength(test) > max_width:
                lines.append(line)
                line = word
            else:
                line = test
        lines.append(line)
    return lines


def fit_text(text: str, width: float, height: float, size: int):
    """Shrink the font until the wrapped text fits the box height."""
    while True:
        font = load_font(size)
        lines = wrap_text(text, font, width)
        if len(lines) * size * LINE_HEIGHT <= height or size <= MIN_FONT:
            return font, size, lines
        size -= 2


def _render_text(base: Image.Image, layer: dict) -> None:
    text = layer["text"].upper() if layer["uppercase"] else layer["text"]
    if not text.strip():
        return
    w, h = round(layer["width"]), round(layer["height"])
    font, size, lines = fit_text(text, w, h, layer["size"])
    pad = layer["outline"] + 4
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line_h = size * LINE_HEIGHT
    top = pad + (h - len(lines) * line_h) / 2
    for i, line in enumerate(lines):
        draw.text((pad + w / 2, top + line_h * (i + 0.5)), line, font=font, anchor="mm",
                  fill=layer["color"], stroke_width=layer["outline"], stroke_fill=layer["stroke"])
    # The padded image shares the box's centre, so centred pasting still lines up.
    _paste_centered(base, img, layer)


def render_meme(template_path: Path, layers: list[dict], face_paths: dict[int, Path],
                out_width: int | None = None) -> Image.Image:
    base = Image.open(template_path).convert("RGBA")
    for layer in layers:
        if layer["type"] == "face":
            path = face_paths.get(layer["face_id"])
            if path is None:
                raise MemeError(f"Face #{layer['face_id']} doesn't exist.")
            _render_face(base, layer, path)
        else:
            _render_text(base, layer)
    if out_width and out_width != base.width:
        out_h = round(base.height * out_width / base.width)
        base = base.resize((out_width, out_h), Image.LANCZOS)
    return base.convert("RGB")


def layers_from_template(template: dict, face_id: int | None, captions: list[str] | None = None) -> list[dict]:
    """Turn a template's face slots + caption boxes into render layers."""
    layers = []
    if face_id is not None:
        for slot in template.get("face_slots", []):
            layers.append({"type": "face", "face_id": face_id, "flip": False,
                           "color_match": True, "rotation": 0, **slot})
    for i, cap in enumerate(template.get("captions", [])):
        text = captions[i] if captions and i < len(captions) else cap.get("default", "")
        layers.append({"type": "text", "text": text, "rotation": 0, "uppercase": True,
                       "color": "#ffffff", "stroke": "#000000",
                       "outline": max(2, round(cap.get("size", 48) / 12)), **cap})
    return parse_layers(layers, template["width"], template["height"])
