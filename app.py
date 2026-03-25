import json
import time
import os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from collections import defaultdict

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# -------------------------------------------------------------------
# Data handling functions with proper error handling
def load_users():
    try:
        if os.path.exists('users.json'):
            with open('users.json') as f:
                users_data = json.load(f)
            users = {}
            for u in users_data:
                users[u['username']] = {
                    'password': u['password'],
                    'role': u.get('role', 'normal'),
                    'balance': u.get('balance', 0.0)
                }
            return users
        else:
            # Create default users if file doesn't exist
            default_users = {
                'superadmin': {'password': 'super123', 'role': 'super_admin', 'balance': 0},
                'alice': {'password': 'alice123', 'role': 'admin', 'balance': 0},
                'bob': {'password': 'bob123', 'role': 'normal', 'balance': 10.0},
                'charlie': {'password': 'charlie123', 'role': 'normal', 'balance': 5.0},
                'david': {'password': 'david123', 'role': 'normal', 'balance': 2.0}
            }
            save_users(default_users)
            return default_users
    except Exception as e:
        print(f"Error loading users: {e}")
        # Fallback users
        return {
            'superadmin': {'password': 'super123', 'role': 'super_admin', 'balance': 0},
            'alice': {'password': 'alice123', 'role': 'admin', 'balance': 0},
            'bob': {'password': 'bob123', 'role': 'normal', 'balance': 10.0},
            'charlie': {'password': 'charlie123', 'role': 'normal', 'balance': 5.0}
        }

USERS = load_users()

