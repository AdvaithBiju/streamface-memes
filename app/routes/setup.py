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
    rows = get_db().execute("SELECT * FROM faces WHERE owner IS NULL ORDER BY id").fetchall()
    return jsonify([_face_json(r) for r in rows])


def save_faces(files, source: str, owner: str | None, faces_per_photo: int = 1) -> tuple[list, list[str]]:
    """Cut the face(s) out of each photo and store them. Returns (new rows, error messages)."""
    db = get_db()
    detector = current_app.extensions["face_detector"]
    created, errors = [], []
    for f in files:
        try:
            paths = process_photo(detector, f.read(),
                                  current_app.config["FACES_DIR"] / f"{uuid.uuid4().hex}.png", faces_per_photo)
        except FaceError as exc:
            errors.append(f"{f.filename}: {exc}" if len(files) > 1 else str(exc))
            continue
        for path in paths:
            storage.save(path)
            cur = db.execute("INSERT INTO faces (filename, source, owner) VALUES (?, ?, ?)",
                             (path.name, source, owner))
            created.append(cur.lastrowid)
    db.commit()
    rows = db.execute(
        f"SELECT * FROM faces WHERE id IN ({','.join('?' * len(created))})", created
    ).fetchall() if created else []
    return rows, errors


def delete_face_row(row) -> None:
    db = get_db()
    db.execute("DELETE FROM faces WHERE id = ?", (row["id"],))
    db.commit()
    storage.delete(current_app.config["FACES_DIR"] / row["filename"])
    try:
        (current_app.config["FACES_DIR"] / row["filename"]).unlink(missing_ok=True)
    except OSError as exc:  # e.g. Windows file lock while the image is being served
        current_app.logger.warning("Could not delete %s: %s", row["filename"], exc)


@bp.post("/api/faces")
def upload_faces():
    files = [f for f in request.files.getlist("photos") if f and f.filename]
    if not files:
        return jsonify(error="No photo received."), 400

    source = "webcam" if request.form.get("source") == "webcam" else "upload"
    count = get_db().execute("SELECT COUNT(*) FROM faces WHERE owner IS NULL").fetchone()[0]
    max_faces = current_app.config["MAX_FACES"]
    if count + len(files) > max_faces:
        return jsonify(error=f"You can keep up to {max_faces} faces. "
                             f"Delete one first ({count} saved)."), 400

    rows, errors = save_faces(files, source, None)
    return jsonify(created=[_face_json(r) for r in rows], errors=errors), 201 if rows else 422


@bp.delete("/api/faces/<int:face_id>")
def delete_face(face_id: int):
    row = get_db().execute("SELECT id, filename FROM faces WHERE id = ? AND owner IS NULL",
                           (face_id,)).fetchone()
    if row is None:
        return jsonify(error="Not found."), 404
    delete_face_row(row)
    return jsonify(ok=True)


@bp.get("/faces/<path:filename>")
def face_file(filename: str):
    return send_from_directory(current_app.config["FACES_DIR"], filename)
