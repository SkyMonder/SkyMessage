from flask import Flask, request, jsonify, session, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Chat, ChatUser, Message
import os

UPLOAD_FOLDER = 'static/uploads'

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

with app.app_context():
    db.create_all()

# --- HTML ---
@app.route('/')
def welcome_page(): return render_template('welcome.html')
@app.route('/login.html')
def login_page(): return render_template('login.html')
@app.route('/register.html')
def register_page(): return render_template('register.html')
@app.route('/chats.html')
def chats_page(): return render_template('chats.html')

# --- AUTH API ---
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'ok':False,'error':'exists'})
    user = User(username=data['username'], password=generate_password_hash(data['password']))
    db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
    return jsonify({'ok':True})

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if not user or not check_password_hash(user.password, data['password']):
        return jsonify({'ok':False})
    session['user_id'] = user.id
    return jsonify({'ok':True})

@app.route('/api/me')
def me():
    uid = session.get('user_id')
    if not uid: return jsonify({'error':'unauth'}), 401
    u = User.query.get(uid)
    return jsonify({'user':{'id':u.id,'username':u.username}})

# --- CHATS API ---
@app.route('/api/chats')
def get_chats():
    uid = session.get('user_id')
    if not uid: return jsonify([])
    chats = db.session.query(Chat).join(ChatUser).filter(ChatUser.user_id==uid).all()
    result=[]
    for c in chats:
        last = Message.query.filter_by(chat_id=c.id).order_by(Message.timestamp.desc()).first()
        last_text = last.text if last else ''
        result.append({'id':c.id,'name':c.name,'last':{'text':last_text}})
    return jsonify(result)

@app.route('/api/messages/<int:chat_id>')
def get_messages(chat_id):
    uid = session.get('user_id')
    if not uid: return jsonify([])
    msgs = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp).all()
    return jsonify([{'sender_id':m.sender_id,'text':m.text,'file':m.file,'timestamp':m.timestamp.isoformat()} for m in msgs])

@app.route('/api/send_message', methods=['POST'])
def send_message():
    uid = session.get('user_id')
    if not uid: return jsonify({'error':'unauth'}), 401
    text = request.form.get('text','')
    chat_id = int(request.form.get('chat_id'))
    file = None
    if 'file' in request.files:
        f = request.files['file']
        filename = f"{uid}_{f.filename}"
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        file = filename
    m = Message(chat_id=chat_id, sender_id=uid, text=text, file=file)
    db.session.add(m)
    db.session.commit()
    socketio.emit('message', {'chat_id':m.chat_id,'sender_id':m.sender_id,'text':m.text,'file':m.file,'timestamp':m.timestamp.isoformat()})
    return jsonify({'ok':True})

@app.route('/api/users')
def search_users():
    q = request.args.get('q','')
    users = User.query.filter(User.username.contains(q)).all()
    return jsonify([{'id':u.id,'username':u.username} for u in users])

@app.route('/api/create_chat', methods=['POST'])
def create_chat():
    uid = session.get('user_id')
    if not uid: return jsonify({'error':'unauth'}), 401
    data = request.json
    ids = data['user_ids'] + [uid]
    # Проверка на существующий чат с точно этими юзерами
    chats = Chat.query.join(ChatUser).filter(ChatUser.user_id.in_(ids)).all()
    for c in chats:
        members = [cu.user_id for cu in ChatUser.query.filter_by(chat_id=c.id).all()]
        if sorted(members) == sorted(ids):
            return jsonify({'ok':True,'chat_id':c.id})
    # Создание нового
    name = ", ".join([User.query.get(i).username for i in data['user_ids']])
    chat = Chat(name=name)
    db.session.add(chat)
    db.session.commit()
    for i in ids:
        db.session.add(ChatUser(chat_id=chat.id, user_id=i))
    db.session.commit()
    socketio.emit('new_chat')
    return jsonify({'ok':True,'chat_id':chat.id})

# --- SOCKET.IO ---
@socketio.on('join_chat')
def on_join(data):
    join_room(data['chat_id'])

# --- STATIC FILES ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__=="__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
