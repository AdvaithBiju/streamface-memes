"""Mod dashboard, OBS overlay and demo mode."""
from flask import Blueprint, abort, current_app, jsonify, render_template, request

from .. import pipeline, voting
from ..auth import mod_name
from ..commands import handle_chat, handle_redemption
from ..db import get_db

bp = Blueprint("stream", __name__)


def _refused(exc):
    return jsonify(error=str(exc)), 409


# ------------------------------------------------------------------ pages

@bp.get("/mod")
def mod_page():
    return render_template("mod.html", demo=current_app.config["DEMO_MODE"],
                           vote_hours=current_app.config["VOTE_WINDOW_HOURS"])


@bp.get("/overlay")
def overlay_page():
    return render_template("overlay.html")


@bp.get("/demo")
def demo_page():
    if not current_app.config["DEMO_MODE"]:
        abort(404)
    return render_template("demo.html", cooldown=current_app.config["COOLDOWN_SECONDS"])


# ------------------------------------------------------------------ mod API

@bp.get("/api/queue")
def queue():
    db = get_db()
    pending = db.execute("SELECT * FROM memes WHERE status = 'pending' ORDER BY id").fetchall()
    history = db.execute(
        "SELECT * FROM memes WHERE status IN ('approved', 'shown', 'rejected') "
        "ORDER BY COALESCE(decided_at, created_at) DESC, id DESC LIMIT 30").fetchall()
    return jsonify(pending=[pipeline.meme_json(r) for r in pending],
                   history=[pipeline.meme_json(r) for r in history])


@bp.post("/api/memes/<int:meme_id>/approve")
def approve(meme_id: int):
    try:
        return jsonify(pipeline.approve(meme_id, mod_name()))
    except pipeline.RequestRefused as exc:
        return _refused(exc)


@bp.post("/api/memes/<int:meme_id>/reject")
def reject(meme_id: int):
    try:
        return jsonify(pipeline.reject(meme_id, mod_name()))
    except pipeline.RequestRefused as exc:
        return _refused(exc)


@bp.post("/api/memes/<int:meme_id>/replay")
def replay(meme_id: int):
    try:
        return jsonify(pipeline.replay(meme_id))
    except pipeline.RequestRefused as exc:
        return _refused(exc)


@bp.post("/api/memes/<int:meme_id>/send")
def send_to_stream(meme_id: int):
    """Editor memes go through mod approval like everything else."""
    try:
        return jsonify(pipeline.submit_for_approval(meme_id))
    except pipeline.RequestRefused as exc:
        return _refused(exc)


# ------------------------------------------------------------------ Meme of the Stream

@bp.get("/api/voting")
def voting_state():
    return jsonify(voting.state())


@bp.post("/api/voting/<action>")
def voting_action(action: str):
    actions = {"open": voting.open_round, "close": voting.close_round,
               "show": voting.show_leaderboard}
    if action not in actions:
        abort(404)
    try:
        actions[action]()
    except pipeline.RequestRefused as exc:
        return _refused(exc)
    return jsonify(voting.state())


# ------------------------------------------------------------------ overlay API

@bp.get("/api/overlay/queue")
def overlay_queue():
    """Approved memes the overlay hasn't shown yet (e.g. after OBS reloads)."""
    rows = get_db().execute("SELECT * FROM memes WHERE status = 'approved' ORDER BY decided_at, id").fetchall()
    return jsonify([pipeline.overlay_json(r) for r in rows])


@bp.post("/api/memes/<int:meme_id>/shown")
def shown(meme_id: int):
    pipeline.mark_shown(meme_id)
    return jsonify(ok=True)


# ------------------------------------------------------------------ demo API

def _demo_only():
    if not current_app.config["DEMO_MODE"]:
        abort(404)


@bp.post("/api/demo/chat")
def demo_chat():
    _demo_only()
    body = request.get_json(silent=True) or {}
    user = str(body.get("user") or "demo_viewer")[:40]
    handled = handle_chat(user, str(body.get("text", ""))[:500], source="demo")
    return jsonify(handled=handled)


@bp.post("/api/demo/redeem")
def demo_redeem():
    _demo_only()
    body = request.get_json(silent=True) or {}
    handle_redemption(str(body.get("user") or "demo_viewer")[:40], str(body.get("text", ""))[:500],
                      source="demo")
    return jsonify(ok=True)


@bp.post("/api/demo/reset-cooldowns")
def demo_reset_cooldowns():
    _demo_only()
    pipeline.reset_cooldowns()
    return jsonify(ok=True)
