import logging

from flask import Flask, redirect, url_for

from . import storage
from .auth import check_access
from .config import Config
from .db import close_db, init_db
from .extensions import socketio
from .face import FaceDetector
from .memetemplates import TemplateStore


def create_app(config_class=Config) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Flask's HTML lives in app/pages so the root /templates folder can hold meme images.
    app = Flask(__name__, template_folder="pages", static_folder="static")
    app.config.from_object(config_class)

    cfg = app.config
    if (cfg["ADMIN_PASSWORD"] or cfg["DATABASE_URL"]) and cfg["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError("Set FLASK_SECRET_KEY before putting StreamFace online.")
    cfg["SESSION_COOKIE_SECURE"] = cfg["PUBLIC_URL"].startswith("https://")

    for d in (cfg["FACES_DIR"], cfg["TEMPLATES_DIR"], cfg["GENERATED_DIR"]):
        d.mkdir(parents=True, exist_ok=True)
    init_db(cfg["DB_PATH"], cfg["DATABASE_URL"])
    storage.restore()  # cloud: bring back faces, memes and tokens after a restart
    app.teardown_appcontext(close_db)
    app.before_request(check_access)

    # The Vercel sites call the API from their own domains.
    site_origins = [u for u in (cfg["USER_SITE_URL"], cfg["MOD_SITE_URL"]) if u]
    if site_origins:
        from flask_cors import CORS
        CORS(app, resources={r"/api/*": {"origins": site_origins}},
             allow_headers=["Authorization", "Content-Type"], max_age=600)

    app.extensions["face_detector"] = FaceDetector(app.config["MODEL_PATH"])
    app.logger.info("Face detector backend: %s", app.extensions["face_detector"].backend)

    app.extensions["template_store"] = TemplateStore(app.config["TEMPLATES_DIR"])
    app.extensions["template_store"].download_originals()

    from .twitch import Twitch
    app.extensions["twitch"] = Twitch(app)
    # Everything pipeline.say() sends also goes to Twitch chat once connected.
    app.extensions["chat_senders"] = [app.extensions["twitch"].send_chat]

    from .routes.editor import bp as editor_bp
    from .routes.setup import bp as setup_bp
    from .routes.stream import bp as stream_bp
    from .routes.sites import bp as sites_bp
    from .routes.twitch import bp as twitch_bp
    app.register_blueprint(setup_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(stream_bp)
    app.register_blueprint(twitch_bp)
    app.register_blueprint(sites_bp)

    socketio.init_app(app)

    @app.get("/")
    def index():
        return redirect(url_for("setup.setup_page"))

    return app
