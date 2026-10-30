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
    assert client.post("/api/voting/open").json["open"] is True
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
    assert state["total_votes"] == 3

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
    client.post(f"/api/memes/{rendered['id']}/send")
    client.post("/api/voting/open")
    vote(client, "v1", rendered["id"])
    assert "isn't in the running" in bot_messages(sio)[-1]


def test_close_with_no_votes(client, sio):
    client.post("/api/voting/open")
    sio.get_received()
    assert client.post("/api/voting/close").json["winner_id"] is None
    assert "No votes" in bot_messages(sio)[-1]
