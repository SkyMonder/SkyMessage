import os
from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, join_room, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Временные данные ---
USERS = [
    {"id": 1, "username": "SkyMonder"},
    {"id": 2, "username": "Alice"},
    {"id": 3, "username": "Bob"},
]
CHATS = []
MESSAGES = []
SESSIONS = {}  # user -> sid


# --- API ---
@app.route("/")
def index():
    return send_from_directory(".", "chats.html")

@app.route("/api/me")
def me():
    # Заглушка: возвращаем первого пользователя
    return jsonify({"user": USERS[0]})

@app.route("/api/users")
def search_users():
    q = request.args.get("q", "").lower()
    return jsonify([u for u in USERS if q in u["username"].lower()])

@app.route("/api/chats")
def get_chats():
    return jsonify(CHATS)

@app.route("/api/messages/<int:chat_id>")
def get_messages(chat_id):
    msgs = [m for m in MESSAGES if m["chat_id"] == chat_id]
    return jsonify(msgs)

@app.route("/api/send_message", methods=["POST"])
def send_message():
    data = request.json
    m = {
        "chat_id": data["chat_id"],
        "sender_id": 1,  # Заглушка (SkyMonder)
        "text": data["text"],
        "timestamp": socketio.server.manager.get_namespaces(),  # временная метка
    }
    MESSAGES.append(m)
    socketio.emit("message", m, room=f"chat_{data['chat_id']}")
    return jsonify({"ok": True})

@app.route("/api/create_chat", methods=["POST"])
def create_chat():
    data = request.json
    chat_id = len(CHATS) + 1
    chat = {"id": chat_id, "name": "Chat " + str(chat_id), "last": {}}
    CHATS.append(chat)
    socketio.emit("new_chat", chat)
    return jsonify({"ok": True, "chat_id": chat_id})


# --- Socket.IO ---
@socketio.on("connect")
def on_connect():
    print("User connected:", request.sid)

@socketio.on("join_chat")
def on_join_chat(data):
    join_room(f"chat_{data['chat_id']}")

@socketio.on("register")
def on_register(data):
    SESSIONS[data["username"]] = request.sid
    print("Registered:", data["username"])

# --- Звонки ---
@socketio.on("call_user")
def on_call_user(data):
    to = data["to"]
    sid = SESSIONS.get(to)
    if sid:
        emit("incoming_call", data, to=sid)

@socketio.on("answer_call")
def on_answer_call(data):
    to = data["to"]
    sid = SESSIONS.get(to)
    if sid:
        emit("call_answered", data, to=sid)

@socketio.on("end_call")
def on_end_call(data):
    to = data["to"]
    sid = SESSIONS.get(to)
    if sid:
        emit("call_ended", data, to=sid)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)

