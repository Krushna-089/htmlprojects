from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SESSION_TYPE'] = 'filesystem'

# Use threading for simpler async mode
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Simple user database
USERS = {
    'user1': {'password': 'pass1', 'name': 'Alice', 'id': 1},
    'user2': {'password': 'pass2', 'name': 'Bob', 'id': 2}
}

# Track online users and their socket IDs
online_users = {}  # user_id -> socket_id
user_sessions = {}  # socket_id -> user_id

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if username in USERS and USERS[username]['password'] == password:
        session['user_id'] = USERS[username]['id']
        session['username'] = USERS[username]['name']
        return redirect(url_for('dashboard'))
    
    return 'Invalid credentials', 401

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    current_user = session['user_id']
    other_user = 2 if current_user == 1 else 1
    other_name = USERS['user1' if other_user == 1 else 'user2']['name']
    
    return render_template('dashboard.html', 
                         current_user=current_user,
                         other_user=other_user,
                         other_name=other_name)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user_id = session['user_id']
        online_users[user_id] = request.sid
        user_sessions[request.sid] = user_id
        print(f"User {user_id} ({session['username']}) connected")
        
        # Notify other user
        other_id = 2 if user_id == 1 else 1
        if other_id in online_users:
            emit('user_online', {'user_id': user_id, 'name': session['username']}, 
                 room=online_users[other_id])

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in user_sessions:
        user_id = user_sessions[request.sid]
        username = session.get('username', 'Unknown')
        del user_sessions[request.sid]
        if user_id in online_users:
            del online_users[user_id]
        
        # Notify other user
        other_id = 2 if user_id == 1 else 1
        if other_id in online_users:
            emit('user_offline', {'user_id': user_id, 'name': username}, 
                 room=online_users[other_id])

@socketio.on('private_message')
def handle_private_message(data):
    """Handle chat messages"""
    if 'user_id' not in session:
        return
    
    sender_id = session['user_id']
    recipient_id = data['to']
    message = data['message']
    
    if recipient_id in online_users:
        emit('new_message', {
            'from': sender_id,
            'from_name': session['username'],
            'message': message,
            'timestamp': data.get('timestamp')
        }, room=online_users[recipient_id])
        
        # Also send back to sender for confirmation
        emit('message_sent', {
            'to': recipient_id,
            'message': message,
            'timestamp': data.get('timestamp')
        })

# WebRTC Signaling
@socketio.on('call_user')
def handle_call(data):
    """Initiate a call (video or audio)"""
    if 'user_id' not in session:
        return
    
    caller_id = session['user_id']
    callee_id = data['to']
    call_type = data['type']
    
    if callee_id in online_users:
        emit('incoming_call', {
            'from': caller_id,
            'from_name': session['username'],
            'type': call_type
        }, room=online_users[callee_id])
    else:
        emit('user_offline', {'message': 'User is offline'})

@socketio.on('accept_call')
def handle_accept_call(data):
    """Callee accepts the call"""
    if 'user_id' not in session:
        return
    
    caller_id = data['from']
    callee_id = session['user_id']
    
    if caller_id in online_users:
        emit('call_accepted', {
            'by': callee_id,
            'by_name': session['username']
        }, room=online_users[caller_id])

@socketio.on('reject_call')
def handle_reject_call(data):
    """Callee rejects the call"""
    if 'user_id' not in session:
        return
    
    caller_id = data['from']
    
    if caller_id in online_users:
        emit('call_rejected', {
            'by': session['user_id'],
            'by_name': session['username']
        }, room=online_users[caller_id])

@socketio.on('end_call')
def handle_end_call(data):
    """End an ongoing call"""
    if 'user_id' not in session:
        return
    
    other_id = data['to']
    if other_id in online_users:
        emit('call_ended', {
            'by': session['user_id'],
            'by_name': session['username']
        }, room=online_users[other_id])

# WebRTC peer connection signaling
@socketio.on('offer')
def handle_offer(data):
    """Forward WebRTC offer to callee"""
    if 'user_id' not in session:
        return
    
    target_id = data['to']
    if target_id in online_users:
        emit('offer', {
            'offer': data['offer'],
            'from': session['user_id'],
            'from_name': session['username']
        }, room=online_users[target_id])

@socketio.on('answer')
def handle_answer(data):
    """Forward WebRTC answer to caller"""
    if 'user_id' not in session:
        return
    
    target_id = data['to']
    if target_id in online_users:
        emit('answer', {
            'answer': data['answer'],
            'from': session['user_id'],
            'from_name': session['username']
        }, room=online_users[target_id])

@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    """Forward ICE candidate to peer"""
    if 'user_id' not in session:
        return
    
    target_id = data['to']
    if target_id in online_users:
        emit('ice-candidate', {
            'candidate': data['candidate'],
            'from': session['user_id']
        }, room=online_users[target_id])

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=10000)
