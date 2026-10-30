"""Test fixtures: an app wired to a temp folder, with one template and one face.

Nothing here touches data/, templates/originals/ or the network.
"""
import json
import sqlite3

import pytest
from PIL import Image, ImageDraw

from app import create_app
from app.config import Config
from app.extensions import socketio


@pytest.fixture
def app(tmp_path):
    templates = tmp_path / "templates"
    (templates / "originals").mkdir(parents=True)
    Image.new("RGB", (400, 300), "steelblue").save(templates / "originals" / "testmeme.jpg")
    (templates / "templates.json").write_text(json.dumps({"templates": [{
        "id": "testmeme", "name": "Test Meme", "file": "testmeme.jpg",
        "image_url": "https://i.imgflip.com/unused.jpg", "width": 400, "height": 300,
        "face_slots": [{"x": 150, "y": 40, "width": 100, "height": 130, "rotation": 0}],
        "captions": [
            {"x": 10, "y": 180, "width": 180, "height": 100, "size": 30, "default": "top"},
            {"x": 210, "y": 180, "width": 180, "height": 100, "size": 30, "default": "bottom"},
        ],
    }]}))

    class TestConfig(Config):
        TESTING = True
        DATA_DIR = tmp_path / "data"
        FACES_DIR = tmp_path / "data" / "faces"
        DB_PATH = tmp_path / "data" / "test.db"
        TEMPLATES_DIR = templates
        GENERATED_DIR = tmp_path / "generated"
        COOLDOWN_SECONDS = 60
        QUEUE_LIMIT = 3
        DEMO_MODE = True
        TWITCH_CLIENT_ID = ""
        TWITCH_CLIENT_SECRET = ""

    application = create_app(TestConfig)

    # A fake face cutout, inserted directly (face detection has its own test).
    face = Image.new("RGBA", (100, 130), (0, 0, 0, 0))
    ImageDraw.Draw(face).ellipse([0, 0, 99, 129], fill=(230, 180, 150, 255))
    face.save(TestConfig.FACES_DIR / "face.png")
    with sqlite3.connect(TestConfig.DB_PATH) as db:
        db.execute("INSERT INTO faces (filename, source) VALUES ('face.png', 'upload')")

    from app import pipeline
    pipeline.reset_cooldowns()
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sio(app, client):
    """Socket.IO test client; get_received() returns everything the server emitted."""
    return socketio.test_client(app, flask_test_client=client)


def bot_messages(sio):
    return [e["args"][0]["text"] for e in sio.get_received() if e["name"] == "bot_message"]
