"""Who can do what once the app is on the internet.

- Viewers and mods sign in with Twitch on the Vercel sites and get a signed
  token, sent back as "Authorization: Bearer <token>".
- The streamer pages (/setup, /editor, /mod, /twitch, /demo) and their APIs
  need ADMIN_PASSWORD (browser password prompt) when it's set.
- The OBS overlay and finished meme images stay public so OBS can load them.

Without ADMIN_PASSWORD (running on your own PC) the streamer pages stay open,
as before.
"""
from __future__ import annotations

import hmac
import re

from flask import Response, current_app, g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

TOKEN_MAX_AGE = 7 * 24 * 3600

# Anyone: OBS overlay, images, site sign-in, health check.
PUBLIC = [
    re.compile(r"^/overlay$"),
    re.compile(r"^/static/"),
    re.compile(r"^/socket\.io/"),
    re.compile(r"^/generated/"),
    re.compile(r"^/template-images/"),
    re.compile(r"^/api/overlay/queue$"),
    re.compile(r"^/api/memes/\d+/shown$"),
    re.compile(r"^/auth/"),
    re.compile(r"^/healthz$"),
    re.compile(r"^/twitch/callback$"),   # Twitch sends the streamer back here; checked by state
]
PUBLIC_GET = [re.compile(r"^/api/voting$")]  # overlay's vote widget
# Signed-in viewers (users site).
VIEWER = [re.compile(r"^/api/viewer/"), re.compile(r"^/api/me$")]
# Mods (mod site) or the streamer.
MOD = [
    re.compile(r"^/api/queue$"),
    re.compile(r"^/api/memes/\d+/(approve|reject|replay)$"),
    re.compile(r"^/api/voting/(open|close|show)$"),
]


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt="streamface-site")


def make_token(login: str, user_id: str, role: str) -> str:
    return _serializer().dumps({"login": login, "user_id": user_id, "role": role})


def token_user() -> dict | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        return _serializer().loads(header[7:].strip(), max_age=TOKEN_MAX_AGE)
    except BadSignature:
        return None


def is_admin() -> bool:
    password = current_app.config["ADMIN_PASSWORD"]
    if not password:
        return True  # local use: no password set
    given = request.authorization.password if request.authorization else None
    return bool(given) and hmac.compare_digest(given.encode(), password.encode())


def _matches(rules, path: str) -> bool:
    return any(r.search(path) for r in rules)


def _deny_admin():
    return Response("StreamFace needs the admin password.", 401,
                    {"WWW-Authenticate": 'Basic realm="StreamFace streamer pages"'})


def check_access():
    """before_request hook: sets g.user for viewer/mod requests, or refuses."""
    g.user = None
    path = request.path
    if request.method == "OPTIONS" or _matches(PUBLIC, path):
        return None
    if request.method == "GET" and _matches(PUBLIC_GET, path):
        return None

    user = token_user()
    if _matches(VIEWER, path):
        if user is None:
            return jsonify(error="Please sign in with Twitch."), 401
        g.user = user
        return None
    if _matches(MOD, path):
        if user is not None and user.get("role") == "mod":
            g.user = user
            return None
        if is_admin():
            return None
        if user is not None:
            return jsonify(error="Only the streamer's mods can do that."), 403
        return jsonify(error="Please sign in with Twitch."), 401

    if not is_admin():
        return _deny_admin()
    return None


def mod_name(fallback: str = "mod") -> str:
    """Who to credit for a mod action: the signed-in mod, else the name typed on /mod."""
    if g.get("user"):
        return g.user["login"]
    body = request.get_json(silent=True) or {}
    return str(body.get("mod") or fallback).strip()[:40] or fallback
