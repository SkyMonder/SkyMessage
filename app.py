import os
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, emit
from datetime import datetime

# --- Flask ---
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))

class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("chat.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("chat.id"))
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    text = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Simple auth (fake) ---
CURRENT_USER = "SkyMonder"

@app.before_first_request
def setup():
    db.create_all()
    if not User.query.filter_by(username=CURRENT_USER).first():
        db.session.add(User(username=CURRENT_USER))
        db.session.commit()

# --- Routes ---
@app.route("/")
def index():
    return send_from_directory(".", "chats.html")

@app.route("/api/me")
def me():
    u = User.query.filter_by(username=CURRENT_USER).first()
    return jsonify({"user": {"id": u.id, "username": u.username}})

@app.route("/api/users")
def users():
    q = request.args.get("q", "")
    results = User.query.filter(User.username.like(f"%{q}%")).all()
    return jsonify([{"id": u.id, "username": u.username} for u in results])

@app.route("/api/create_chat", methods=["POST"])
def create_chat():
    data = request.get_json()
    user_ids = data.get("user_ids", [])
    chat = Chat(name="Личный чат")
    db.session.add(chat)
    db.session.commit()
    # members
    for uid in user_ids + [User.query.filter_by(username=CURRENT_USER).first().id]:
        db.session.add(ChatMember(chat_id=chat.id, user_id=uid))
    db.session.commit()
    socketio.emit("new_chat", {"chat_id": chat.id})
    return jsonify({"ok": True, "chat_id": chat.id})

@app.route("/api/chats")
def chats():
    me = User.query.filter_by(username=CURRENT_USER).first()
    member_chats = ChatMember.query.filter_by(user_id=me.id).all()
    chats = []
    for m in member_chats:
        c = Chat.query.get(m.chat_id)
        last = Message.query.filter_by(chat_id=c.id).order_by(Message.timestamp.desc()).first()
        chats.append({
            "id": c.id,
            "name": c.name,
            "last": {"text": last.text if last else ""}
        })
    return jsonify(chats)

@app.route("/api/messages/<int:chat_id>")
def messages(chat_id):
    msgs = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp).all()
    return jsonify([{
        "id": m.id,
        "chat_id": m.chat_id,
        "sender_id": m.sender_id,
        "text": m.text,
        "timestamp": m.timestamp.isoformat()
    } for m in msgs])

@app.route("/api/send_message", methods=["POST"])
def send_message():
    data = request.get_json()
    chat_id, text = data.get("chat_id"), data.get("text")
    me = User.query.filter_by(username=CURRENT_USER).first()
    m = Message(chat_id=chat_id, sender_id=me.id, text=text)
    db.session.add(m)
    db.session.commit()
    payload = {
        "id": m.id,
        "chat_id": chat_id,
        "sender_id": me.id,
        "text": m.text,
        "timestamp": m.timestamp.isoformat()
    }
    socketio.emit("message", payload, to=str(chat_id))
    return jsonify({"ok": True})

# --- Socket.IO ---
@socketio.on("join_chat")
def on_join(data):
    join_room(str(data["chat_id"]))

@socketio.on("leave_chat")
def on_leave(data):
    leave_room(str(data["chat_id"]))

# --- Run ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    import eventlet
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(("0.0.0.0", port)), app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)

