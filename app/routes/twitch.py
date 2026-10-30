"""/twitch: connect accounts, create the channel point reward, check status."""
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

from ..twitch import TwitchError

bp = Blueprint("twitch", __name__)


def _twitch():
    return current_app.extensions["twitch"]


@bp.get("/twitch")
def twitch_page():
    return render_template("twitch.html", reward_cost=current_app.config["TWITCH_REWARD_COST"],
                           message=request.args.get("msg", ""), error=request.args.get("err", ""))


@bp.get("/api/twitch/status")
def status():
    return jsonify(_twitch().status_json())


@bp.get("/twitch/login/<role>")
def login(role: str):
    tw = _twitch()
    if not tw.configured:
        return redirect(url_for("twitch.twitch_page", err="Add TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET to .env, then restart the app."))
    try:
        return redirect(tw.login_url(role))
    except TwitchError as exc:
        return redirect(url_for("twitch.twitch_page", err=str(exc)))


@bp.get("/twitch/callback")
def callback():
    if request.args.get("error"):
        return redirect(url_for("twitch.twitch_page",
                                err=request.args.get("error_description") or "Sign-in was cancelled."))
    try:
        role, login_name = _twitch().finish_login(request.args.get("code", ""), request.args.get("state", ""))
    except TwitchError as exc:
        return redirect(url_for("twitch.twitch_page", err=str(exc)))
    label = "Streamer" if role == "broadcaster" else "Bot"
    return redirect(url_for("twitch.twitch_page", msg=f"{label} account connected: {login_name}"))


@bp.post("/api/twitch/disconnect/<role>")
def disconnect(role: str):
    if role not in ("broadcaster", "bot"):
        return jsonify(error="Unknown account."), 400
    _twitch().disconnect(role)
    return jsonify(ok=True)


@bp.post("/api/twitch/reconnect")
def reconnect():
    _twitch().restart()
    return jsonify(ok=True)


@bp.post("/api/twitch/reward")
def create_reward():
    cost = (request.get_json(silent=True) or {}).get("cost") or current_app.config["TWITCH_REWARD_COST"]
    try:
        reward_id = _twitch().create_reward(int(cost))
    except (TwitchError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(reward_id=reward_id)


@bp.post("/api/twitch/test")
def test_message():
    tw = _twitch()
    if not tw.account("broadcaster"):
        return jsonify(error="Connect your streamer account first."), 400
    tw.send_chat("StreamFace Memes is connected! Type !memes to see the meme list.")
    return jsonify(ok=True)
