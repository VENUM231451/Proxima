# --------------------------
# app.py
# Complete queue system (single file) - Render-ready
# - Special Pass removed everywhere
# - PTPTN and EMGS Bank Letter hidden from user side only
# - Admin joins all_counters room and receives live updates
# - Uses SECRET_KEY and PORT from environment (Render-ready)
# - DING sound plays on display (and user ticket) with static fallback
# - User must enter First + Last name before seeing services
# - Names saved in names.txt (no duplicates, case-insensitive)
# - Admin can clear names with a button
# - "Medical Insurance" label changed to "Medical Insurance Inquiry" on user side
# - COUNTER PAGE: shows Next in Line (first waiting ticket) live
# --------------------------

import os
import eventlet
eventlet.monkey_patch()

from flask import Flask, request, redirect, render_template_string, url_for, session
from flask_socketio import SocketIO, emit, join_room
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "secret!")
socketio = SocketIO(app, async_mode='eventlet')

# ------------------ DATA ------------------
queue = {
    "Passport Submission": [],
    "Passport Collection": [],
    "I-Kad Collection": [],
    "Medical Insurance Inquiry": [],
    "EMGS Bank Letter": [],   # admin-only on user side
    "PTPTN": []               # admin-only on user side
}

ticket_prefixes = {
    "Passport Submission": "PS",
    "Passport Collection": "PC",
    "I-Kad Collection": "IK",
    "Medical Insurance Inquiry": "MI",
    "EMGS Bank Letter": "BL",
    "PTPTN": "PT"
}

category_counters = {k: 0 for k in queue.keys()}
counters = {}  # counter_id -> dict: name, categories, current_ticket

# Categories shown to users (Special Pass removed; EMGS & PTPTN hidden)
user_categories = [
    "Passport Submission",
    "Passport Collection",
    "I-Kad Collection",
    "Medical Insurance Inquiry"
]

# ------------------ HELPERS: save/load/clear names ------------------

NAMES_FILE = "names.txt"

def save_user_name(first, last):
    """Save full name into names.txt (one per line). Prevent duplicates (case-insensitive)."""
    full = f"{first.strip()} {last.strip()}".strip()
    if not full:
        return
    # Ensure file exists
    if not os.path.exists(NAMES_FILE):
        open(NAMES_FILE, "a", encoding="utf-8").close()
    # Read existing names (case-insensitive set)
    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            existing = {line.strip().lower() for line in f if line.strip()}
    except FileNotFoundError:
        existing = set()
    if full.lower() not in existing:
        with open(NAMES_FILE, "a", encoding="utf-8") as f:
            f.write(full + "\n")

def load_user_names():
    """Return list of stored full names (preserve original capitalization)."""
    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

def clear_user_names():
    """Clear the names file."""
    open(NAMES_FILE, "w", encoding="utf-8").close()

# ------------------ TEMPLATES ------------------

username_template = """
<!DOCTYPE html>
<html>
<head>
<title>Enter Your Name</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Inter,Arial,Helvetica,sans-serif;background:#f0f4f8;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.container{background:white;padding:28px;border-radius:12px;box-shadow:0 6px 30px rgba(10,20,40,0.08);text-align:center;width:360px}
h1{color:#0D3B66;margin-bottom:16px;font-size:22px}
input{display:block;width:100%;padding:12px;margin:10px 0;border-radius:8px;border:1px solid #ccc;font-size:16px}
button{padding:12px;width:100%;border:none;border-radius:8px;background:#0D3B66;color:white;font-size:16px;cursor:pointer}
button:hover{background:#08457e}
.note{font-size:13px;color:#666;margin-top:10px}
</style>
</head>
<body>
<div class="container">
  <h1>Please Enter Your Name</h1>
  <form method="POST" action="/">
    <input type="text" name="first_name" placeholder="First Name" required>
    <input type="text" name="last_name" placeholder="Last Name" required>
    <button type="submit">Continue</button>
  </form>
  <div class="note">Both fields are required. We'll save your name so staff can see who registered.</div>
</div>
</body>
</html>
"""

