"""Meme editor: templates, uploads, Imgflip imports and rendering."""
import uuid

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_from_directory

from .. import imgflip
from ..db import get_db
from ..meme import MemeError, parse_layers, render_meme
from ..memetemplates import TemplateError

bp = Blueprint("editor", __name__)

MIN_OUT_WIDTH, MAX_OUT_WIDTH = 200, 2000


def _store():
    return current_app.extensions["template_store"]


def _template_json(t: dict) -> dict:
    return {**t, "url": f"/template-images/{t['id']}"}


def _face_paths() -> dict:
    rows = get_db().execute("SELECT id, filename FROM faces").fetchall()
    faces_dir = current_app.config["FACES_DIR"]
    return {r["id"]: faces_dir / r["filename"] for r in rows}


@bp.get("/editor")
def editor_page():
    return render_template("editor.html")


@bp.get("/api/templates")
def list_templates():
    return jsonify([_template_json(t) for t in _store().all()])


@bp.get("/template-images/<template_id>")
def template_image(template_id: str):
    t = _store().get(template_id)
    if t is None:
        abort(404)
    path = _store().image_path(t)
    return send_from_directory(path.parent, path.name)


@bp.post("/api/templates")
def upload_template():
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify(error="No image received."), 400
    try:
        t = _store().add_image(f.stream, request.form.get("name") or f.filename.rsplit(".", 1)[0],
                               source="upload")
    except TemplateError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(_template_json(t)), 201


@bp.post("/api/templates/from-layout")
def save_layout():
    body = request.get_json(silent=True) or {}
    base = _store().get(str(body.get("base_id", "")))
    if base is None:
        return jsonify(error="Unknown template."), 404
    try:
        layers = parse_layers(body.get("layers"), base["width"], base["height"])
    except MemeError as exc:
        return jsonify(error=str(exc)), 400

    def box(l):
        return {k: round(l[k]) for k in ("x", "y", "width", "height", "rotation")}

    face_slots = [box(l) for l in layers if l["type"] == "face"]
    captions = [{**box(l), "size": l["size"], "default": l["text"], "color": l["color"],
                 "stroke": l["stroke"], "outline": l["outline"]}
                for l in layers if l["type"] == "text"]
    if not face_slots:
        return jsonify(error="Add at least one face before saving as a template."), 400
    t = _store().save_layout(base, body.get("name", ""), face_slots, captions)
    return jsonify(_template_json(t)), 201


@bp.delete("/api/templates/<template_id>")
def delete_template(template_id: str):
    try:
        _store().delete(template_id)
    except TemplateError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True)


@bp.get("/api/imgflip")
def imgflip_list():
    try:
        return jsonify(imgflip.popular())
    except Exception as exc:
        current_app.logger.warning("Imgflip list failed: %s", exc)
        return jsonify(error="Couldn't reach Imgflip. Check your internet connection."), 502


@bp.post("/api/imgflip/import")
def imgflip_import():
    meme_id = str((request.get_json(silent=True) or {}).get("id", ""))
    existing = next((t for t in _store().all() if t.get("imgflip_id") == meme_id), None)
    if existing:
        return jsonify(_template_json(existing))
    try:
        meme, data = imgflip.download(meme_id)
        t = _store().add_image(data, meme["name"], source="imgflip",
                               with_captions=True, imgflip_id=meme_id)
    except (ValueError, TemplateError) as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        current_app.logger.warning("Imgflip import failed: %s", exc)
        return jsonify(error="Couldn't download that template."), 502
    return jsonify(_template_json(t)), 201


@bp.post("/api/render")
def render():
    body = request.get_json(silent=True) or {}
    t = _store().get(str(body.get("template_id", "")))
    if t is None:
        return jsonify(error="Pick a template first."), 404

    out_width = body.get("out_width")
    try:
        out_width = int(out_width) if out_width else None
        if out_width is not None:
            out_width = max(MIN_OUT_WIDTH, min(MAX_OUT_WIDTH, out_width))
        layers = parse_layers(body.get("layers"), t["width"], t["height"])
        image = render_meme(_store().image_path(t), layers, _face_paths(), out_width)
    except (MemeError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    filename = f"{uuid.uuid4().hex}.png"
    image.save(current_app.config["GENERATED_DIR"] / filename, optimize=True)
    caption = " / ".join(l["text"] for l in layers if l["type"] == "text")[:300]
    db = get_db()
    cur = db.execute(
        "INSERT INTO memes (filename, template_id, requested_by, caption, status) "
        "VALUES (?, ?, 'streamer', ?, 'created')", (filename, t["id"], caption))
    db.commit()
    return jsonify(id=cur.lastrowid, url=f"/generated/{filename}"), 201


@bp.get("/api/memes")
def list_memes():
    rows = get_db().execute("SELECT * FROM memes ORDER BY id DESC LIMIT 24").fetchall()
    return jsonify([{**dict(r), "url": f"/generated/{r['filename']}"} for r in rows])


@bp.get("/generated/<path:filename>")
def generated_file(filename: str):
    return send_from_directory(current_app.config["GENERATED_DIR"], filename)
