"""The online setup: password-protected streamer pages, and the viewer and mod sites' APIs."""
import base64
import urllib.parse

import pytest

from app import twitch as twmod
from app.auth import make_token
from conftest import MOD_SITE, USER_SITE


def token(app, login, role):
    with app.app_context():
        return {"Authorization": "Bearer " + make_token(login, "id-" + login, role)}


ADMIN = {"Authorization": "Basic " + base64.b64encode(b"streamer:pw").decode()}


@pytest.fixture
def online(app):
    app.config["ADMIN_PASSWORD"] = "pw"
    return app


def test_streamer_pages_need_the_password(client, online):
    for path in ("/setup", "/editor", "/mod", "/twitch", "/api/faces", "/api/twitch/status"):
        res = client.get(path)
        assert res.status_code == 401 and "Basic" in res.headers["WWW-Authenticate"], path
    assert client.get("/setup", headers=ADMIN).status_code == 200
    assert client.get("/setup", headers={"Authorization": "Basic " + base64.b64encode(b"x:nope").decode()}).status_code == 401
    # OBS needs these without a password.
    assert client.get("/overlay").status_code == 200
    assert client.get("/api/overlay/queue").status_code == 200
    assert client.get("/api/voting").status_code == 200
    assert client.post("/api/voting/open").status_code == 401


def test_viewer_makes_a_meme_on_the_site(client, app):
    assert client.post("/api/viewer/memes", json={}).status_code == 401
    alice = token(app, "alice", "viewer")

    templates = client.get("/api/viewer/templates", headers=alice).json
    assert [t["id"] for t in templates] == ["testmeme"] and len(templates[0]["captions"]) == 2

    res = client.post("/api/viewer/memes", headers=alice,
                      json={"template_id": "testmeme", "captions": ["me at 3am", "still coding"]})
    assert res.status_code == 201
    meme = res.json
    assert meme["status"] == "pending" and meme["source"] == "web" and meme["requested_by"] == "alice"
    assert client.get("/api/queue").json["pending"][0]["id"] == meme["id"]

    again = client.post("/api/viewer/memes", headers=alice,
                        json={"template_id": "testmeme", "captions": ["again"]})
    assert again.status_code == 409 and again.json["error"].startswith("slow down")
    assert [m["id"] for m in client.get("/api/viewer/memes", headers=alice).json] == [meme["id"]]

    bob = token(app, "bob", "viewer")
    for captions, error in ((["hi @someone"], "@mentions"), (["", ""], "at least one"),
                            (["a", "b", "c"], "caption boxes")):
        res = client.post("/api/viewer/memes", headers=bob, json={"template_id": "testmeme", "captions": captions})
        assert res.status_code == 409 and error in res.json["error"], captions


def test_only_mods_can_moderate(client, online):
    meme = client.post("/api/viewer/memes", headers=token(online, "alice", "viewer"),
                       json={"template_id": "testmeme", "captions": ["hello"]}).json
    viewer = token(online, "alice", "viewer")
    assert client.post(f"/api/memes/{meme['id']}/approve", headers=viewer).status_code == 403
    assert client.get("/api/queue", headers=viewer).status_code == 403

    mod = token(online, "modkate", "mod")
    assert client.get("/api/queue", headers=mod).json["pending"][0]["id"] == meme["id"]
    approved = client.post(f"/api/memes/{meme['id']}/approve", headers=mod, json={"mod": "spoofed"}).json
    assert approved["status"] == "approved" and approved["decided_by"] == "modkate"
    assert client.post("/api/voting/open", headers=mod).json["open"] is True
    # A mod token doesn't unlock the streamer pages.
    assert client.get("/setup", headers=mod).status_code == 401


def test_forged_token_is_refused(client, app):
    good = token(app, "alice", "viewer")["Authorization"]
    bad = {"Authorization": good[:-3] + ("aaa" if not good.endswith("aaa") else "bbb")}
    assert client.get("/api/me", headers=bad).status_code == 401


@pytest.fixture
def tw(app, monkeypatch):
    t = app.extensions["twitch"]
    t.client_id, t.client_secret = "cid", "secret"
    mods = {"id-modkate"}
    monkeypatch.setattr(twmod.Twitch, "identify",
                        lambda self, code, uri: {"login": code, "user_id": "id-" + code})
    monkeypatch.setattr(twmod.Twitch, "is_moderator", lambda self, user_id: user_id in mods)
    return t


def sign_in(client, site, login):
    res = client.get(f"/auth/login?site={site}")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(res.headers["Location"]).query, keep_blank_values=True))
    assert res.headers["Location"].startswith(twmod.AUTH_URL)
    assert q["redirect_uri"] == "http://localhost:5000/auth/callback" and q["scope"] == ""
    back = client.get(f"/auth/callback?code={login}&state={q['state']}").headers["Location"]
    url = urllib.parse.urlparse(back)
    return f"{url.scheme}://{url.netloc}", dict(urllib.parse.parse_qsl(url.fragment))


def test_site_sign_in(client, tw):
    site, frag = sign_in(client, "user", "alice")
    assert site == USER_SITE
    me = client.get("/api/me", headers={"Authorization": "Bearer " + frag["token"]}).json
    assert me["login"] == "alice" and me["role"] == "viewer"

    site, frag = sign_in(client, "mod", "modkate")
    assert site == MOD_SITE
    assert client.get("/api/me", headers={"Authorization": "Bearer " + frag["token"]}).json["role"] == "mod"

    site, frag = sign_in(client, "mod", "alice")
    assert site == MOD_SITE and "token" not in frag and "isn't a mod" in frag["error"]

    # A callback without a matching sign-in started in this browser is refused.
    assert client.get("/auth/callback?code=alice&state=forged").status_code == 400


def test_cors_only_for_the_two_sites(client):
    def preflight(origin):
        return client.options("/api/viewer/memes", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
    assert preflight(USER_SITE).headers.get("Access-Control-Allow-Origin") == USER_SITE
    assert preflight(MOD_SITE).headers.get("Access-Control-Allow-Origin") == MOD_SITE
    assert "Access-Control-Allow-Origin" not in preflight("https://evil.example").headers


@pytest.mark.skipif(not __import__("conftest").TEST_DATABASE_URL, reason="needs TEST_DATABASE_URL")
def test_files_survive_a_restart_on_postgres(app, tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    face = tmp_path / "data" / "faces" / "kept.png"
    face.parent.mkdir(parents=True, exist_ok=True)
    face.write_bytes(b"png-bytes")
    storage.save(face)
    face.unlink()          # the cloud host wipes its disk...
    storage.restore()      # ...and startup brings the file back
    assert face.read_bytes() == b"png-bytes"
    storage.delete(face)
    face.unlink()
    storage.restore()
    assert not face.exists()
