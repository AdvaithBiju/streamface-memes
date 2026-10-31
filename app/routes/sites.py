"""Backend for the two Vercel sites: Twitch sign-in, and the viewer meme API.

The mod site uses the existing mod API (/api/queue, approve, reject, voting);
app/auth.py lets signed-in mods through.
"""
import secrets
import urllib.parse

from flask import Blueprint, current_app, g, jsonify, redirect, request, session

from .. import pipeline
from ..auth import make_token
from ..db import get_db
from ..twitch import TwitchError

bp = Blueprint("sites", __name__)

SITES = {"user": "USER_SITE_URL", "mod": "MOD_SITE_URL"}


def _site_url(site: str) -> str:
    return current_app.config.get(SITES.get(site, ""), "")


def _redirect_uri() -> str:
    return current_app.config["PUBLIC_URL"] + "/auth/callback"


def _back_to_site(site: str, **fragment) -> object:
    return redirect(_site_url(site) + "/#" + urllib.parse.urlencode(fragment))


@bp.get("/healthz")
def healthz():
    return jsonify(ok=True)


# ------------------------------------------------------------------ sign-in

@bp.get("/auth/login")
def login():
    site = request.args.get("site", "")
    if not _site_url(site):
        return f"The {site or '?'} site isn't set up (set {SITES.get(site, 'USER_SITE_URL')}).", 400
    tw = current_app.extensions["twitch"]
    if not tw.configured:
        return "Twitch isn't set up on the server yet.", 503
    state = secrets.token_urlsafe(24)
    session["auth"] = {"state": state, "site": site}
    return redirect(tw.site_login_url(state, _redirect_uri()))


@bp.get("/auth/callback")
def callback():
    pending = session.pop("auth", None) or {}
    site = pending.get("site", "")
    if not _site_url(site) or not secrets.compare_digest(pending.get("state", ""),
                                                         request.args.get("state", "")):
        return "Sign-in expired. Go back to the site and try again.", 400
    if request.args.get("error"):
        return _back_to_site(site, error="Sign-in was cancelled.")

    tw = current_app.extensions["twitch"]
    try:
        who = tw.identify(request.args.get("code", ""), _redirect_uri())
    except TwitchError as exc:
        current_app.logger.warning("Site sign-in failed: %s", exc)
        return _back_to_site(site, error="Twitch sign-in failed. Please try again.")

    role = "viewer"
    if site == "mod":
        if who["login"].lower() not in current_app.config["MOD_LOGINS"] and not tw.is_moderator(who["user_id"]):
            return _back_to_site(site, error=f"{who['login']} isn't a mod of this channel.")
        role = "mod"
    return _back_to_site(site, token=make_token(who["login"], who["user_id"], role))


@bp.get("/api/me")
def me():
    cfg = current_app.config
    return jsonify(login=g.user["login"], role=g.user["role"],
                   caption_max=cfg["CAPTION_MAX_LENGTH"], cooldown_seconds=cfg["COOLDOWN_SECONDS"])


# ------------------------------------------------------------------ viewer API

@bp.get("/api/viewer/templates")
def viewer_templates():
    """Templates with a face slot, as viewers' memes always include the streamer."""
    keep = ("id", "name", "width", "height", "face_slots", "captions")
    return jsonify([{**{k: t.get(k) for k in keep}, "url": f"/template-images/{t['id']}"}
                    for t in current_app.extensions["template_store"].all() if t.get("face_slots")])


@bp.post("/api/viewer/memes")
def viewer_submit():
    body = request.get_json(silent=True) or {}
    login = g.user["login"]
    try:
        meme = pipeline.submit_web_meme(login, body.get("template_id", ""), body.get("captions"))
    except pipeline.RequestRefused as exc:
        return jsonify(error=str(exc).removeprefix(f"@{login} ")), 409
    return jsonify(meme), 201


@bp.get("/api/viewer/memes")
def viewer_memes():
    rows = get_db().execute(
        "SELECT * FROM memes WHERE lower(requested_by) = ? ORDER BY id DESC LIMIT 12",
        (g.user["login"].lower(),)).fetchall()
    return jsonify([pipeline.meme_json(r) for r in rows])
