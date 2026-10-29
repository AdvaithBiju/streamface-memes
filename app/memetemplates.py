"""Meme template registry.

Built-in templates live in templates/templates.json (committed). Templates the
streamer uploads, imports from Imgflip or saves from the editor live in
templates/user/templates.json (git-ignored, since they may be copyrighted).
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_TEMPLATE_SIZE = 1600

_lock = threading.Lock()


class TemplateError(ValueError):
    pass


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:30].strip("-") or "meme"


def default_captions(width: int, height: int) -> list[dict]:
    """Classic TOP TEXT / BOTTOM TEXT boxes."""
    size = max(24, round(width / 12))
    box_h = round(height * 0.22)
    margin_x, margin_y = round(width * 0.04), round(height * 0.02)
    return [
        {"x": margin_x, "y": margin_y, "width": width - 2 * margin_x, "height": box_h,
         "size": size, "default": "TOP TEXT"},
        {"x": margin_x, "y": height - box_h - margin_y, "width": width - 2 * margin_x,
         "height": box_h, "size": size, "default": "BOTTOM TEXT"},
    ]


class TemplateStore:
    def __init__(self, builtin_dir: Path):
        self.builtin_dir = builtin_dir
        self.user_dir = builtin_dir / "user"
        self.user_json = self.user_dir / "templates.json"
        self.user_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("templates", [])

    def _write_user(self, templates: list[dict]) -> None:
        tmp = self.user_json.with_suffix(".tmp")
        tmp.write_text(json.dumps({"templates": templates}, indent=2), encoding="utf-8")
        tmp.replace(self.user_json)

    def all(self) -> list[dict]:
        builtin = [{**t, "source": "builtin"} for t in self._read(self.builtin_dir / "templates.json")]
        return builtin + self._read(self.user_json)

    def get(self, template_id: str) -> dict | None:
        return next((t for t in self.all() if t["id"] == template_id), None)

    def image_path(self, template: dict) -> Path:
        folder = self.builtin_dir if template["source"] == "builtin" else self.user_dir
        return folder / template["file"]

    def _unique_id(self, name: str) -> str:
        taken = {t["id"] for t in self.all()}
        base = slugify(name)
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def add_image(self, data, name: str, source: str, with_captions: bool = False,
                  **extra) -> dict:
        """Save an uploaded/downloaded image as a new user template."""
        try:
            img = Image.open(data)
            img = ImageOps.exif_transpose(img).convert("RGB")
        except (UnidentifiedImageError, OSError):
            raise TemplateError("That file isn't a readable image.")
        img.thumbnail((MAX_TEMPLATE_SIZE, MAX_TEMPLATE_SIZE), Image.LANCZOS)

        name = (name or "My meme").strip()[:60]
        with _lock:
            tid = self._unique_id(name)
            filename = f"{tid}.jpg"
            img.save(self.user_dir / filename, quality=92)
            template = {"id": tid, "name": name, "file": filename, "source": source,
                        "width": img.width, "height": img.height,
                        "face_slots": [],
                        "captions": default_captions(img.width, img.height) if with_captions else [],
                        **extra}
            self._write_user(self._read(self.user_json) + [template])
        return template

    def save_layout(self, base: dict, name: str, face_slots: list[dict], captions: list[dict]) -> dict:
        """Store an editor layout as a new template that chat can use later."""
        name = (name or base["name"]).strip()[:60]
        with _lock:
            tid = self._unique_id(name)
            src = self.image_path(base)
            filename = f"{tid}{src.suffix}"
            shutil.copyfile(src, self.user_dir / filename)
            template = {"id": tid, "name": name, "file": filename, "source": "layout",
                        "width": base["width"], "height": base["height"],
                        "face_slots": face_slots, "captions": captions}
            self._write_user(self._read(self.user_json) + [template])
        return template

    def delete(self, template_id: str) -> None:
        with _lock:
            templates = self._read(self.user_json)
            match = next((t for t in templates if t["id"] == template_id), None)
            if match is None:
                raise TemplateError("Only your own templates can be deleted.")
            self._write_user([t for t in templates if t["id"] != template_id])
            (self.user_dir / match["file"]).unlink(missing_ok=True)
