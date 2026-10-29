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

    # Twitch (used from Phase 4)
    TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
    TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
    TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL", "")
    TWITCH_BOT_TOKEN = os.getenv("TWITCH_BOT_TOKEN", "")
