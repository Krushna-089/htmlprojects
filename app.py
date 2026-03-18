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
