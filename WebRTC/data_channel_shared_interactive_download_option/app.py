from flask import Flask, render_template_string,render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import time
from flask import request

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

online_users = {} 
available_files = {} 
active_transfers = {}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def on_disconnect():
    print(f"Client disconnected: {request.sid}")
    
    if request.sid in online_users:
        username = online_users[request.sid]
        del online_users[request.sid]
        
        if username in available_files:
            del available_files[username]
        
        emit('users_updated', {
            'onlineUsers': list(online_users.values())
        }, broadcast=True)
        
        emit('files_updated', {
            'availableFiles': available_files
        }, broadcast=True)

@socketio.on('join_space')
def on_join_space(data):
    username = data['username'].strip()

    if username in online_users.values():
        emit('join_error', {'message': 'Username already taken'})
        return
    
    online_users[request.sid] = username
    available_files[username] = []
    
    join_room('sharing_space')
    
    emit('joined_space', {
        'username': username,
        'availableFiles': available_files,
        'onlineUsers': list(online_users.values())
    })
    
    emit('users_updated', {
        'onlineUsers': list(online_users.values())
    }, room='sharing_space', include_self=False)
    
    print(f"User {username} joined the sharing space")

@socketio.on('update_files')
def on_update_files(data):
    if request.sid not in online_users:
        return
    
    username = online_users[request.sid]
    available_files[username] = data['files']
    emit('files_updated', {
        'availableFiles': available_files
    }, room='sharing_space')
    
    print(f"User {username} updated their file list: {len(data['files'])} files")

@socketio.on('request_file')
def on_request_file(data):
    if request.sid not in online_users:
        return
    
    requester = online_users[request.sid]
    
    if 'fileId' in data:
        file_id = data['fileId']
        owner = data['owner']
        file_index = data['fileIndex']
        action = data['action']
    else:
        owner = data['owner']
        file_index = data['fileIndex']
        action = data['action']
    
    owner_sid = None
    for sid, username in online_users.items():
        if username == owner:
            owner_sid = sid
            break
    
    if not owner_sid:
        emit('file_request_error', {'message': 'File owner not found'})
        return
    
    transfer_id = str(uuid.uuid4())
    active_transfers[transfer_id] = {
        'requester': requester,
        'requester_sid': request.sid,
        'owner': owner,
        'owner_sid': owner_sid,
        'file_index': file_index,
        'action': action,
        'timestamp': time.time()
    }
    
    emit('file_request', {
        'requestId': transfer_id,
        'requester': requester,
        'fileIndex': file_index,
        'action': action
    }, room=owner_sid)
    
    print(f"File request: {requester} wants to {action} file from {owner}")

@socketio.on('file_request_response')
def on_file_request_response(data):
    request_id = data['requestId']
    accepted = data['accepted']
    
    if request_id not in active_transfers:
        return
    
    transfer_info = active_transfers[request_id]
    requester_sid = transfer_info['requester_sid']
    
    emit('file_request_response', {
        'requestId': request_id,
        'accepted': accepted,
        'action': transfer_info['action']
    }, room=requester_sid)
    
    if not accepted:
        del active_transfers[request_id]
        print(f"File request {request_id} was rejected")
    else:
        print(f"File request {request_id} for {transfer_info['action']} was accepted")

@socketio.on('offer')
def on_offer(data):
    transfer_id = data['transferId']
    
    if transfer_id not in active_transfers:
        return
    
    transfer_info = active_transfers[transfer_id]
    requester_sid = transfer_info['requester_sid']
    
    emit('offer', {
        'offer': data['offer'],
        'transferId': transfer_id
    }, room=requester_sid)

@socketio.on('answer')
def on_answer(data):
    transfer_id = data['transferId']
    
    if transfer_id not in active_transfers:
        return
    
    transfer_info = active_transfers[transfer_id]
    owner_sid = transfer_info['owner_sid']
    
    emit('answer', {
        'answer': data['answer'],
        'transferId': transfer_id
    }, room=owner_sid)

@socketio.on('ice_candidate')
def on_ice_candidate(data):
    transfer_id = data['transferId']
    
    if transfer_id not in active_transfers:
        return
    
    transfer_info = active_transfers[transfer_id]
    
    if request.sid == transfer_info['requester_sid']:

        emit('ice_candidate', {
            'candidate': data['candidate'],
            'transferId': transfer_id
        }, room=transfer_info['owner_sid'])
    else:
        emit('ice_candidate', {
            'candidate': data['candidate'],
            'transferId': transfer_id
        }, room=transfer_info['requester_sid'])

@socketio.on('cancel_transfer')
def on_cancel_transfer(transfer_id):
    if transfer_id in active_transfers:
        transfer_info = active_transfers[transfer_id]
        
        emit('transfer_cancelled', {'transferId': transfer_id}, 
             room=transfer_info['requester_sid'])
        emit('transfer_cancelled', {'transferId': transfer_id}, 
             room=transfer_info['owner_sid'])
        
        del active_transfers[transfer_id]
        print(f"Transfer {transfer_id} was cancelled")

@socketio.on('transfer_complete')
def on_transfer_complete(data):
    transfer_id = data['transferId']
    
    if transfer_id in active_transfers:
        del active_transfers[transfer_id]
        print(f"Transfer {transfer_id} completed successfully")

def cleanup_old_transfers():
    current_time = time.time()
    expired_transfers = []
    
    for transfer_id, transfer_info in active_transfers.items():
        if current_time - transfer_info['timestamp'] > 3600:
            expired_transfers.append(transfer_id)
    
    for transfer_id in expired_transfers:
        del active_transfers[transfer_id]
        print(f"Cleaned up expired transfer: {transfer_id}")

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
