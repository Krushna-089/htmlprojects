
import json
import time
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from collections import defaultdict

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# Load users from JSON
try:
    with open('users.json') as f:
        USERS = {u['username']: u['password'] for u in json.load(f)}
except:
    # Fallback users if file not found
    USERS = {
        'alice': 'alice123',
        'bob': 'bob123',
        'charlie': 'charlie123',
        'david': 'david123',
        'eve': 'eve123'
    }

# In‑memory state
online_users = set()
user_sessions = {}
user_call_status = {}
user_messages = defaultdict(list)
user_call_events = defaultdict(list)

# -------------------------------------------------------------------
def clean_stale_users():
    """Remove users who haven't pinged in last 60 seconds"""
    now = time.time()
    stale = [u for u, last in list(user_sessions.items()) if now - last > 60]
    for u in stale:
        if u in online_users:
            online_users.remove(u)
        if u in user_call_status:
            other = user_call_status[u]
            if other and other in online_users:
                user_call_status[other] = None
                user_call_events[other].append({'type': 'call_ended', 'from': u})
            del user_call_status[u]
        if u in user_sessions:
            del user_sessions[u]

# -------------------------------------------------------------------
@app.route('/')
def index():
    if 'username' in session:
        return render_template('index.html', username=session['username'])
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USERS and USERS[username] == password:
            session['username'] = username
            session.permanent = True
            online_users.add(username)
            user_sessions[username] = time.time()
            if username not in user_call_status:
                user_call_status[username] = None
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'username' in session:
        username = session.pop('username')
        if username in online_users:
            online_users.remove(username)
        if username in user_call_status:
            other = user_call_status[username]
            if other and other in online_users:
                user_call_status[other] = None
                user_call_events[other].append({'type': 'call_ended', 'from': username})
            del user_call_status[username]
        if username in user_sessions:
            del user_sessions[username]
    return redirect(url_for('login'))

@app.route('/api/ping', methods=['POST'])
def ping():
    """Keep session alive"""
    username = session.get('username')
    if username:
        user_sessions[username] = time.time()
    return jsonify({'status': 'ok'})

@app.route('/api/users')
def get_users():
    clean_stale_users()
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    users_list = []
    for u in online_users:
        if u != username:
            users_list.append({
                'username': u,
                'in_call_with': user_call_status.get(u)
            })
    return jsonify(users_list)

@app.route('/api/send_message', methods=['POST'])
def send_message():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    to = data.get('to')
    msg = data.get('message')
    
    if not to or not msg:
        return jsonify({'error': 'Missing fields'}), 400
    
    if to not in online_users:
        return jsonify({'error': 'User offline'}), 400
    
    user_messages[to].append({
        'from': username,
        'msg': msg,
        'timestamp': time.time()
    })
    return jsonify({'status': 'ok'})

@app.route('/api/get_messages')
def get_messages():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    messages = user_messages[username][:]
    user_messages[username].clear()
    return jsonify(messages)

# Call signaling endpoints
@app.route('/api/call/initiate', methods=['POST'])
def initiate_call():
    """Start a call - check if target is available"""
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    target = data.get('to')
    call_type = data.get('type')
    
    if target not in online_users:
        return jsonify({'error': 'User offline'}), 400
    
    if user_call_status.get(target) is not None:
        return jsonify({'busy': True, 'msg': f'{target} is talking with another'}), 409
    
    # Notify target of incoming call
    user_call_events[target].append({
        'type': 'incoming_call',
        'from': username,
        'call_type': call_type
    })
    
    return jsonify({'status': 'waiting'})

@app.route('/api/call/offer', methods=['POST'])
def call_offer():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    target = data.get('to')
    offer = data.get('offer')
    
    if target not in online_users:
        return jsonify({'error': 'User offline'}), 400
    
    user_call_events[target].append({
        'type': 'offer',
        'from': username,
        'offer': offer
    })
    return jsonify({'status': 'ok'})

@app.route('/api/call/answer', methods=['POST'])
def call_answer():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    target = data.get('to')
    answer = data.get('answer')
    
    if target not in online_users:
        return jsonify({'error': 'User offline'}), 400
    
    user_call_events[target].append({
        'type': 'answer',
        'from': username,
        'answer': answer
    })
    return jsonify({'status': 'ok'})

@app.route('/api/call/ice', methods=['POST'])
def call_ice():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    target = data.get('to')
    candidate = data.get('candidate')
    
    if target not in online_users:
        return jsonify({'error': 'User offline'}), 400
    
    user_call_events[target].append({
        'type': 'ice',
        'from': username,
        'candidate': candidate
    })
    return jsonify({'status': 'ok'})

@app.route('/api/call/accept', methods=['POST'])
def call_accept():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    caller = data.get('from')
    
    if caller not in online_users:
        return jsonify({'error': 'Caller offline'}), 400
    
    # Mark both as in call
    user_call_status[caller] = username
    user_call_status[username] = caller
    
    user_call_events[caller].append({
        'type': 'call_accepted',
        'from': username
    })
    return jsonify({'status': 'ok'})

@app.route('/api/call/reject', methods=['POST'])
def call_reject():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    caller = data.get('from')
    
    if caller in online_users:
        user_call_events[caller].append({
            'type': 'call_rejected',
            'from': username
        })
    return jsonify({'status': 'ok'})

@app.route('/api/call/hangup', methods=['POST'])
def call_hangup():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    other = user_call_status.get(username)
    if other and other in online_users:
        user_call_status[other] = None
        user_call_status[username] = None
        user_call_events[other].append({
            'type': 'call_ended',
            'from': username
        })
    else:
        user_call_status[username] = None
    
    return jsonify({'status': 'ok'})

@app.route('/api/call/events')
def get_call_events():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    events = user_call_events[username][:]
    user_call_events[username].clear()
    return jsonify(events)

# -------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
=======
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
if __name__ == "__main__":
    app.run()