user_template = """
<!DOCTYPE html>
<html>
<head>
<title>Service Selection</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--brand:#0D3B66;--brand-dark:#08457e;background:#f0f4f8}
body{font-family:Inter,Arial,Helvetica,sans-serif;background:var(--brand-light,#f0f4f8);margin:0;padding:0;display:flex;align-items:center;justify-content:center;height:100vh}
.container{width:360px;background:white;padding:28px;border-radius:12px;box-shadow:0 6px 30px rgba(10,20,40,0.08);text-align:center}
h1{color:var(--brand);margin:0 0 16px;font-size:22px}
.service-btn{display:block;width:100%;padding:14px;margin:10px 0;border-radius:8px;border:none;background:var(--brand);color:#fff;font-size:16px;cursor:pointer}
.service-btn:hover{background:var(--brand-dark)}
.small{font-size:13px;color:#666;margin-top:8px}
</style>
</head>
<body>
<div class="container">
  <h1>Please select a service</h1>
  {% for cat in categories %}
    <button class="service-btn" onclick="selectService('{{ cat }}')">{{ cat }}</button>
  {% endfor %}
  <div class="small">After selecting, you'll get a ticket number and estimated wait time.</div>
</div>

<script>
function selectService(category){
    location.href = "/ticket_page/" + encodeURIComponent(category);
}
</script>
</body>
</html>
"""

ticket_page_template = """
<!DOCTYPE html>
<html>
<head>
<title>Your Ticket</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Inter,Arial,Helvetica,sans-serif;background:#f0f4f8;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.card{background:white;padding:32px;border-radius:12px;box-shadow:0 8px 30px rgba(10,20,40,0.08);text-align:center;width:420px}
h1{color:#0D3B66;margin:0 0 8px}
#ticket_number{font-size:42px;color:#0D3B66;margin:8px 0}
.info{color:#333;margin:6px 0}
.small{color:#666;margin-top:10px}
</style>
</head>
<body>
<div class="card">
  <h1>Your Ticket</h1>
  <div id="ticket_number">{{ ticket.id }}</div>
  <div class="info">Service: <strong>{{ ticket.category }}</strong></div>
  <div id="waiting" class="info">Waiting Time: calculating...</div>
  <div id="counter_info" class="info">Assigned Counter: Not yet</div>
  <div class="small">Please wait — you will be notified when your ticket is called.</div>
</div>

<!-- ticket ding audio element (uses static/ding.mp3 if present; fallback handled in JS) -->
<audio id="ticket-ding" src="{{ ding_url }}"></audio>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
var socket = io();
var ticketId = "{{ ticket.id }}";
socket.emit("join_ticket_room", {ticket_id: ticketId});

// ticket ding element & fallback
var ticketDing = document.getElementById('ticket-ding');
ticketDing.preload = "auto";
ticketDing.addEventListener('error', function(){
    ticketDing.src = "https://www.soundjay.com/buttons/sounds/button-16.mp3";
    ticketDing.load();
});

function updateWaiting(){
    fetch('/ticket_wait_time/' + ticketId)
    .then(r => r.json())
    .then(data => {
        document.getElementById('waiting').innerText = "Waiting Time: " + data.waiting_time + " minutes";
    });
}
setInterval(updateWaiting, 5000);
updateWaiting();

socket.on("ticket_called", function(data){
    if(data.id === ticketId){
        try { ticketDing.currentTime = 0; ticketDing.play().catch(()=>{}); } catch(e){}
        document.getElementById('counter_info').innerText = "Assigned Counter: " + data.counter_name;
        alert("Ticket " + ticketId + " is being served at " + data.counter_name);
    }
});
</script>
</body>
</html>
"""

