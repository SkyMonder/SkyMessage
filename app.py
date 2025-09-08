from flask import Flask, render_template, request, session, jsonify, redirect, url_for, abort
from flask_socketio import SocketIO, join_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models import User, Chat, Message
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY","devsecret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///skychat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({'error':'unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapper

@app.route('/')
def home():
    return redirect(url_for('login_page'))

@app.route('/login.html')
def login_page():
    return render_template('login.html')

@app.route('/register.html')
def register_page():
    return render_template('register.html')

@app.route('/chats.html')
@login_required
def chats_page():
    return render_template('chats.html')

# --- Auth ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'error':'empty'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error':'exists'}), 400
    user = User(username=username,password_hash=generate_password_hash(password))
    db.session.add(user); db.session.commit()
    session['user_id'] = user.id
    return jsonify({'ok': True})

@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash,password):
        session['user_id'] = user.id
        return jsonify({'ok': True})
    return jsonify({'error':'wrong'}), 401

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.pop('user_id',None)
    return jsonify({'ok': True})

# --- API ---
@app.route('/api/me')
@login_required
def api_me():
    u = current_user()
    return jsonify({'user':{'id':u.id,'username':u.username}})

@app.route('/api/chats')
@login_required
def api_chats():
    u = current_user()
    chats = Chat.query.filter(Chat.members.any(id=u.id)).all()
    result=[]
    for c in chats:
        last = Message.query.filter_by(chat_id=c.id).order_by(Message.timestamp.desc()).first()
        result.append({'id':c.id,'name':c.name,'last':{'text':last.text if last else '', 'timestamp': last.timestamp.isoformat() if last else None}})
    result.sort(key=lambda x:x['last']['timestamp'] or '', reverse=True)
    return jsonify(result)

@app.route('/api/messages/<int:chat_id>')
@login_required
def api_messages(chat_id):
    u = current_user()
    chat = Chat.query.get_or_404(chat_id)
    if u not in chat.members: abort(403)
    msgs = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp.asc()).all()
    return jsonify([{'id':m.id,'text':m.text,'sender_id':m.sender_id,'timestamp':m.timestamp.isoformat()} for m in msgs])

@app.route('/api/send_message', methods=['POST'])
@login_required
def api_send_message():
    u = current_user()
    data = request.json or {}
    chat_id = int(data.get('chat_id',0))
    text = (data.get('text') or '').strip()
    if not chat_id or not text: return jsonify({'error':'empty'}),400
    chat = Chat.query.get_or_404(chat_id)
    if u not in chat.members: abort(403)
    msg = Message(chat_id=chat.id, sender_id=u.id, text=text)
    db.session.add(msg); db.session.commit()
    payload={'id':msg.id,'chat_id':chat.id,'sender_id':u.id,'text':msg.text,'timestamp':msg.timestamp.isoformat()}
    socketio.emit('message',payload,room=f"chat_{chat.id}")
    return jsonify(payload)

@app.route('/api/create_chat', methods=['POST'])
@login_required
def api_create_chat():
    data = request.json or {}
    peer_id = data.get('peer_id')
    u = current_user()
    members = [u, User.query.get(peer_id)]
    chat_name = ', '.join([m.username for m in members])
    chat = Chat(name=chat_name)
    chat.members = members
    db.session.add(chat); db.session.commit()
    return jsonify({'ok':True,'chat_id':chat.id})

# --- Socket.IO ---
@socketio.on('join_chat')
def join(data):
    join_room(f"chat_{data.get('chat_id')}")

@socketio.on('webrtc_offer')
def webrtc_offer(data):
    chat_id = data['chat_id']
    emit('webrtc_offer', data, room=f"chat_{chat_id}", include_self=False)

@socketio.on('webrtc_answer')
def webrtc_answer(data):
    chat_id = data['chat_id']
    emit('webrtc_answer', data, room=f"chat_{chat_id}", include_self=False)

@socketio.on('webrtc_ice')
def webrtc_ice(data):
    chat_id = data['chat_id']
    emit('webrtc_ice', data, room=f"chat_{chat_id}", include_self=False)

# --- Run ---
if __name__=="__main__":
    with app.app_context(): db.create_all()
    port = int(os.environ.get("PORT",5000))
    socketio.run(app, host="0.0.0.0", port=port)
