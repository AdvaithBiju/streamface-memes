"""Streamer setup: upload / capture face photos and manage cutouts."""
import uuid

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory

from .. import storage
from ..db import get_db
from ..face import FaceError, process_photo

bp = Blueprint("setup", __name__)


def _face_json(row) -> dict:
    return {
        "id": row["id"],
        "url": f"/faces/{row['filename']}",
        "source": row["source"],
        "created_at": row["created_at"],
    }


@bp.get("/setup")
def setup_page():
    return render_template(
        "setup.html",
        max_faces=current_app.config["MAX_FACES"],
        backend=current_app.extensions["face_detector"].backend,
    )


@bp.get("/api/faces")
def list_faces():
    rows = get_db().execute("SELECT * FROM faces ORDER BY id").fetchall()
    return jsonify([_face_json(r) for r in rows])


@bp.post("/api/faces")
def upload_faces():
    files = [f for f in request.files.getlist("photos") if f and f.filename]
    if not files:
        return jsonify(error="No photo received."), 400

    source = "webcam" if request.form.get("source") == "webcam" else "upload"
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    max_faces = current_app.config["MAX_FACES"]
    if count + len(files) > max_faces:
        return jsonify(error=f"You can keep up to {max_faces} faces. "
                             f"Delete one first ({count} saved)."), 400

    detector = current_app.extensions["face_detector"]
    created, errors = [], []
    for f in files:
        filename = f"{uuid.uuid4().hex}.png"
        try:
            process_photo(detector, f.read(), current_app.config["FACES_DIR"] / filename)
            storage.save(current_app.config["FACES_DIR"] / filename)
        except FaceError as exc:
            errors.append(f"{f.filename}: {exc}")
            continue
        cur = db.execute("INSERT INTO faces (filename, source) VALUES (?, ?)", (filename, source))
        created.append(cur.lastrowid)
    db.commit()

    rows = db.execute(
        f"SELECT * FROM faces WHERE id IN ({','.join('?' * len(created))})", created
    ).fetchall() if created else []
    status = 201 if created else 422
    return jsonify(created=[_face_json(r) for r in rows], errors=errors), status


@bp.delete("/api/faces/<int:face_id>")
def delete_face(face_id: int):
    db = get_db()
    row = db.execute("SELECT filename FROM faces WHERE id = ?", (face_id,)).fetchone()
    if row is None:
        return jsonify(error="Not found."), 404
    db.execute("DELETE FROM faces WHERE id = ?", (face_id,))
    db.commit()
    storage.delete(current_app.config["FACES_DIR"] / row["filename"])
    try:
        (current_app.config["FACES_DIR"] / row["filename"]).unlink(missing_ok=True)
    except OSError as exc:  # e.g. Windows file lock while the image is being served
        current_app.logger.warning("Could not delete %s: %s", row["filename"], exc)
    return jsonify(ok=True)


@bp.get("/faces/<path:filename>")
def face_file(filename: str):
    return send_from_directory(current_app.config["FACES_DIR"], filename)
