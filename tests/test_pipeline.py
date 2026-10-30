from conftest import bot_messages


def chat(client, user, text):
    return client.post("/api/demo/chat", json={"user": user, "text": text})


def pending(client):
    return client.get("/api/queue").json["pending"]


def test_memes_lists_templates(client, sio):
    chat(client, "alice", "!memes")
    assert "testmeme" in bot_messages(sio)[0]


def test_meme_request_goes_to_mod_queue(client, sio):
    chat(client, "alice", "!meme testmeme homework vs gaming")
    assert "waiting for mod approval" in bot_messages(sio)[0]
    [meme] = pending(client)
    assert (meme["requested_by"], meme["caption"], meme["source"]) == ("alice", "homework vs gaming", "demo")
    assert client.get(meme["url"]).status_code == 200


def test_template_matching_is_forgiving(client, sio):
    chat(client, "alice", "!meme TEST")
    assert pending(client)[0]["template_id"] == "testmeme"


def test_refusals(client, sio):
    chat(client, "bob", "!meme pizza hi")
    chat(client, "bob", "!meme testmeme www.spam.com")
    chat(client, "bob", "hello chat")
    msgs = bot_messages(sio)
    assert "don't know that meme" in msgs[0]
    assert "links aren't allowed" in msgs[1]
    assert len(msgs) == 2  # plain chat is ignored
    assert pending(client) == []


def test_cooldown_and_queue_limit(client, sio):
    chat(client, "carol", "!meme testmeme one")
    chat(client, "carol", "!meme testmeme two")
    assert "slow down" in bot_messages(sio)[-1]
    chat(client, "dave", "!meme testmeme")
    chat(client, "erin", "!meme testmeme")
    chat(client, "frank", "!meme testmeme")  # QUEUE_LIMIT = 3 in tests
    assert "queue is full" in bot_messages(sio)[-1]
    client.post("/api/demo/reset-cooldowns")
    chat(client, "carol", "!meme testmeme again")
    assert "queue is full" in bot_messages(sio)[-1]


def test_approve_reject_replay_and_overlay(client, sio):
    chat(client, "alice", "!meme testmeme a")
    chat(client, "bob", "!meme testmeme b")
    first, second = (m["id"] for m in pending(client))
    sio.get_received()

    assert client.post(f"/api/memes/{first}/approve", json={"mod": "modjoe"}).status_code == 200
    events = [e["name"] for e in sio.get_received()]
    assert "show_meme" in events and "bot_message" in events
    assert client.post(f"/api/memes/{first}/approve").status_code == 409  # already decided

    client.post(f"/api/memes/{second}/reject")
    assert "wasn't approved" in bot_messages(sio)[-1]

    assert [m["id"] for m in client.get("/api/overlay/queue").json] == [first]
    client.post(f"/api/memes/{first}/shown")
    assert client.get("/api/overlay/queue").json == []
    assert client.post(f"/api/memes/{first}/replay").status_code == 200
    assert client.post(f"/api/memes/{second}/replay").status_code == 409


def test_channel_point_redemption(client, sio):
    client.post("/api/demo/redeem", json={"user": "gina", "text": "testmeme stay | touch grass"})
    [meme] = pending(client)
    assert meme["caption"] == "stay | touch grass"
    client.post("/api/demo/redeem", json={"user": "hank", "text": ""})
    assert "include a meme name" in bot_messages(sio)[-1]
