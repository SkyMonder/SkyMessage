from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from models import db, User, Chat, Message
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///skymessage.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

users_online = {}  # username -> sid

# --- Pages ---
@app.route("/")
def welcome():
    return render_template("welcome.html")

@app.route("/register.html")
def register_page():
    return render_template("register.html")

@app.route("/login.html")
def login_page():
    return render_template("login.html")

@app.route("/chats.html")
def chats_page():
    return render_template("chats.html")

# --- API ---
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"ok": False, "error": "exists"})
    u = User(username=data['username'], password=generate_password_hash(data['password']))
    db.session.add(u)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    u = User.query.filter_by(username=data['username']).first()
    if u and check_password_hash(u.password, data['password']):
        return jsonify({"ok": True})
    return jsonify({"ok": False})

@app.route("/api/me")
def api_me():
    # Для простоты возвращаем первого пользователя
    u = User.query.first()
    if u:
        return jsonify({"user": {"id": u.id, "username": u.username}})
    return jsonify({"user": None})

@app.route("/api/chats")
def api_chats():
    chats = Chat.query.all()
    result = []
    for c in chats:
        last = Message.query.filter_by(chat_id=c.id).order_by(Message.timestamp.desc()).first()
        result.append({"id": c.id, "name": c.name, "last": {"text": last.text if last else ""}})
    return jsonify(result)

@app.route("/api/messages/<int:chat_id>")
def api_messages(chat_id):
    msgs = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp).all()
    return jsonify([{"sender_id": m.sender_id, "text": m.text, "timestamp": m.timestamp.isoformat()} for m in msgs])

@app.route("/api/send_message", methods=["POST"])
def api_send_message():
    data = request.json
    m = Message(chat_id=data['chat_id'], sender_id=1, text=data['text'])  # Для простоты sender_id=1
    db.session.add(m)
    db.session.commit()
    socketio.emit("message", {"chat_id": m.chat_id, "sender_id": m.sender_id, "text": m.text, "timestamp": m.timestamp.isoformat()})
    return jsonify({"ok": True})

@app.route("/api/users")
def api_users():
    q = request.args.get('q','')
    users = User.query.filter(User.username.contains(q)).all()
    return jsonify([{"id": u.id, "username": u.username} for u in users])

@app.route("/api/create_chat", methods=["POST"])
def api_create_chat():
    data = request.json
    users = data['user_ids']
    if not users: return jsonify({"ok": False})
    name = "@".join([str(u) for u in users])
    c = Chat(name=name)
    db.session.add(c)
    db.session.commit()
    socketio.emit("new_chat")
    return jsonify({"ok": True, "chat_id": c.id})

# --- Socket.IO ---
@socketio.on("register")
def socket_register(data):
    users_online[data['username']] = request.sid

@socketio.on("join_chat")
def join_chat(data):
    join_room(data['chat_id'])

@socketio.on("call_user")
def call_user(data):
    to_sid = users_online.get(data['to'])
    if to_sid:
        emit("incoming_call", data, room=to_sid)

@socketio.on("answer_call")
def answer_call(data):
    to_sid = users_online.get(data['to'])
    if to_sid:
        emit("call_answered", data, room=to_sid)

@socketio.on("end_call")
def end_call(data):
    to_sid = users_online.get(data['to'])
    if to_sid:
        emit("call_ended", data, room=to_sid)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)