counter_template = """
<!DOCTYPE html>
<html>
<head>
<title>Counter - {{ counter.name }}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Inter,Arial,Helvetica,sans-serif;background:#f0f4f8;margin:0;padding:20px}
.header{display:flex;align-items:center;justify-content:space-between}
h1{color:#0D3B66;margin:0}
.box{background:white;padding:18px;border-radius:10px;box-shadow:0 6px 20px rgba(10,20,40,0.06);margin-top:16px}
button{background:#0D3B66;color:white;border:none;padding:12px 18px;border-radius:8px;cursor:pointer}
button:hover{background:#08457e}
#current_ticket{font-size:20px;color:#0D3B66;margin-top:10px}
#next_in_line{font-size:16px;color:#333;margin-top:6px}
ul{padding-left:18px}
</style>
</head>
<body>
<div class="header">
  <h1>Counter: {{ counter.name }}</h1>
  <div><strong>Services:</strong> {{ counter.categories|join(", ") }}</div>
</div>

<div class="box">
  <div id="current_ticket">No ticket being served</div>
  <div id="next_in_line">Next: None</div>
  <h3>Waiting Queue</h3>
  <ul id="queue_list"></ul>
  <button onclick="callNext()">Call Next</button>
</div>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
var socket = io();
var counterId = "{{ counter_id }}";
socket.emit("join_counter_room", {counter_id: counterId});

// update UI when queue_update arrives
socket.on("queue_update", function(data){
    var c = data.counters[counterId];
    if(!c){
        document.getElementById('current_ticket').innerText = "No ticket being served";
        document.getElementById('next_in_line').innerText = "Next: None";
        document.getElementById('queue_list').innerHTML = "";
        return;
    }
    document.getElementById('current_ticket').innerText = c.current_ticket ? "Serving: " + c.current_ticket : "No ticket being served";

    var waiting = [];
    for(var i=0; i < c.categories.length; i++){
        var cat = c.categories[i];
        var catQueue = data.queue[cat] || [];
        for(var j=0; j<catQueue.length; j++){
            waiting.push(catQueue[j]);
        }
    }

    // Next in line is the first waiting item's id (if any)
    var next = waiting.length > 0 ? waiting[0].id : "None";
    document.getElementById('next_in_line').innerText = "Next: " + next;

    var qlist = document.getElementById('queue_list');
    qlist.innerHTML = "";
    for(var k=0; k<waiting.length; k++){
        var li = document.createElement("li");
        li.innerText = waiting[k].id + " (" + waiting[k].category + ")";
        qlist.appendChild(li);
    }
});

function callNext(){
    socket.emit("call_next", {counter_id: counterId});
}
</script>
</body>
</html>
"""

display_template = """
<!DOCTYPE html>
<html>
<head>
<title>Now Serving</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Inter,Arial,Helvetica,sans-serif;background:#0D3B66;color:white;margin:0;padding:20px}
.container{max-width:1000px;margin:0 auto}
.header{text-align:center;padding:12px}
.header h1{margin:0;font-size:36px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:20px}
.card{background:white;color:#0D3B66;padding:18px;border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:120px}
.counter-name{font-size:18px;font-weight:600}
.ticket-number{font-size:36px;margin-top:8px}
</style>
</head>
<body>
<div class="container">
  <div class="header"><h1>Now Serving</h1></div>
  <!-- audio element uses ding_url passed from Flask; fallback handled in JS -->
  <audio id="display-ding" src="{{ ding_url }}"></audio>
  <div class="grid" id="grid">
    {% for cid,c in counters.items() %}
      <div class="card" id="{{ cid }}">
        <div class="counter-name">{{ c.name }}</div>
        <div class="ticket-number">{{ c.current_ticket or "None" }}</div>
      </div>
    {% endfor %}
  </div>
</div>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
var socket = io();
socket.emit("join_display_room");

// DING audio element (static fallback -> external)
var dingElem = document.getElementById('display-ding');
dingElem.preload = "auto";
dingElem.addEventListener('error', function(){
    dingElem.src = "https://www.soundjay.com/buttons/sounds/button-16.mp3";
    dingElem.load();
});
var last = {};

socket.on("display_update", function(data){
    for(var cid in data){
        var item = data[cid];
        var el = document.getElementById(cid);
        if(!el){
            var grid = document.getElementById('grid');
            var card = document.createElement('div');
            card.className = 'card';
            card.id = cid;
            card.innerHTML = '<div class="counter-name">'+item.name+'</div><div class="ticket-number">'+(item.current_ticket||'None')+'</div>';
            grid.appendChild(card);
            last[cid] = item.current_ticket || 'None';
            continue;
        }
        var shown = item.current_ticket || 'None';
        var ticketDiv = el.querySelector('.ticket-number');
        if((last[cid] || 'None') !== shown && shown !== 'None'){
            try { dingElem.currentTime = 0; dingElem.play().catch(()=>{}); } catch(e){}
        }
        ticketDiv.innerText = shown;
        last[cid] = shown;
    }
});
</script>
</body>
</html>
"""

