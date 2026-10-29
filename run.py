from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # Local-only dev server; Werkzeug is fine for a single streamer's machine.
    socketio.run(app, host=app.config["HOST"], port=app.config["PORT"], debug=True,
                 allow_unsafe_werkzeug=True)
