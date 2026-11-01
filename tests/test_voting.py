from app.auth import make_token
from app.voting import choices_message
from conftest import bot_messages


def make_approved_memes(client, users):
    ids = []
    for user in users:
        client.post("/api/demo/chat", json={"user": user, "text": "!meme testmeme hi"})
    for meme in client.get("/api/queue").json["pending"]:
        client.post(f"/api/memes/{meme['id']}/approve")
        ids.append(meme["id"])
    return ids


def vote(client, user, ref):
    client.post("/api/demo/chat", json={"user": user, "text": f"!vote {ref}"})


def test_vote_requires_open_round(client, sio):
    vote(client, "v1", 1)
    assert "isn't open" in bot_messages(sio)[-1]


def test_full_voting_round(client, sio):
    a, b = make_approved_memes(client, ["alice", "bob"])
    assert [m["id"] for m in client.get("/api/voting").json["candidates"]] == [a, b]
    sio.get_received()
    opened = client.post("/api/voting/open").json
    assert opened["open"] is True and [(m["id"], m["votes"]) for m in opened["candidates"]] == [(a, 0), (b, 0)]
    events = sio.get_received()
    # Opening shows the choices on stream and lists them in chat.
    choices = next(e["args"][0] for e in events if e["name"] == "show_choices")
    assert [m["id"] for m in choices["choices"]] == [a, b] and choices["total"] == 2
    said = [e["args"][0]["text"] for e in events if e["name"] == "bot_message"][-1]
    assert f"!vote {a} (alice)" in said and f"!vote {b} (bob)" in said
    assert client.post("/api/voting/open").status_code == 409

    vote(client, "v1", a)
    vote(client, "v2", f"#{b}")
    vote(client, "v3", b)
    vote(client, "v1", b)      # changing your vote moves it
    vote(client, "v4", 999)    # not in the running
    vote(client, "v5", "abc")  # not a number
    sio.get_received()

    state = client.get("/api/voting").json
    assert [(m["id"], m["votes"]) for m in state["leaderboard"]] == [(b, 3)]
    assert [(m["id"], m["votes"]) for m in state["candidates"]] == [(a, 0), (b, 3)]
    assert state["total_votes"] == 3

    res = client.post("/api/voting/choices")
    assert res.status_code == 200 and res.json["chat_connected"] is False   # tests have no Twitch login
    events = sio.get_received()
    assert any(e["name"] == "show_choices" for e in events)
    assert any(e["name"] == "bot_message" and f"!vote {b} (bob)" in e["args"][0]["text"] for e in events)

    assert client.post("/api/voting/show").status_code == 200
    assert any(e["name"] == "show_leaderboard" for e in sio.get_received())

    closed = client.post("/api/voting/close").json
    assert closed["open"] is False and closed["winner_id"] == b
    events = sio.get_received()
    assert any(e["name"] == "show_winner" and e["args"][0]["id"] == b for e in events)
    assert any(e["name"] == "bot_message" and "Meme of the Stream" in e["args"][0]["text"] for e in events)
    vote(client, "v6", b)
    assert "isn't open" in bot_messages(sio)[-1]


def test_streamer_memes_are_not_eligible(client, sio):
    template = client.get("/api/templates").json[0]
    rendered = client.post("/api/render", json={"template_id": template["id"], "layers": []}).json
    assert client.post(f"/api/memes/{rendered['id']}/send").json["status"] == "pending"
    client.post(f"/api/memes/{rendered['id']}/approve")
    make_approved_memes(client, ["alice"])
    assert rendered["id"] not in [m["id"] for m in client.post("/api/voting/open").json["candidates"]]
    vote(client, "v1", rendered["id"])
    assert "isn't in the running" in bot_messages(sio)[-1]


def test_cant_open_with_nothing_to_vote_on(client, sio):
    res = client.post("/api/voting/open")
    assert res.status_code == 409 and "approve some viewer memes" in res.json["error"]
    assert client.get("/api/voting").json["open"] is False
    assert client.post("/api/voting/choices").status_code == 409


def test_chat_list_fits_one_twitch_message():
    memes = [{"id": 1000 + i, "requested_by": f"viewer_with_a_long_name_{i}"} for i in range(40)]
    msg = choices_message(memes)
    assert len(msg) <= 500 and "!vote 1000 " in msg and msg.endswith("more on stream")
    assert choices_message(memes[:2]).endswith("!vote 1001 (viewer_with_a_long_name_1)")


def test_viewers_vote_on_the_site(app, client, sio):
    a, b = make_approved_memes(client, ["alice", "bob"])
    with app.app_context():
        carol = {"Authorization": "Bearer " + make_token("Carol", "id-carol", "viewer")}
    assert client.post("/api/viewer/vote", json={"meme_id": a}).status_code == 401
    assert "isn't open" in client.post("/api/viewer/vote", json={"meme_id": a}, headers=carol).json["error"]
    client.post("/api/voting/open")
    assert client.post("/api/viewer/vote", json={"meme_id": a}, headers=carol).status_code == 200
    state = client.post("/api/viewer/vote", json={"meme_id": b}, headers=carol).json   # changes the vote
    assert [(m["id"], m["votes"]) for m in state["candidates"]] == [(a, 0), (b, 1)]
    vote(client, "carol", a)   # same person in chat: still one vote
    assert client.get("/api/voting").json["total_votes"] == 1
    res = client.post("/api/viewer/vote", json={"meme_id": 999}, headers=carol)
    assert res.status_code == 409 and res.json["error"].startswith("meme #999")


def test_close_with_no_votes(client, sio):
    make_approved_memes(client, ["alice"])
    client.post("/api/voting/open")
    sio.get_received()
    assert client.post("/api/voting/close").json["winner_id"] is None
    assert "No votes" in bot_messages(sio)[-1]
