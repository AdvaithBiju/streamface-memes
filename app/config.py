import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5000"))

    DATA_DIR = ROOT / "data"
    FACES_DIR = DATA_DIR / "faces"
    DB_PATH = DATA_DIR / "streamface.db"
    MODEL_PATH = ROOT / "models" / "blaze_face_short_range.tflite"
    TEMPLATES_DIR = ROOT / "templates"   # meme templates (Phase 2)
    GENERATED_DIR = ROOT / "generated"   # finished memes (Phase 2)

    MAX_FACES = 3
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB per request

    # Meme requests from chat / channel points
    COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "60"))   # per viewer
    QUEUE_LIMIT = int(os.getenv("QUEUE_LIMIT", "10"))             # max memes awaiting approval
    CAPTION_MAX_LENGTH = int(os.getenv("CAPTION_MAX_LENGTH", "80"))
    OVERLAY_SECONDS = int(os.getenv("OVERLAY_SECONDS", "8"))
    VOTE_WINDOW_HOURS = int(os.getenv("VOTE_WINDOW_HOURS", "12"))  # memes eligible for !vote
    DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in ("1", "true", "yes")

    # Twitch app from https://dev.twitch.tv/console/apps. Accounts are connected
    # on the /twitch page; their tokens are stored in data/twitch.json.
    TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "").strip()
    TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
    TWITCH_REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI", "http://localhost:5000/twitch/callback")
    TWITCH_REWARD_TITLE = os.getenv("TWITCH_REWARD_TITLE", "Make a Meme")
    TWITCH_REWARD_COST = int(os.getenv("TWITCH_REWARD_COST", "500"))
