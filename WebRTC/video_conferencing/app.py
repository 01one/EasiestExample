# pip install Flask flask-socketio
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    print('User connected')

@socketio.on('disconnect')
def on_disconnect():
    print('User disconnected')

@socketio.on('offer')
def on_offer(data):
    emit('offer', data, broadcast=True, include_self=False)

@socketio.on('answer')
def on_answer(data):
    emit('answer', data, broadcast=True, include_self=False)

@socketio.on('ice_candidate')
def on_ice_candidate(data):
    emit('ice_candidate', data, broadcast=True, include_self=False)

if __name__ == '__main__':
    socketio.run(app, debug=True)