def save_users(users_dict=None):
    if users_dict is None:
        users_dict = USERS
    users_list = [
        {'username': u, 'password': d['password'], 'role': d['role'], 'balance': d['balance']}
        for u, d in users_dict.items()
    ]
    try:
        with open('users.json', 'w') as f:
            json.dump(users_list, f, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

def load_calls():
    try:
        if os.path.exists('calls.json'):
            with open('calls.json') as f:
                content = f.read().strip()
                if content:  # Check if file is not empty
                    return json.loads(content)
                else:
                    return []
        return []
    except json.JSONDecodeError:
        print("Error decoding calls.json, returning empty list")
        return []
    except Exception as e:
        print(f"Error loading calls: {e}")
        return []

def save_calls(calls):
    try:
        with open('calls.json', 'w') as f:
            json.dump(calls, f, indent=2)
    except Exception as e:
        print(f"Error saving calls: {e}")

# Helper functions
def get_user_role(username):
    return USERS.get(username, {}).get('role', 'normal')

def get_user_balance(username):
    return USERS.get(username, {}).get('balance', 0.0)

def update_balance(username, amount):
    if username in USERS:
        USERS[username]['balance'] = round(USERS[username]['balance'] + amount, 2)
        save_users()
        return True
    return False

# -------------------------------------------------------------------
# In‑memory state
online_users = set()
user_sessions = {}
user_call_status = defaultdict(lambda: None)
user_messages = defaultdict(list)
user_call_events = defaultdict(list)
active_calls = {}          # key: caller (initiator), value: dict {callee, type, start_time}

# -------------------------------------------------------------------
def clean_stale_users():
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
# Authentication routes
@app.route('/')
def index():
    if 'username' in session:
        role = get_user_role(session['username'])
        if role == 'super_admin':
            return redirect(url_for('super_admin_dashboard'))
        elif role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('index.html', username=session['username'], role=role, balance=get_user_balance(session['username']))
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if 'username' in session and get_user_role(session['username']) == 'admin':
        return render_template('admin.html', username=session['username'], role='admin')
    return redirect(url_for('login'))

@app.route('/super_admin')
def super_admin_dashboard():
    if 'username' in session and get_user_role(session['username']) == 'super_admin':
        return render_template('super_admin.html', username=session['username'], role='super_admin')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USERS and USERS[username]['password'] == password:
            session['username'] = username
            session.permanent = True
            online_users.add(username)
            user_sessions[username] = time.time()
            if username not in user_call_status:
                user_call_status[username] = None
            role = USERS[username]['role']
            if role == 'super_admin':
                return redirect(url_for('super_admin_dashboard'))
            elif role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
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
        # Remove from active calls if any
        for caller, call in list(active_calls.items()):
            if caller == username or call['callee'] == username:
                del active_calls[caller]
    return redirect(url_for('login'))

# -------------------------------------------------------------------
# API endpoints
@app.route('/api/ping', methods=['POST'])
def ping():
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

    role = get_user_role(username)
    users_list = []
    for u in online_users:
        if u == username:
            continue
        # Filter based on role
        u_role = get_user_role(u)
        if role == 'normal' and u_role != 'admin':
            continue
        if role == 'admin' and u_role != 'normal':
            continue
        # super_admin sees all
        users_list.append({
            'username': u,
            'in_call_with': user_call_status.get(u),
            'role': u_role
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

# -------------------------------------------------------------------
# Balance and stats
@app.route('/api/user/balance')
def get_balance():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'balance': get_user_balance(username)})

@app.route('/api/user/add_balance', methods=['POST'])
def add_balance():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    
    role = get_user_role(username)
    if role != 'normal':
        return jsonify({'error': 'Only normal users can add balance'}), 403
    
    data = request.get_json()
    amount = data.get('amount', 0)
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({'error': 'Amount must be positive'}), 400
        update_balance(username, amount)
        return jsonify({'status': 'ok', 'new_balance': get_user_balance(username)})
    except:
        return jsonify({'error': 'Invalid amount'}), 400

@app.route('/api/admin/stats')
def admin_stats():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Not logged in'}), 401
    role = get_user_role(username)
    if role not in ['admin', 'super_admin']:
        return jsonify({'error': 'Unauthorized'}), 403

    calls = load_calls()
    
    if role == 'super_admin':
        # For each admin, total time spent with normal users
        stats = {}
        for call in calls:
            if call.get('caller_role') == 'admin' and call.get('callee_role') == 'normal':
                admin = call.get('caller')
                stats[admin] = stats.get(admin, 0) + call.get('duration', 0)
            elif call.get('caller_role') == 'normal' and call.get('callee_role') == 'admin':
                admin = call.get('callee')
                stats[admin] = stats.get(admin, 0) + call.get('duration', 0)
        
        # Format as hh:mm:ss
        result = {}
        for admin, seconds in stats.items():
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            result[admin] = f"{h:02d}:{m:02d}:{s:02d}"
        return jsonify(result)
    else:
        # For admin, own stats with normal users
        stats = {'total_duration': 0, 'calls': []}
        for call in calls:
            if call.get('caller') == username or call.get('callee') == username:
                if (call.get('caller_role') == 'admin' and call.get('callee_role') == 'normal') or \
                   (call.get('caller_role') == 'normal' and call.get('callee_role') == 'admin'):
                    stats['total_duration'] += call.get('duration', 0)
                    stats['calls'].append(call)
        seconds = stats['total_duration']
        stats['total_duration_formatted'] = f"{int(seconds//3600):02d}:{int((seconds%3600)//60):02d}:{int(seconds%60):02d}"
        return jsonify(stats)

# -------------------------------------------------------------------
# Call signaling endpoints
@app.route('/api/call/initiate', methods=['POST'])
def initiate_call():
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

    caller_role = get_user_role(username)
    callee_role = get_user_role(target)

    # Role restrictions
    if caller_role == 'normal' and callee_role != 'admin':
        return jsonify({'error': 'Normal users can only call admins'}), 403
    if caller_role == 'admin' and callee_role != 'normal':
        return jsonify({'error': 'Admin users can only call normal users'}), 403
    # Super admin can call anyone

    # Balance check for normal caller
    if caller_role == 'normal':
        balance = get_user_balance(username)
        min_cost = 0.6 if call_type == 'audio' else 1.2
        if balance < min_cost:
            return jsonify({'error': f'Insufficient balance. Need at least ₹{min_cost} to start a call'}), 402

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
    call_type = data.get('call_type', 'audio')
    
    if caller not in online_users:
        return jsonify({'error': 'Caller offline'}), 400

    # Mark both as in call
    user_call_status[caller] = username
    user_call_status[username] = caller

    # Store call session
    active_calls[caller] = {
        'callee': username,
        'type': call_type,
        'start_time': time.time()
    }

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

    # Find which call session involves this user
    session_key = None
    call_data = None
    for caller, data in list(active_calls.items()):
        if caller == username or data['callee'] == username:
            session_key = caller
            call_data = data
            break

    if session_key and call_data:
        # Compute duration
        end_time = time.time()
        start_time = call_data['start_time']
        duration = end_time - start_time

        # Determine caller and callee
        caller = session_key
        callee = call_data['callee']
        call_type = call_data['type']
        caller_role = get_user_role(caller)
        callee_role = get_user_role(callee)

        # Compute cost (only if caller is normal and not super admin)
        cost = 0.0
        if caller_role == 'normal':
            rate = 0.6 if call_type == 'audio' else 1.2
            cost = round((duration / 60.0) * rate, 2)
            # Deduct from caller's balance
            update_balance(caller, -cost)

        # Save call record
        calls = load_calls()
        calls.append({
            'caller': caller,
            'callee': callee,
            'call_type': call_type,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'cost': cost,
            'caller_role': caller_role,
            'callee_role': callee_role
        })
        save_calls(calls)

        # Clean up
        del active_calls[session_key]

    # Notify other party
    other = user_call_status.get(username)
    if other and other in online_users:
        user_call_status[other] = None
        user_call_events[other].append({
            'type': 'call_ended',
            'from': username
        })
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
    # Ensure calls.json exists
    if not os.path.exists('calls.json'):
        with open('calls.json', 'w') as f:
            json.dump([], f)
    
    # Ensure users.json exists
    if not os.path.exists('users.json'):
        save_users()
    
    app.run(debug=True, host='0.0.0.0', port=5000)
