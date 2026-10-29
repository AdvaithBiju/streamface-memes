import logging

from flask import Flask, redirect, url_for

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

    for d in (app.config["FACES_DIR"], app.config["TEMPLATES_DIR"], app.config["GENERATED_DIR"]):
        d.mkdir(parents=True, exist_ok=True)
    init_db(app.config["DB_PATH"])
    app.teardown_appcontext(close_db)

    app.extensions["face_detector"] = FaceDetector(app.config["MODEL_PATH"])
    app.logger.info("Face detector backend: %s", app.extensions["face_detector"].backend)

    app.extensions["template_store"] = TemplateStore(app.config["TEMPLATES_DIR"])
    app.extensions["template_store"].download_originals()

    app.extensions["chat_senders"] = []  # Twitch bot registers here in Phase 4

    from .routes.editor import bp as editor_bp
    from .routes.setup import bp as setup_bp
    from .routes.stream import bp as stream_bp
    app.register_blueprint(setup_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(stream_bp)

    socketio.init_app(app)

    @app.get("/")
    def index():
        return redirect(url_for("setup.setup_page"))

    return app
