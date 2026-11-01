"""The online setup: password-protected streamer pages, and the viewer and mod sites' APIs."""
import base64
import io
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


FACE = {"type": "face", "face_id": 1, "x": 150, "y": 40, "width": 100, "height": 130}


def text(t, x=10):
    return {"type": "text", "text": t, "x": x, "y": 180, "width": 180, "height": 100, "size": 30}


def meme(template="testmeme", *layers):
    return {"template_id": template, "layers": list(layers) or [FACE, text("me at 3am"), text("still coding", 210)]}


def test_viewer_makes_a_meme_on_the_site(client, app):
    assert client.post("/api/viewer/memes", json={}).status_code == 401
    alice = token(app, "alice", "viewer")

    templates = client.get("/api/viewer/templates", headers=alice).json
    assert [t["id"] for t in templates] == ["testmeme"] and len(templates[0]["captions"]) == 2
    assert client.get("/api/viewer/faces", headers=alice).json == [
        {"id": 1, "url": "/faces/face.png", "mine": False}]
    assert client.get("/faces/face.png").status_code == 200   # the editor draws it

    res = client.post("/api/viewer/memes", headers=alice, json=meme())
    assert res.status_code == 201
    made = res.json
    assert made["status"] == "pending" and made["source"] == "web" and made["requested_by"] == "alice"
    assert made["caption"] == "me at 3am | still coding"
    assert client.get("/api/queue").json["pending"][0]["id"] == made["id"]

    again = client.post("/api/viewer/memes", headers=alice, json=meme())
    assert again.status_code == 409 and again.json["error"].startswith("slow down")
    assert [m["id"] for m in client.get("/api/viewer/memes", headers=alice).json] == [made["id"]]

    bob = token(app, "bob", "viewer")
    for body, error in ((meme("testmeme", FACE, text("hi @someone")), "@mentions"),
                        (meme("testmeme", FACE, text("go to evil.com")), "Links"),
                        (meme("testmeme", text("no face")), "Add a face"),
                        (meme("testmeme", {**FACE, "face_id": 99}), "isn't available"),
                        (meme("nope", FACE), "Pick a meme"),
                        ({"template_id": "testmeme", "layers": "x"}, "must be a list")):
        res = client.post("/api/viewer/memes", headers=bob, json=body)
        assert res.status_code == 409 and error in res.json["error"], body


def test_viewer_face_screenshots(client, app, monkeypatch):
    from app.routes import setup as setup_routes

    def fake_cutout(detector, data, out_path, max_faces=1):
        if data == b"no face here":
            raise setup_routes.FaceError("No face found. Try a well-lit, front-facing photo.")
        people = 3 if data == b"group shot" else 1
        paths = [out_path] + [out_path.with_name(f"{out_path.stem}-{i}.png") for i in range(2, people + 1)]
        for path in paths[:max_faces]:
            path.write_bytes((app.config["FACES_DIR"] / "face.png").read_bytes())
        return paths[:max_faces]
    monkeypatch.setattr(setup_routes, "process_photo", fake_cutout)
    app.config["VIEWER_MAX_FACES"] = 2

    alice, bob = token(app, "alice", "viewer"), token(app, "bob", "viewer")

    def upload(who, data=b"screenshot", source="paste"):
        return client.post("/api/viewer/faces", headers=who, content_type="multipart/form-data",
                           data={"photo": (io.BytesIO(data), "shot.png"), "source": source})

    res = upload(alice)
    assert res.status_code == 201 and res.json["mine"] is True
    face_id = res.json["id"]
    assert upload(alice, b"no face here").json["error"].startswith("No face found")
    assert upload(alice).status_code == 201
    assert "up to 2" in upload(alice).json["error"]

    # Alice's faces are hers: Bob can't see, use or delete them, and the streamer's pages don't list them.
    assert [f["id"] for f in client.get("/api/viewer/faces", headers=bob).json] == [1]
    assert len(client.get("/api/viewer/faces", headers=alice).json) == 3
    assert client.get("/api/faces").json[0]["id"] == 1 and len(client.get("/api/faces").json) == 1
    used = meme("testmeme", {**FACE, "face_id": face_id}, text("hello"))
    assert "isn't available" in client.post("/api/viewer/memes", headers=bob, json=used).json["error"]
    assert client.delete(f"/api/viewer/faces/{face_id}", headers=bob).status_code == 404
    assert client.delete("/api/viewer/faces/1", headers=alice).status_code == 404   # the streamer's

    assert client.post("/api/viewer/memes", headers=alice, json=used).status_code == 201
    assert client.delete(f"/api/viewer/faces/{face_id}", headers=alice).json == {"ok": True}
    assert len(client.get("/api/viewer/faces", headers=alice).json) == 2

    # A group screenshot gives one face per person, but only up to the viewer's limit.
    app.config["VIEWER_MAX_FACES"] = 5
    carol = token(app, "carol", "viewer")
    group = upload(carol, b"group shot").json
    ids = [f["id"] for f in group["faces"]]
    assert len(ids) == 3 and group["id"] == ids[0]
    assert len(upload(carol, b"group shot").json["faces"]) == 2   # 3 + 2 = the limit of 5

    # Several faces in one meme: the streamer's and two of Carol's.
    many = meme("testmeme", FACE, {**FACE, "face_id": ids[0], "x": 10}, {**FACE, "face_id": ids[1], "x": 300},
                text("squad"))
    made = client.post("/api/viewer/memes", headers=carol, json=many)
    assert made.status_code == 201, made.json


def test_only_mods_can_moderate(client, online):
    meme_ = client.post("/api/viewer/memes", headers=token(online, "alice", "viewer"),
                        json=meme("testmeme", FACE, text("hello"))).json
    viewer = token(online, "alice", "viewer")
    assert client.post(f"/api/memes/{meme_['id']}/approve", headers=viewer).status_code == 403
    assert client.get("/api/queue", headers=viewer).status_code == 403

    mod = token(online, "modkate", "mod")
    assert client.get("/api/queue", headers=mod).json["pending"][0]["id"] == meme_["id"]
    approved = client.post(f"/api/memes/{meme_['id']}/approve", headers=mod, json={"mod": "spoofed"}).json
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
