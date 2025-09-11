from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Модели ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(200))

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))

class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.String(500))

# --- REST API ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"ok": False, "error": "exists"})
    u = User(username=data['username'], password=generate_password_hash(data['password']))
    db.session.add(u)
    db.session.commit()
    return jsonify({"ok": True})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    u = User.query.filter_by(username=data['username']).first()
    if u and check_password_hash(u.password, data['password']):
        return jsonify({"ok": True, "user": {"id": u.id, "username": u.username}})
    return jsonify({"ok": False})

@app.route('/api/me')
def me():
    # Пока возвращаем заглушку, потом можно сделать сессии
    return jsonify({"user": {"id": 1, "username": "TestUser"}})

@app.route('/api/users')
def users():
    q = request.args.get('q','')
    users = User.query.filter(User.username.contains(q)).all()
    return jsonify([{"id": u.id, "username": u.username} for u in users])

@app.route('/api/chats')
def chats():
    chats = Chat.query.all()
    result = []
    for c in chats:
        last_msg = Message.query.filter_by(chat_id=c.id).order_by(Message.id.desc()).first()
        result.append({"id": c.id, "name": c.name, "last": {"text": last_msg.text if last_msg else ""}})
    return jsonify(result)

@app.route('/api/messages/<int:chat_id>')
def messages(chat_id):
    msgs = Message.query.filter_by(chat_id=chat_id).all()
    return jsonify([{"sender_id": m.sender_id, "text": m.text, "timestamp": ""} for m in msgs])

@app.route('/api/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    msg = Message(chat_id=data['chat_id'], sender_id=1, text=data['text'])
    db.session.add(msg)
    db.session.commit()
    socketio.emit('message', {"chat_id": data['chat_id'], "sender_id": 1, "text": data['text']})
    return jsonify({"ok": True})

@app.route('/api/create_chat', methods=['POST'])
def create_chat():
    data = request.get_json()
    c = Chat(name="Chat")
    db.session.add(c)
    db.session.commit()
    for uid in data['user_ids']:
        db.session.add(ChatMember(chat_id=c.id, user_id=uid))
    db.session.commit()
    socketio.emit('new_chat')
    return jsonify({"ok": True, "chat_id": c.id})

# --- Socket.IO ---
users_online = {}

@socketio.on('register')
def handle_register(data):
    users_online[data['username']] = request.sid

@socketio.on('join_chat')
def handle_join(data):
    join_room(data['chat_id'])

@socketio.on('call_user')
def handle_call(data):
    to_sid = users_online.get(data['to'])
    if to_sid:
        emit('incoming_call', data, room=to_sid)

@socketio.on('answer_call')
def handle_answer(data):
    to_sid = users_online.get(data['to'])
    if to_sid:
        emit('call_answered', data, room=to_sid)

@socketio.on('end_call')
def handle_end_call(data):
    to_sid = users_online.get(data['to'])
    if to_sid:
        emit('call_ended', room=to_sid)

# --- Запуск ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # ⚡ важно обернуть в контекст
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
