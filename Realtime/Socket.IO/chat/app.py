from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit
import time
import secrets

app = Flask(__name__)
#app.secret_key = ''
app.secret_key = secrets.token_hex(32)

socketio = SocketIO(app)

active_users = {}
chat_history = {}


def room_key(user1, user2):
    return "__".join(sorted([user1, user2]))


@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' in session:
        return render_template('chat.html', username=session['username'])

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if not username:
            error = "Name cannot be empty."
        elif len(username) > 20:
            error = "Name is too long (max 20 characters)."
        elif username in active_users:
            error = f"'{username}' is already online. Pick another name."
        else:
            session['username'] = username
            return redirect(url_for('index'))

    return render_template('login.html', error=error)


@app.route('/check_username')
def check_username():
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify({"available": False, "message": ""})
    if len(username) > 20:
        return jsonify({"available": False, "message": "Too long"})
    if 'username' in session and session['username'] == username:
        return jsonify({"available": True, "message": "Your current name"})
    if username in active_users:
        return jsonify({"available": False, "message": "Name taken"})
    return jsonify({"available": True, "message": "Available"})


@app.route('/signout')
def signout():
    session.pop('username', None)
    return redirect(url_for('index'))


@socketio.on('connect')
def on_connect():
    username = session.get('username')
    if username:
        active_users[username] = request.sid
        emit('user_list', list(active_users.keys()), broadcast=True)


@socketio.on('disconnect')
def on_disconnect():
    username = session.get('username')
    if username in active_users and active_users[username] == request.sid:
        del active_users[username]
        emit('user_list', list(active_users.keys()), broadcast=True)


@socketio.on('search_users')
def search_users(data):
    query = data.get('query', '').strip().lower()
    me    = session.get('username')
    results = [u for u in active_users if query in u.lower() and u != me]
    emit('search_results', {'results': results})


@socketio.on('get_history')
def get_history(data):
    me   = session.get('username')
    peer = data.get('peer')
    if not me or not peer:
        return
    key     = room_key(me, peer)
    history = chat_history.get(key, [])
    emit('chat_history', {'peer': peer, 'messages': history})


@socketio.on('send_message')
def send_message(data):
    sender    = session.get('username')
    recipient = data.get('recipient')
    message   = data.get('message', '').strip()

    if not sender:
        emit('error', {'message': 'Session expired. Please refresh.'})
        return
    if not message:
        return
    if recipient not in active_users:
        emit('error', {'message': f'{recipient} is no longer online.'})
        return

    key = room_key(sender, recipient)
    msg = {
        'from':      sender,
        'to':        recipient,
        'message':   message,
        'timestamp': int(time.time() * 1000)
    }
    chat_history.setdefault(key, []).append(msg)

    emit('receive_message', msg, to=active_users[recipient])
    emit('receive_message', msg)


if __name__ == '__main__':
    socketio.run(app, debug=True)
