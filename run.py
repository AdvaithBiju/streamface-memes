from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # Connect to Twitch chat/channel points if an account is connected on /twitch.
    app.extensions["twitch"].start()
    host, port = app.config["HOST"], app.config["PORT"]
    print()
    print(f"StreamFace Memes running at http://localhost:{port}")
    print(f"  OBS overlay:  http://localhost:{port}/overlay")
    print(f"  Mod queue:    http://localhost:{port}/mod")
    print(f"  Twitch setup: http://localhost:{port}/twitch")
    print()
    # Local-only server. No auto-reloader: it would start the Twitch bot twice.
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False,
                 allow_unsafe_werkzeug=True)
