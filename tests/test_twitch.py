"""Twitch integration with the HTTP layer and WebSocket replaced by fakes."""
import json
import time
import urllib.parse

import pytest

from app import twitch as twmod


@pytest.fixture
def tw(app, monkeypatch):
    t = app.extensions["twitch"]
    t.client_id, t.client_secret = "cid", "secret"
    calls = []

    def fake_request(self, method, url, *, token=None, body=None, form=None, params=None):
        calls.append({"method": method, "path": url.replace(twmod.HELIX, ""), "token": token,
                      "body": body, "form": form, "params": params})
        if url == twmod.TOKEN_URL:
            return {"access_token": f"at{len(calls)}", "refresh_token": "rt"}
        if url == twmod.VALIDATE_URL:
            return {"user_id": "111", "login": "streamer", "scopes": twmod.SCOPES["broadcaster"]}
        if url.endswith("/channel_points/custom_rewards") and method == "POST":
            return {"data": [{"id": "rew-1"}]}
        return {"data": [{"is_sent": True}]}

    monkeypatch.setattr(twmod.Twitch, "_request", fake_request)
    monkeypatch.setattr(twmod.Twitch, "start", lambda self: None)
    t.calls = calls
    return t


def connect(client, tw):
    loc = client.get("/twitch/login/broadcaster").headers["Location"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))["state"]
    return client.get(f"/twitch/callback?code=abc&state={state}")


def drain(tw, wait=1.0):
    time.sleep(wait)  # outgoing calls run on the background worker
    out, tw.calls[:] = list(tw.calls), []
    return out


def notify(tw, sub_type, event):
    tw.handle_notification({"subscription": {"type": sub_type}, "event": event})


def test_oauth_sign_in(client, tw):
    loc = client.get("/twitch/login/broadcaster").headers["Location"]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))
    assert loc.startswith(twmod.AUTH_URL) and q["scope"] == " ".join(twmod.SCOPES["broadcaster"])
    assert "err=" in client.get("/twitch/callback?code=abc&state=bogus").headers["Location"]
    assert "msg=" in connect(client, tw).headers["Location"]
    assert tw.account("broadcaster")["login"] == "streamer"
    assert client.get("/api/twitch/status").json["broadcaster"]["login"] == "streamer"


def test_chat_command_replies_in_twitch_chat(client, tw):
    connect(client, tw)
    drain(tw, 0)
    notify(tw, "channel.chat.message",
           {"chatter_user_id": "9", "chatter_user_name": "Viewer", "message": {"text": "!meme testmeme hi"}})
    sent = [c["body"]["message"] for c in drain(tw) if c["path"] == "/chat/messages"]
    assert sent and "waiting for mod approval" in sent[0]


def test_redemption_fulfilled_or_refunded(client, tw):
    connect(client, tw)
    client.post("/api/twitch/reward", json={"cost": 100})
    drain(tw, 0)
    redemption = "channel.channel_points_custom_reward_redemption.add"
    notify(tw, redemption, {"id": "r1", "user_name": "A", "user_input": "testmeme hi",
                            "reward": {"id": "rew-1", "title": "Make a Meme"}})
    notify(tw, redemption, {"id": "r2", "user_name": "B", "user_input": "nosuchmeme",
                            "reward": {"id": "rew-1", "title": "Make a Meme"}})
    notify(tw, redemption, {"id": "r3", "user_name": "C", "user_input": "testmeme",
                            "reward": {"id": "other", "title": "Hydrate"}})  # not our reward
    calls = drain(tw)
    patches = [(c["params"]["id"], c["body"]["status"]) for c in calls if c["method"] == "PATCH"]
    assert patches == [("r2", "CANCELED")]
    [meme] = client.get("/api/queue").json["pending"]
    client.post(f"/api/memes/{meme['id']}/approve")
    patches = [(c["params"]["id"], c["body"]["status"]) for c in drain(tw) if c["method"] == "PATCH"]
    assert patches == [("r1", "FULFILLED")]


def test_token_refresh_on_401(client, tw, monkeypatch):
    connect(client, tw)
    original = twmod.Twitch._request
    state = {"failed": False}

    def flaky(self, method, url, **kw):
        if url.endswith("/chat/messages") and not state["failed"]:
            state["failed"] = True
            raise twmod.TwitchError("expired", 401)
        return original(self, method, url, **kw)

    monkeypatch.setattr(twmod.Twitch, "_request", flaky)
    drain(tw, 0)
    tw.send_chat("hello")
    calls = drain(tw)
    assert any(c["form"] and c["form"]["grant_type"] == "refresh_token" for c in calls)
    assert any(c["path"] == "/chat/messages" for c in calls)


def test_eventsub_session(app, tw, monkeypatch):
    tw.store.set("broadcaster", {"access_token": "a", "refresh_token": "r", "user_id": "1", "login": "s"})
    subs, handled = [], []
    monkeypatch.setattr(twmod.Twitch, "_helix", lambda self, role, method, path, **kw: subs.append(kw["body"]["type"]) or {})
    monkeypatch.setattr(tw, "handle_notification", lambda payload: handled.append(payload["subscription"]["type"]))

    def msg(kind, payload):
        return json.dumps({"metadata": {"message_type": kind}, "payload": payload})

    scripts = {
        twmod.EVENTSUB_URL: [msg("session_welcome", {"session": {"id": "S1", "keepalive_timeout_seconds": 10}}),
                             msg("notification", {"subscription": {"type": "channel.chat.message"}}),
                             msg("session_reconnect", {"session": {"reconnect_url": "wss://new"}})],
        "wss://new": [msg("session_welcome", {"session": {"id": "S2"}})],
    }

    class FakeWS:
        def __init__(self, url):
            self.script = list(scripts[url])

        def receive(self, timeout=None):
            return self.script.pop(0) if self.script else None

        def close(self):
            pass

    monkeypatch.setattr(twmod.Twitch, "_connect", lambda self, url: FakeWS(url))
    with pytest.raises(twmod.TwitchError, match="keepalive"):
        tw._session()
    assert subs == ["channel.chat.message", "channel.channel_points_custom_reward_redemption.add"]
    assert handled == ["channel.chat.message"]
