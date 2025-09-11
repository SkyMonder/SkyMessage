from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sky.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'supersecretkey'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(200))

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    users = db.relationship('User', secondary='chat_user')

class ChatUser(db.Model):
    __tablename__ = 'chat_user'
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

db.create_all()

# --- Auth ---
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"ok": False, "error": "exists"})
    u = User(username=data['username'], password=generate_password_hash(data['password']))
    db.session.add(u)
    db.session.commit()
    session['user_id'] = u.id
    return jsonify({"ok": True})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    u = User.query.filter_by(username=data['username']).first()
    if u and check_password_hash(u.password, data['password']):
        session['user_id'] = u.id
        return jsonify({"ok": True})
    return jsonify({"ok": False})

@app.route("/logout")
def logout():
    session.pop('user_id', None)
    return jsonify({"ok": True})

# --- API ---
@app.route("/api/me")
def api_me():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"user": None})
    u = User.query.get(user_id)
    return jsonify({"user": {"id": u.id, "username": u.username}})

@app.route("/api/chats")
def api_chats():
    user_id = session.get('user_id')
    if not user_id: return jsonify([])
    user = User.query.get(user_id)
    chats = Chat.query.join(ChatUser).filter(ChatUser.user_id==user_id).all()
    result = []
    for c in chats:
        last = Message.query.filter_by(chat_id=c.id).order_by(Message.timestamp.desc()).first()
        result.append({"id": c.id, "name": c.name, "last": {"text": last.text if last else ""}})
    return jsonify(result)

@app.route("/api/messages/<int:chat_id>")
def api_messages(chat_id):
    user_id = session.get('user_id')
    if not user_id: return jsonify([])
    msgs = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp).all()
    return jsonify([{"sender_id": m.sender_id, "text": m.text, "timestamp": m.timestamp.isoformat()} for m in msgs])

@app.route("/api/send_message", methods=["POST"])
def api_send_message():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"ok": False, "error": "not_logged_in"})
    data = request.json
    m = Message(chat_id=data['chat_id'], sender_id=user_id, text=data['text'])
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
    user_id = session.get('user_id')
    if not user_id: return jsonify({"ok": False})
    data = request.json
    users = [User.query.get(uid) for uid in data['user_ids'] if User.query.get(uid)]
    if not users: return jsonify({"ok": False})
    c = Chat(name="Chat with "+", ".join([u.username for u in users]))
    db.session.add(c)
    db.session.commit()
    db.session.add(ChatUser(chat_id=c.id, user_id=user_id))
    for u in users: db.session.add(ChatUser(chat_id=c.id, user_id=u.id))
    db.session.commit()
    socketio.emit("new_chat")
    return jsonify({"ok": True, "chat_id": c.id})

# --- Socket.IO для звонков ---
@socketio.on("register")
def sock_register(data):
    # можно хранить connected users если нужно
    pass

@socketio.on("call_user")
def call_user(data):
    socketio.emit("incoming_call", data, to=data['to'])

@socketio.on("answer_call")
def answer_call(data):
    socketio.emit("call_answered", data, to=data['to'])

@socketio.on("end_call")
def end_call(data):
    socketio.emit("call_ended", data, to=data['to'])

if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)