admin_template = """
<!DOCTYPE html>
<html>
<head>
<title>Admin Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Inter,Arial,Helvetica,sans-serif;background:#f0f4f8;margin:0;padding:20px}
.header{display:flex;align-items:center;justify-content:space-between}
h1{color:#0D3B66;margin:0}
.form{background:white;padding:16px;border-radius:10px;box-shadow:0 6px 20px rgba(10,20,40,0.06);margin-top:14px}
table{width:100%;border-collapse:collapse;margin-top:14px}
th,td{padding:10px;border:1px solid #e6e9ee;text-align:center}
button{padding:8px 12px;border-radius:8px;border:none;background:#0D3B66;color:white;cursor:pointer}
button:hover{background:#08457e}
.checkbox-list{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.checkbox-list label{background:#fff;padding:6px 8px;border-radius:6px;border:1px solid #ddd}
.names-list{margin-top:18px;background:#fff;padding:12px;border-radius:8px;border:1px solid #e6e9ee}
.clear-btn{background:#c0392b;margin-left:8px}
.clear-btn:hover{background:#a93226}
</style>
</head>
<body>
<div class="header">
  <h1>Admin Dashboard</h1>
  <div style="display:flex;align-items:center;gap:10px">
    <a href="/display" target="_blank">Open Display</a>
    <form action="/admin/clear_names" method="post" style="display:inline;margin:0">
      <button type="submit" class="clear-btn">Clear Names</button>
    </form>
  </div>
</div>

<div class="form">
  <form action="/admin/add_counter" method="post">
    <input type="text" name="name" placeholder="Counter name (eg Counter 1)" required>
    <div class="checkbox-list">
      {% for cat in categories %}
        <label><input type="checkbox" name="categories" value="{{ cat }}"> {{ cat }}</label>
      {% endfor %}
    </div>
    <div style="margin-top:10px">
      <button type="submit">Add Counter</button>
    </div>
  </form>
</div>

<h3>Existing Counters</h3>
<table id="counter_table">
<tr><th>Counter Name</th><th>Services</th><th>Current Ticket</th><th>Counter Link</th><th>Actions</th></tr>
{% for cid,c in counters.items() %}
<tr id="row_{{ cid }}">
  <td>{{ c['name'] }}</td>
  <td>{{ c['categories']|join(", ") }}</td>
  <td id="current_{{ cid }}">{{ c['current_ticket'] or "None" }}</td>
  <td><a href="/counter/{{ cid }}" target="_blank">Open Counter</a></td>
  <td><button onclick="deleteCounter('{{ cid }}')">Delete</button></td>
</tr>
{% endfor %}
</table>

<div class="names-list">
  <h3>Registered Users</h3>
  {% if names %}
    <ul>
      {% for name in names %}
        <li>{{ name }}</li>
      {% endfor %}
    </ul>
  {% else %}
    <p>No users have registered yet.</p>
  {% endif %}
</div>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
var socket = io();
// join admin room
socket.emit("join_admin");

function deleteCounter(id){
    if(!confirm("Delete counter?")) return;
    fetch("/admin/delete_counter/"+id, {method:"POST"})
    .then(()=>{/* server will emit update */});
}

socket.on("queue_update", function(data){
    var table = document.getElementById('counter_table');
    table.innerHTML = "<tr><th>Counter Name</th><th>Services</th><th>Current Ticket</th><th>Counter Link</th><th>Actions</th></tr>";
    for(var cid in data.counters){
        var c = data.counters[cid];
        var row = table.insertRow();
        row.insertCell(0).innerText = c.name;
        row.insertCell(1).innerText = c.categories.join(", ");
        row.insertCell(2).innerText = c.current_ticket || "None";
        var linkCell = row.insertCell(3);
        var a = document.createElement('a'); a.href = "/counter/" + cid; a.target="_blank"; a.innerText = "Open Counter";
        linkCell.appendChild(a);
        var actions = row.insertCell(4);
        var btn = document.createElement('button'); btn.innerText = "Delete";
        btn.onclick = (function(id){ return function(){ deleteCounter(id); }; })(cid);
        actions.appendChild(btn);
    }
});
</script>
</body>
</html>
"""

# ------------------ LOGIC ------------------

def generate_ticket(category):
    category_counters[category] += 1
    tid = f"{ticket_prefixes[category]}-{category_counters[category]:03d}"
    ticket = {"id": tid, "category": category}
    queue[category].append(ticket)
    # notify counters and admin
    socketio.emit("queue_update", get_full_state(), room="all_counters")
    return ticket

def get_display_state():
    return counters

def get_full_state():
    qcopy = {cat: [t.copy() for t in lst] for cat, lst in queue.items()}
    ccopy = {cid: c.copy() for cid, c in counters.items()}
    return {"queue": qcopy, "counters": ccopy}

