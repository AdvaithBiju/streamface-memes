"""Twitch integration.

- OAuth sign-in from the /twitch page (no copy-pasting tokens). Tokens are saved
  in data/twitch.json, which is git-ignored, and refreshed automatically.
- EventSub over WebSocket for chat messages (!meme, !memes) and channel point
  redemptions of the "Make a Meme" reward.
- Bot replies go out through the Helix "Send Chat Message" API, either as an
  optional separate bot account or as the streamer.
- Redemptions are marked fulfilled when a mod approves the meme, and canceled
  (points refunded) when it's refused or rejected.
"""
from __future__ import annotations

import json
import logging
import queue
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import simple_websocket

from . import storage
from .net import SSL_CONTEXT

log = logging.getLogger(__name__)

AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
HELIX = "https://api.twitch.tv/helix"
EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"

SCOPES = {
    # The streamer's account: read chat + redemptions, manage the meme reward.
    "broadcaster": ["user:read:chat", "user:write:chat",
                    "channel:read:redemptions", "channel:manage:redemptions",
                    "moderation:read"],  # lets the mod site check who your mods are
    # Optional bot account that posts the replies.
    "bot": ["user:write:chat"],
}

REWARD_PROMPT = "Meme name + caption, e.g. drake homework vs gaming (type !memes in chat for the list)"


class TwitchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class TokenStore:
    """Small JSON file holding tokens and the reward id."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get(self, key: str):
        with self._lock:
            return self._load().get(key)

    def set(self, key: str, value) -> None:
        with self._lock:
            data = self._load()
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            storage.save(self.path)


class Twitch:
    def __init__(self, app):
        self.app = app
        cfg = app.config
        self.client_id = cfg["TWITCH_CLIENT_ID"]
        self.client_secret = cfg["TWITCH_CLIENT_SECRET"]
        self.redirect_uri = cfg["TWITCH_REDIRECT_URI"]
        self.reward_title = cfg["TWITCH_REWARD_TITLE"]
        self.store = TokenStore(cfg["DATA_DIR"] / "twitch.json")

        self.status = "not connected"
        self.last_error: str | None = None
        self.channel_points = None  # True/False once we've tried to subscribe

        self._states: dict[str, tuple[str, float]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self._tasks: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, name="twitch-worker", daemon=True).start()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def account(self, role: str) -> dict | None:
        return self.store.get(role)

    def status_json(self) -> dict:
        def who(role):
            acc = self.account(role)
            return acc and {"login": acc["login"], "user_id": acc["user_id"]}
        return {
            "configured": self.configured,
            "redirect_uri": self.redirect_uri,
            "broadcaster": who("broadcaster"),
            "bot": who("bot"),
            "status": self.status,
            "last_error": self.last_error,
            "reward_id": self.store.get("reward_id"),
            "reward_title": self.reward_title,
            "channel_points": self.channel_points,
        }

    # ------------------------------------------------------------------ HTTP

    def _request(self, method: str, url: str, *, token: str | None = None, body=None,
                 form: dict | None = None, params: dict | None = None) -> dict:
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": "StreamFaceMemes"}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["Client-Id"] = self.client_id
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except ValueError:
                pass
            raise TwitchError(f"Twitch API {exc.code}: {detail}", exc.code) from None
        except urllib.error.URLError as exc:
            raise TwitchError(f"Can't reach Twitch: {exc.reason}") from None
        return json.loads(raw) if raw else {}

    def _helix(self, role: str, method: str, path: str, *, body=None, params=None) -> dict:
        for attempt in (1, 2):
            acc = self.account(role)
            if not acc:
                raise TwitchError(f"No {role} account connected.")
            try:
                return self._request(method, HELIX + path, token=acc["access_token"],
                                     body=body, params=params)
            except TwitchError as exc:
                if exc.status == 401 and attempt == 1:
                    self._refresh(role)
                    continue
                raise

    def _refresh(self, role: str) -> None:
        acc = self.account(role)
        tok = self._request("POST", TOKEN_URL, form={
            "grant_type": "refresh_token", "refresh_token": acc["refresh_token"],
            "client_id": self.client_id, "client_secret": self.client_secret,
        })
        acc.update(access_token=tok["access_token"],
                   refresh_token=tok.get("refresh_token", acc["refresh_token"]))
        self.store.set(role, acc)
        log.info("Refreshed Twitch token for %s", acc["login"])

    # ------------------------------------------------------------------ OAuth

    def login_url(self, role: str) -> str:
        if role not in SCOPES:
            raise TwitchError("Unknown account type.")
        now = time.time()
        self._states = {s: v for s, v in self._states.items() if now - v[1] < 600}
        state = secrets.token_urlsafe(24)
        self._states[state] = (role, now)
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES[role]),
            "state": state,
            "force_verify": "true",  # lets you pick a different account for the bot
        })

    def finish_login(self, code: str, state: str) -> tuple[str, str]:
        entry = self._states.pop(state, None)
        if entry is None or time.time() - entry[1] > 600:
            raise TwitchError("Sign-in expired or was tampered with. Please try again.")
        role = entry[0]
        tok = self._request("POST", TOKEN_URL, form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "code": code, "grant_type": "authorization_code", "redirect_uri": self.redirect_uri,
        })
        info = self._request("GET", VALIDATE_URL, token=tok["access_token"])
        missing = set(SCOPES[role]) - set(info.get("scopes", []))
        if missing:
            raise TwitchError(f"Twitch didn't grant: {', '.join(sorted(missing))}")
        self.store.set(role, {
            "access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
            "user_id": info["user_id"], "login": info["login"],
        })
        log.info("Connected Twitch %s account: %s", role, info["login"])
        if role == "broadcaster":
            self.restart()
        return role, info["login"]

    # ------------------------------------------------------------------ viewer / mod site sign-in

    def site_login_url(self, state: str, redirect_uri: str) -> str:
        """Sign-in for the Vercel sites: identity only, no permissions requested."""
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": "", "state": state,
        })

    def identify(self, code: str, redirect_uri: str) -> dict:
        """Swap a sign-in code for the viewer's Twitch login and user id."""
        tok = self._request("POST", TOKEN_URL, form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
        })
        info = self._request("GET", VALIDATE_URL, token=tok["access_token"])
        return {"login": info["login"], "user_id": info["user_id"]}

    def is_moderator(self, user_id: str) -> bool:
        """True for the streamer and the channel's Twitch moderators."""
        broadcaster = self.account("broadcaster")
        if not broadcaster:
            return False
        if user_id == broadcaster["user_id"]:
            return True
        try:
            res = self._helix("broadcaster", "GET", "/moderation/moderators",
                              params={"broadcaster_id": broadcaster["user_id"], "user_id": user_id})
        except TwitchError as exc:
            log.warning("Couldn't check moderators (reconnect the streamer on /twitch "
                        "to grant moderation:read): %s", exc)
            return False
        return bool(res.get("data"))

    def disconnect(self, role: str) -> None:
        if role == "broadcaster":
            self.stop()
            self.status = "not connected"
        self.store.set(role, None)

    # ------------------------------------------------------------------ outgoing (background)

    def _worker(self) -> None:
        while True:
            job = self._tasks.get()
            try:
                job()
            except Exception as exc:
                log.warning("Twitch task failed: %s", exc)
            time.sleep(0.35)  # stay well under chat rate limits

    def send_chat(self, message: str) -> None:
        """Queue a chat message (called by pipeline.say)."""
        self._tasks.put(lambda: self._send_chat_now(message))

    def _send_chat_now(self, message: str) -> None:
        broadcaster = self.account("broadcaster")
        if not broadcaster:
            return
        role = "bot" if self.account("bot") else "broadcaster"
        result = self._helix(role, "POST", "/chat/messages", body={
            "broadcaster_id": broadcaster["user_id"],
            "sender_id": self.account(role)["user_id"],
            "message": message[:500],
        })
        sent = (result.get("data") or [{}])[0]
        if sent and not sent.get("is_sent", True):
            reason = (sent.get("drop_reason") or {}).get("message", "dropped")
            log.warning("Twitch dropped chat message: %s", reason)

    def settle_redemption(self, reward_id: str, redemption_id: str, status: str) -> None:
        """FULFILLED or CANCELED (refunds points). Only works for rewards this app created."""
        def job():
            broadcaster = self.account("broadcaster")
            if not broadcaster:
                return
            self._helix("broadcaster", "PATCH", "/channel_points/custom_rewards/redemptions",
                        params={"broadcaster_id": broadcaster["user_id"], "reward_id": reward_id,
                                "id": redemption_id},
                        body={"status": status})
        self._tasks.put(job)

    def create_reward(self, cost: int) -> str:
        broadcaster = self.account("broadcaster")
        if not broadcaster:
            raise TwitchError("Connect your streamer account first.")
        result = self._helix("broadcaster", "POST", "/channel_points/custom_rewards",
                             params={"broadcaster_id": broadcaster["user_id"]}, body={
                                 "title": self.reward_title,
                                 "cost": max(1, int(cost)),
                                 "prompt": REWARD_PROMPT,
                                 "is_user_input_required": True,
                                 "is_global_cooldown_enabled": True,
                                 "global_cooldown_seconds": 15,
                             })
        reward_id = result["data"][0]["id"]
        self.store.set("reward_id", reward_id)
        return reward_id

    # ------------------------------------------------------------------ EventSub

    def start(self) -> None:
        if not self.configured:
            self.status = "not configured (add TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET to .env)"
            return
        if not self.account("broadcaster"):
            self.status = "not connected"
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="twitch-eventsub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def _connect(self, url: str):
        return simple_websocket.Client.connect(url, ssl_context=SSL_CONTEXT)

    def _run(self) -> None:
        backoff = 2
        while not self._stop.is_set():
            self.status = "connecting…"
            try:
                self._session()
                backoff = 2
            except Exception as exc:
                if self._stop.is_set():
                    break
                self.last_error = str(exc)
                log.warning("Twitch EventSub connection lost: %s", exc)
                if isinstance(exc, simple_websocket.ConnectionError) and "307" in str(exc):
                    self.last_error = ("Twitch's live connection was redirected, which usually means "
                                       "a network firewall (school/office Wi-Fi) is blocking it.")
            self.status = f"reconnecting in {backoff}s"
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 60)

    def _session(self) -> None:
        ws = self._connect(EVENTSUB_URL)
        self._ws = ws
        keepalive = 40
        subscribed = False
        try:
            while not self._stop.is_set():
                raw = ws.receive(timeout=keepalive)
                if raw is None:
                    raise TwitchError("No keepalive from Twitch; reconnecting.")
                msg = json.loads(raw)
                kind = msg["metadata"]["message_type"]
                payload = msg.get("payload", {})

                if kind == "session_welcome":
                    session = payload["session"]
                    keepalive = (session.get("keepalive_timeout_seconds") or 30) + 10
                    if not subscribed:
                        self._subscribe(session["id"])
                        subscribed = True
                    self.status = f"connected to #{self.account('broadcaster')['login']}"
                    self.last_error = None
                elif kind == "notification":
                    self.handle_notification(payload)
                elif kind == "session_reconnect":
                    # Open the new connection first; subscriptions carry over.
                    new_ws = self._connect(payload["session"]["reconnect_url"])
                    ws.close()
                    ws = self._ws = new_ws
                elif kind == "revocation":
                    sub = payload.get("subscription", {})
                    self.last_error = f"Twitch revoked {sub.get('type')}: {sub.get('status')}"
                    log.warning(self.last_error)
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _subscribe(self, session_id: str) -> None:
        uid = self.account("broadcaster")["user_id"]
        transport = {"method": "websocket", "session_id": session_id}
        self._helix("broadcaster", "POST", "/eventsub/subscriptions", body={
            "type": "channel.chat.message", "version": "1",
            "condition": {"broadcaster_user_id": uid, "user_id": uid}, "transport": transport,
        })
        try:
            self._helix("broadcaster", "POST", "/eventsub/subscriptions", body={
                "type": "channel.channel_points_custom_reward_redemption.add", "version": "1",
                "condition": {"broadcaster_user_id": uid}, "transport": transport,
            })
            self.channel_points = True
        except TwitchError as exc:
            # Channel points only exist for Affiliates/Partners; chat still works.
            self.channel_points = False
            log.info("Channel point events unavailable: %s", exc)

    # ------------------------------------------------------------------ incoming

    def _is_meme_reward(self, reward: dict) -> bool:
        reward_id = self.store.get("reward_id")
        if reward_id:
            return reward.get("id") == reward_id
        return (reward.get("title") or "").strip().lower() == self.reward_title.strip().lower()

    def handle_notification(self, payload: dict) -> None:
        from .commands import handle_chat, handle_redemption

        sub_type = payload["subscription"]["type"]
        event = payload["event"]
        with self.app.app_context():
            if sub_type == "channel.chat.message":
                bot = self.account("bot")
                if bot and event.get("chatter_user_id") == bot["user_id"]:
                    return  # ignore our own bot's messages
                user = event.get("chatter_user_name") or event.get("chatter_user_login") or "viewer"
                handle_chat(user, (event.get("message") or {}).get("text", ""), source="chat")
            elif sub_type == "channel.channel_points_custom_reward_redemption.add":
                reward = event.get("reward") or {}
                if not self._is_meme_reward(reward):
                    return
                handle_redemption(event.get("user_name") or event.get("user_login") or "viewer",
                                  event.get("user_input", ""), source="channel_points",
                                  redemption={"id": event["id"], "reward_id": reward.get("id")})
