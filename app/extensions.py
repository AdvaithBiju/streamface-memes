from flask_socketio import SocketIO

# Threading mode works with the plain Werkzeug server on every OS/Python.
socketio = SocketIO(async_mode="threading")