def call_next_ticket(counter_id):
    counter = counters.get(counter_id)
    if not counter:
        return
    for cat in counter['categories']:
        if queue.get(cat) and len(queue[cat]) > 0:
            next_ticket = queue[cat].pop(0)
            counter['current_ticket'] = next_ticket['id']
            # notify the user who holds this ticket (room with ticket id)
            socketio.emit("ticket_called", {"id": next_ticket['id'], "counter_name": counter['name']}, room=next_ticket['id'])
            break
    else:
        counter['current_ticket'] = None
    # update display and all counters/admin
    socketio.emit("display_update", get_display_state(), room="display")
    socketio.emit("queue_update", get_full_state(), room="all_counters")

# ------------------ ROUTES ------------------

@app.route("/", methods=["GET", "POST"])
def username_page():
    # if user has already entered name, redirect to services
    if request.method == "GET":
        if session.get("user_name"):
            return redirect("/services")
        return render_template_string(username_template)

    # POST -> save name and redirect to services
    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    if not first or not last:
        # if missing redirect back (template has required fields but double-check)
        return redirect("/")
    save_user_name(first, last)
    session["user_name"] = f"{first} {last}"
    return redirect("/services")

@app.route("/services")
def user_home():
    # ensure user provided name first
    if not session.get("user_name"):
        return redirect("/")
    return render_template_string(user_template, categories=user_categories)

@app.route("/ticket_page/<category>")
def ticket_page(category):
    # restrict direct access if no name in session
    if not session.get("user_name"):
        return redirect("/")
    # Protect: if a user navigates manually to a category that isn't shown, still allow if exists.
    if category not in queue:
        return "Invalid service", 404
    ticket = generate_ticket(category)
    # pass ding_url (static) into template so audio uses it
    ding_url = url_for('static', filename='ding.mp3')
    return render_template_string(ticket_page_template, ticket=ticket, ding_url=ding_url)

@app.route("/ticket_wait_time/<ticket_id>")
def ticket_wait_time(ticket_id):
    # compute simple estimate: 5 minutes per person ahead (search queue for ticket)
    for cat in queue:
        for i, t in enumerate(queue[cat]):
            if t['id'] == ticket_id:
                return {"waiting_time": i * 5}
    return {"waiting_time": 0}

@app.route("/display")
def display_page():
    ding_url = url_for('static', filename='ding.mp3')
    return render_template_string(display_template, counters=get_display_state(), ding_url=ding_url)

@app.route("/admin")
def admin_page():
    # admins can see all categories (including EMGS & PTPTN)
    names = load_user_names()
    return render_template_string(admin_template, counters=counters, categories=list(queue.keys()), names=names)

@app.route("/admin/add_counter", methods=["POST"])
def add_counter():
    name = request.form.get('name', '').strip()
    cats = request.form.getlist('categories')
    if not name:
        return redirect("/admin")
    counter_id = str(uuid.uuid4())
    counters[counter_id] = {"name": name, "categories": cats, "current_ticket": None}
    # send updates
    socketio.emit("display_update", get_display_state(), room="display")
    socketio.emit("queue_update", get_full_state(), room="all_counters")
    return redirect("/admin")

@app.route("/admin/delete_counter/<counter_id>", methods=["POST"])
def delete_counter(counter_id):
    if counter_id in counters:
        del counters[counter_id]
        socketio.emit("display_update", get_display_state(), room="display")
        socketio.emit("queue_update", get_full_state(), room="all_counters")
    return ("", 200)

@app.route("/admin/clear_names", methods=["POST"])
def admin_clear_names():
    clear_user_names()
    return redirect("/admin")

@app.route("/counter/<counter_id>")
def counter_page(counter_id):
    if counter_id not in counters:
        return "Counter not found", 404
    return render_template_string(counter_template, counter=counters[counter_id], counter_id=counter_id)

# ------------------ SOCKET EVENTS ------------------

@socketio.on("join_ticket_room")
def join_ticket_room(data):
    ticket_id = data.get('ticket_id')
    if ticket_id:
        join_room(ticket_id)

@socketio.on("join_display_room")
def join_display_room():
    join_room("display")
    emit("display_update", get_display_state(), to=request.sid)

@socketio.on("join_counter_room")
def join_counter_room(data):
    # counters and admin use this 'all_counters' room for live updates
    join_room("all_counters")
    emit("queue_update", get_full_state(), to=request.sid)

@socketio.on("join_admin")
def join_admin():
    join_room("all_counters")
    emit("queue_update", get_full_state(), to=request.sid)

@socketio.on("call_next")
def handle_call_next(data):
    cid = data.get('counter_id')
    call_next_ticket(cid)
    emit("queue_update", get_full_state(), room="all_counters")

# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
