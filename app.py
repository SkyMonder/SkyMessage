import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash

# === Flask setup ===
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "supersecret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///app.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# === Models ===
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    text = db.Column(db.String(500), nullable=False)


# === Auth routes ===
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "User already exists"}), 400
    user = User(username=data["username"])
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "Registered successfully"})


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data["username"]).first()
    if not user or not user.check_password(data["password"]):
        return jsonify({"error": "Invalid credentials"}), 401
    session["user_id"] = user.id
    return jsonify({"message": "Login successful", "user_id": user.id})


# === User search API ===
@app.route("/api/users")
def api_users():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])
    users = User.query.filter(User.username.ilike(f"%{q}%")).all()
    return jsonify([{"id": u.id, "username": u.username} for u in users])


# === Chat messages API ===
@app.route("/api/messages/<int:user_id>")
def get_messages(user_id):
    current_user = session.get("user_id")
    if not current_user:
        return jsonify({"error": "Unauthorized"}), 401

    messages = (
        Message.query.filter(
            ((Message.sender_id == current_user) & (Message.receiver_id == user_id))
            | ((Message.sender_id == user_id) & (Message.receiver_id == current_user))
        )
        .all()
    )
    return jsonify(
        [
            {"id": m.id, "sender": m.sender_id, "receiver": m.receiver_id, "text": m.text}
            for m in messages
        ]
    )


# === Socket.IO events ===
@socketio.on("send_message")
def handle_message(data):
    sender = session.get("user_id")
    receiver = data["receiver_id"]
    text = data["text"]

    msg = Message(sender_id=sender, receiver_id=receiver, text=text)
    db.session.add(msg)
    db.session.commit()

    emit(
        "receive_message",
        {"sender": sender, "receiver": receiver, "text": text},
        room=f"user_{receiver}",
    )
    emit(
        "receive_message",
        {"sender": sender, "receiver": receiver, "text": text},
        room=f"user_{sender}",
    )


@socketio.on("join")
def on_join(data):
    user_id = data["user_id"]
    join_room(f"user_{user_id}")


@socketio.on("leave")
def on_leave(data):
    user_id = data["user_id"]
    leave_room(f"user_{user_id}")


# === Call events ===
@socketio.on("call_user")
def call_user(data):
    emit("incoming_call", {"from": data["from"]}, room=f"user_{data['to']}")


@socketio.on("answer_call")
def answer_call(data):
    emit("call_answered", {"from": data["from"], "accepted": data["accepted"]}, room=f"user_{data['to']}")


# === Main page ===
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return render_template("chats.html")


@app.route("/login_page")
def login_page():
    return render_template("login.html")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
