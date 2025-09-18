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

from flask import Flask, request, redirect, render_template_string, url_for, session, flash
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
<title>Enter Your Name | Proxima</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --primary-light: #dbeafe;
  --accent: #f97316;
  --text: #1e293b;
  --text-light: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --success: #10b981;
  --card-shadow: 0 10px 30px rgba(0,0,0,0.08);
  --transition: all 0.3s ease;
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  color: var(--text);
}
.container {
  background: var(--card-bg);
  padding: 2.5rem;
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
  text-align: center;
  width: 100%;
  max-width: 400px;
  margin: 1rem;
}
.logo {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 1.5rem;
  letter-spacing: -0.5px;
}
h1 {
  color: var(--text);
  margin-bottom: 1.5rem;
  font-size: 1.5rem;
  font-weight: 600;
}
input {
  display: block;
  width: 100%;
  padding: 0.875rem 1rem;
  margin: 0.75rem 0;
  border-radius: 0.5rem;
  border: 1px solid #e2e8f0;
  font-size: 1rem;
  transition: var(--transition);
  box-sizing: border-box;
}
input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}
button {
  width: 100%;
  padding: 0.875rem 1rem;
  border: none;
  border-radius: 0.5rem;
  background: var(--primary);
  color: white;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  margin-top: 0.5rem;
}
button:hover {
  background: var(--primary-dark);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
.note {
  font-size: 0.875rem;
  color: var(--text-light);
  margin-top: 1rem;
  line-height: 1.5;
}
</style>
</head>
<body>
<div class="container">
  <div class="logo">Proxima</div>
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
<title>Service Selection | Proxima</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --primary-light: #dbeafe;
  --accent: #f97316;
  --text: #1e293b;
  --text-light: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --success: #10b981;
  --danger: #ef4444;
  --card-shadow: 0 10px 30px rgba(0,0,0,0.08);
  --transition: all 0.3s ease;
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  color: var(--text);
}
.container {
  width: 100%;
  max-width: 400px;
  background: var(--card-bg);
  padding: 2.5rem;
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
  text-align: center;
  margin: 1rem;
}
.logo {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 1.5rem;
  letter-spacing: -0.5px;
}
h1 {
  color: var(--text);
  margin: 0 0 1.5rem;
  font-size: 1.5rem;
  font-weight: 600;
}
.service-btn {
  display: block;
  width: 100%;
  padding: 1rem 1.25rem;
  margin: 0.75rem 0;
  border-radius: 0.5rem;
  border: none;
  background: var(--primary);
  color: #fff;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: var(--transition);
  text-align: left;
  position: relative;
}
.service-btn:after {
  content: '→';
  position: absolute;
  right: 1.25rem;
  top: 50%;
  transform: translateY(-50%);
  transition: var(--transition);
}
.service-btn:hover {
  background: var(--primary-dark);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
.service-btn:hover:after {
  right: 1rem;
}
.small {
  font-size: 0.875rem;
  color: var(--text-light);
  margin-top: 1.5rem;
  line-height: 1.5;
}
.alert {
  background-color: #fee2e2;
  color: var(--danger);
  padding: 1rem;
  border-radius: 0.5rem;
  margin-bottom: 1.5rem;
  font-size: 0.875rem;
  text-align: left;
  border-left: 4px solid var(--danger);
}
</style>
</head>
<body>
<div class="container">
  <div class="logo">Proxima</div>
  <h1>Please select a service</h1>
  {% if messages %}
    {% for category, message in messages %}
      <div class="alert">{{ message }}</div>
    {% endfor %}
  {% endif %}
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
<title>Your Ticket | Proxima</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --primary-light: #dbeafe;
  --accent: #f97316;
  --text: #1e293b;
  --text-light: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --success: #10b981;
  --card-shadow: 0 10px 30px rgba(0,0,0,0.08);
  --transition: all 0.3s ease;
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  color: var(--text);
}
.card {
  background: var(--card-bg);
  padding: 2.5rem;
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
  text-align: center;
  width: 100%;
  max-width: 420px;
  margin: 1rem;
  position: relative;
  overflow: hidden;
}
.card:before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 0.25rem;
  background: var(--primary);
}
.logo {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 1.5rem;
  letter-spacing: -0.5px;
}
h1 {
  color: var(--text);
  margin: 0 0 1rem;
  font-size: 1.5rem;
  font-weight: 600;
}
#ticket_number {
  font-size: 3rem;
  color: var(--primary);
  margin: 1.5rem 0;
  font-weight: 700;
  letter-spacing: -0.5px;
  position: relative;
  display: inline-block;
  padding: 0.5rem 2rem;
}
#ticket_number:before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--primary-light);
  border-radius: 0.5rem;
  z-index: -1;
}
.info {
  color: var(--text);
  margin: 1rem 0;
  font-size: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}
.info strong {
  color: var(--primary-dark);
}
.status-container {
  margin: 1.5rem 0;
  padding: 1rem;
  background: #f1f5f9;
  border-radius: 0.5rem;
}
#waiting, #counter_info {
  margin: 0.5rem 0;
}
.small {
  color: var(--text-light);
  margin-top: 1.5rem;
  font-size: 0.875rem;
  line-height: 1.5;
}
.pulse {
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.4);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(37, 99, 235, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0);
  }
}
.called {
  color: var(--success) !important;
  animation: scale 0.5s ease;
}
@keyframes scale {
  0% { transform: scale(1); }
  50% { transform: scale(1.2); }
  100% { transform: scale(1); }
}
#notification {
  position: fixed;
  top: 20px;
  right: 20px;
  background: var(--success);
  color: white;
  padding: 1rem;
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: none;
  z-index: 100;
  animation: slideIn 0.3s ease;
}
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Proxima</div>
  <h1>Your Ticket</h1>
  <div id="ticket_number" class="pulse">{{ ticket.id }}</div>
  <div class="info">Service: <strong>{{ ticket.category }}</strong></div>
  <div class="status-container">
    <div id="waiting" class="info">Waiting Time: calculating...</div>
    <div id="counter_info" class="info">Assigned Counter: Not yet</div>
  </div>
  <div class="small">Please wait — you will be notified when your ticket is called.</div>
</div>

<!-- Notification element -->
<div id="notification"></div>

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

// Request notification permission
if ("Notification" in window) {
    Notification.requestPermission();
}

function showNotification(title, message) {
    // Browser notification
    if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body: message });
    }
    
    // In-page notification
    var notificationEl = document.getElementById('notification');
    notificationEl.textContent = message;
    notificationEl.style.display = 'block';
    
    setTimeout(function() {
        notificationEl.style.display = 'none';
    }, 10000);
}

function updateWaiting(){
    fetch('/ticket_wait_time/' + ticketId)
    .then(r => r.json())
    .then(data => {
        var waitingEl = document.getElementById('waiting');
        if (data.waiting_time === 0) {
            waitingEl.innerHTML = "Waiting Time: <strong>You're next!</strong>";
        } else {
            waitingEl.innerText = "Waiting Time: " + data.waiting_time + " minutes";
        }
    });
}
setInterval(updateWaiting, 5000);
updateWaiting();

socket.on("ticket_called", function(data){
    if(data.id === ticketId){
        try { 
            ticketDing.currentTime = 0; 
            ticketDing.play().catch(function(e) {
                console.log("Audio play error:", e);
            }); 
        } catch(e){}
        
        // Update UI
        document.getElementById('counter_info').innerHTML = "Assigned Counter: <strong>" + data.counter_name + "</strong>";
        var ticketNumber = document.getElementById('ticket_number');
        ticketNumber.classList.remove('pulse');
        ticketNumber.classList.add('called');
        
        // Show notification
        showNotification(
            "Your ticket is ready!", 
            "Ticket " + ticketId + " is now being served at " + data.counter_name
        );
        
        // Vibrate if supported
        if ("vibrate" in navigator) {
            navigator.vibrate([200, 100, 200]);
        }
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
<title>Counter - {{ counter.name }} | Proxima</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --primary-light: #dbeafe;
  --accent: #f97316;
  --text: #1e293b;
  --text-light: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --success: #10b981;
  --card-shadow: 0 10px 30px rgba(0,0,0,0.08);
  --transition: all 0.3s ease;
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  margin: 0;
  padding: 2rem 1.5rem;
  color: var(--text);
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}
.logo {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 1rem;
  letter-spacing: -0.5px;
}
h1 {
  color: var(--text);
  margin: 0;
  font-size: 1.75rem;
  font-weight: 600;
}
.box {
  background: var(--card-bg);
  padding: 1.5rem;
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
  margin-top: 1rem;
}
button {
  background: var(--primary);
  color: white;
  border: none;
  padding: 0.875rem 1.5rem;
  border-radius: 0.5rem;
  cursor: pointer;
  font-size: 1rem;
  font-weight: 500;
  transition: var(--transition);
}
button:hover {
  background: var(--primary-dark);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
#current_ticket {
  font-size: 1.5rem;
  color: var(--primary);
  margin: 1rem 0;
  font-weight: 600;
  padding: 1rem;
  background: var(--primary-light);
  border-radius: 0.5rem;
  text-align: center;
}
#next_in_line {
  font-size: 1.125rem;
  color: var(--text);
  margin: 1rem 0;
  padding: 0.75rem;
  background: #f1f5f9;
  border-radius: 0.5rem;
  text-align: center;
}
.services {
  display: inline-flex;
  align-items: center;
  padding: 0.5rem 1rem;
  background: var(--primary-light);
  border-radius: 2rem;
  color: var(--primary);
  font-weight: 500;
  font-size: 0.875rem;
}
h3 {
  color: var(--text);
  margin: 1.5rem 0 1rem;
  font-size: 1.25rem;
  font-weight: 600;
}
ul {
  padding-left: 0;
  list-style: none;
  margin: 1rem 0 1.5rem;
}
li {
  margin: 0.5rem 0;
  padding: 0.75rem 1rem;
  background: #f1f5f9;
  border-radius: 0.5rem;
  display: flex;
  align-items: center;
}
li:before {
  content: '•';
  color: var(--primary);
  font-weight: bold;
  margin-right: 0.5rem;
}
</style>
</head>
<body>
<div class="logo">Proxima</div>
<div class="header">
  <h1>Counter: {{ counter.name }}</h1>
  <div class="services">{{ counter.categories|join(" • ") }}</div>
</div>

<div class="box">
  <div id="current_ticket">No ticket being served</div>
  <div id="next_in_line">Next: None</div>
  <h3>Waiting Queue</h3>
  <ul id="queue_list"></ul>
  <button onclick="callNext()">Call Next Ticket</button>
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
<title>Display | Proxima</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --primary-light: #dbeafe;
  --accent: #f97316;
  --text: #1e293b;
  --text-light: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --success: #10b981;
  --card-shadow: 0 10px 30px rgba(0,0,0,0.08);
  --transition: all 0.3s ease;
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  margin: 0;
  padding: 0;
  color: var(--text);
  height: 100vh;
  overflow: hidden;
}
.header {
  background: var(--primary);
  color: white;
  padding: 1rem 1.5rem;
  text-align: center;
  font-size: 1.75rem;
  font-weight: 600;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  position: relative;
  z-index: 10;
}
.display-container {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1.5rem;
  padding: 1.5rem;
  height: calc(100vh - 4.75rem);
  overflow-y: auto;
}
.counter-card {
  background: var(--card-bg);
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  transition: var(--transition);
  position: relative;
  overflow: hidden;
}
.counter-card:before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 0.25rem;
  background: var(--primary);
}
.counter-name {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 1rem;
  text-align: center;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}
.ticket-display {
  font-size: 4rem;
  font-weight: 700;
  color: var(--accent);
  text-align: center;
  margin: auto 0;
  padding: 2rem 0;
  letter-spacing: -1px;
  transition: all 0.5s ease;
}
.empty-ticket {
  color: var(--text-light);
  font-size: 2.5rem;
  opacity: 0.5;
}
.flash {
  animation: flash 1s;
}
@keyframes flash {
  0%, 100% { background-color: var(--card-bg); }
  50% { background-color: var(--primary-light); }
}
@media (max-width: 768px) {
  .display-container {
    grid-template-columns: 1fr;
  }
  .ticket-display {
    font-size: 3rem;
    padding: 1.5rem 0;
  }
}
</style>
</head>
<body>
<div class="header">Proxima Queue Display</div>
<div class="display-container" id="counters">
  {% for counter in counters %}
  <div class="counter-card">
    <div class="counter-name">{{ counter.name }}</div>
    <div class="ticket-display" id="counter_{{ counter.id }}">
      {% if counter.current_ticket %}
        {{ counter.current_ticket }}
      {% else %}
        <span class="empty-ticket">-</span>
      {% endif %}
    </div>
  </div>
  {% endfor %}
</div>

<audio id="ding" src="{{ ding_url }}" preload="auto"></audio>
<!-- Add speech synthesis for announcements -->

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
var socket = io();
var ding = document.getElementById('ding');
// Set lower volume for the ding sound
ding.volume = 0.4; // 40% volume

socket.emit("join_display_room");

socket.on("display_update", function(data){
    var countersDiv = document.getElementById('counters');
    countersDiv.innerHTML = '';
    
    for(var i=0; i < data.length; i++){
        var counter = data[i];
        var card = document.createElement('div');
        card.className = 'counter-card';
        
        var nameDiv = document.createElement('div');
        nameDiv.className = 'counter-name';
        nameDiv.innerText = counter.name;
        
        var ticketDiv = document.createElement('div');
        ticketDiv.className = 'ticket-display';
        ticketDiv.id = 'counter_' + counter.id;
        
        if(counter.current_ticket){
            ticketDiv.innerText = counter.current_ticket;
        } else {
            var span = document.createElement('span');
            span.className = 'empty-ticket';
            span.innerText = '-';
            ticketDiv.appendChild(span);
        }
        
        card.appendChild(nameDiv);
        card.appendChild(ticketDiv);
        countersDiv.appendChild(card);
    }
});

// Function to announce ticket using speech synthesis
function announceTicket(ticketId, counterName) {
    // Format the ticket ID for better pronunciation
    let formattedTicket = ticketId.split('-').join(' ');
    let announcement = `Ticket ${formattedTicket}, please proceed to ${counterName}`;
    
    // Check if browser supports speech synthesis
    if ('speechSynthesis' in window) {
        // Create a new speech synthesis utterance
        let utterance = new SpeechSynthesisUtterance(announcement);
        utterance.rate = 0.9; // Slightly slower rate for clarity
        utterance.pitch = 1;
        utterance.volume = 1;
        
        // Get available voices and set to a clear voice if available
        let voices = window.speechSynthesis.getVoices();
        if (voices.length > 0) {
            // Try to find a good English voice
            let englishVoice = voices.find(voice => 
                voice.lang.includes('en') && voice.name.includes('Female'));
            if (englishVoice) utterance.voice = englishVoice;
        }
        
        // Wait for the ding sound to complete before speaking
        // Typical ding sound is about 1-2 seconds, so wait 2 seconds
        setTimeout(() => {
            window.speechSynthesis.speak(utterance);
        }, 2000); // Wait 2 seconds after the ding starts
    }
}

socket.on("ticket_called", function(data){
    try { 
        ding.currentTime = 0;
        // Play the ding sound first
        ding.play().catch(function(e){console.log("Audio play error:", e)}); 
        // Don't cut off the ding sound - let it play naturally
        // Remove the timeout that was cutting it off
    } catch(e){}
    
    // Announce the ticket vocally AFTER the ding completes
    // We'll handle this in the announceTicket function
    announceTicket(data.id, data.counter_name);
    
    var counterElem = document.getElementById('counter_' + data.counter_id);
    if(counterElem){
        counterElem.innerText = data.id;
        // Flash effect
        var card = counterElem.parentElement;
        card.classList.add('flash');
        setTimeout(function(){
            card.classList.remove('flash');
        }, 1000);
        
        // Highlight the ticket
        counterElem.style.transition = 'all 0.5s ease';
        counterElem.style.color = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
        counterElem.style.transform = 'scale(1.1)';
        setTimeout(function(){
            counterElem.style.transform = 'scale(1)';
        }, 1000);
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
<title>Admin Dashboard | Proxima</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --primary: #2563eb;
  --primary-dark: #1d4ed8;
  --primary-light: #dbeafe;
  --accent: #f97316;
  --text: #1e293b;
  --text-light: #64748b;
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --success: #10b981;
  --danger: #ef4444;
  --card-shadow: 0 10px 30px rgba(0,0,0,0.08);
  --transition: all 0.3s ease;
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  margin: 0;
  padding: 2rem 1.5rem;
  color: var(--text);
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}
.logo {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 1rem;
  letter-spacing: -0.5px;
}
h1 {
  color: var(--text);
  margin: 0;
  font-size: 1.75rem;
  font-weight: 600;
}
h3 {
  color: var(--text);
  margin: 1.5rem 0 1rem;
  font-size: 1.25rem;
  font-weight: 600;
}
.form {
  background: var(--card-bg);
  padding: 1.5rem;
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
  margin-top: 1rem;
}
input[type="text"] {
  display: block;
  width: 100%;
  padding: 0.875rem 1rem;
  margin: 0 0 1rem;
  border-radius: 0.5rem;
  border: 1px solid #e2e8f0;
  font-size: 1rem;
  transition: var(--transition);
  box-sizing: border-box;
}
input[type="text"]:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-light);
}
table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 1rem;
  background: var(--card-bg);
  border-radius: 1rem;
  overflow: hidden;
  box-shadow: var(--card-shadow);
}
th {
  background: var(--primary-light);
  color: var(--primary-dark);
  font-weight: 600;
  text-align: left;
  padding: 1rem;
}
th:first-child {
  border-top-left-radius: 1rem;
}
th:last-child {
  border-top-right-radius: 1rem;
}
th, td {
  padding: 1rem;
  border: none;
  border-bottom: 1px solid #e2e8f0;
}
tr:last-child td {
  border-bottom: none;
}
tr:last-child td:first-child {
  border-bottom-left-radius: 1rem;
}
tr:last-child td:last-child {
  border-bottom-right-radius: 1rem;
}
button {
  padding: 0.625rem 1rem;
  border-radius: 0.5rem;
  border: none;
  background: var(--primary);
  color: white;
  cursor: pointer;
  font-weight: 500;
  transition: var(--transition);
  font-size: 0.875rem;
}
button:hover {
  background: var(--primary-dark);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
.checkbox-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 1rem 0;
}
.checkbox-list label {
  background: #f1f5f9;
  padding: 0.625rem 1rem;
  border-radius: 0.5rem;
  border: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  transition: var(--transition);
  font-size: 0.875rem;
}
.checkbox-list label:hover {
  border-color: var(--primary);
  background: var(--primary-light);
}
.names-list {
  margin-top: 1.5rem;
  background: var(--card-bg);
  padding: 1.5rem;
  border-radius: 1rem;
  box-shadow: var(--card-shadow);
}
.clear-btn {
  background: var(--danger);
  margin-left: 0.5rem;
}
.clear-btn:hover {
  background: #dc2626;
}
.action-btns {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
a {
  color: var(--primary);
  text-decoration: none;
  font-weight: 500;
  transition: var(--transition);
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
}
a:hover {
  color: var(--primary-dark);
  text-decoration: underline;
}
.btn-danger {
    background-color: #e74c3c;
}
.btn-danger:hover {
    background-color: #c0392b;
}
.display-btn:before {
  content: '⤴';
  font-size: 1.125rem;
}
.user-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem;
  margin-top: 1rem;
}
.user-list li {
  background: var(--primary-light);
  color: var(--primary-dark);
  padding: 0.625rem 1rem;
  border-radius: 0.5rem;
  list-style: none;
  font-size: 0.875rem;
}
</style>
</head>
<body>
<div class="logo">Proxima</div>
<div class="header">
  <h1>Admin Dashboard</h1>
  <div class="action-btns">
    <a href="/display" target="_blank" class="display-btn">Open Display</a>
    <form action="/admin/clear_names" method="post" style="display:inline;margin:0">
      <button type="submit" class="clear-btn">Clear Names</button>
    </form>
    <a href="/admin/logout" class="btn btn-danger">Logout</a>
  </div>
</div>

<div class="form">
  <h3>Add New Counter</h3>
  <form action="/admin/add_counter" method="post">
    <input type="text" name="name" placeholder="Counter name (eg Counter 1)" required>
    <div class="checkbox-list">
      {% for cat in categories %}
        <label><input type="checkbox" name="categories" value="{{ cat }}"> {{ cat }}</label>
      {% endfor %}
    </div>
    <div style="margin-top:1rem">
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
    <ul class="user-list">
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

admin_login_template = """<!DOCTYPE html>
<html>
<head>
    <title>Proxima Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --primary-color: #3498db;
            --secondary-color: #2980b9;
            --text-color: #333;
            --bg-color: #f5f5f5;
        }
        body {
            font-family: Arial, sans-serif;
            background-color: var(--bg-color);
            margin: 0;
            padding: 20px;
            color: var(--text-color);
        }
        .login-container {
            max-width: 400px;
            margin: 50px auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: var(--primary-color);
            text-align: center;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        input[type="password"] {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
        }
        button {
            background-color: var(--primary-color);
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 4px;
            cursor: pointer;
            width: 100%;
            font-size: 16px;
            transition: background-color 0.3s;
        }
        button:hover {
            background-color: var(--secondary-color);
        }
        .error-message {
            color: #e74c3c;
            margin-top: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Proxima Admin</h1>
        <form method="POST" action="/admin/login">
            <div class="form-group">
                <label for="passcode">Admin Passcode</label>
                <input type="password" id="passcode" name="passcode" required>
            </div>
            {% if error %}
            <div class="error-message">{{ error }}</div>
            {% endif %}
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>"""

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
    return list(counters.values())

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
            # Also notify the display to play sound and update
            socketio.emit("ticket_called", {"id": next_ticket['id'], "counter_name": counter['name'], "counter_id": counter_id}, room="display")
            break
    else:
        counter['current_ticket'] = None
    # update display and all counters/admin
    socketio.emit("display_update", get_display_state(), room="display")
    socketio.emit("queue_update", get_full_state(), room="all_counters")

# ------------------ ROUTES ------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    
    # If already authenticated, redirect to admin page
    if session.get("admin_authenticated"):
        return redirect("/admin")
    
    if request.method == "POST":
        passcode = request.form.get("passcode")
        if passcode == "apuvisa2025":
            session["admin_authenticated"] = True
            return redirect("/admin")
        else:
            error = "Invalid passcode"
    
    return render_template_string(admin_login_template, error=error)

@app.route("/", methods=["GET", "POST"])
def username_page():
    # Always show the name form on GET requests, regardless of session state
    if request.method == "GET":
        # Clear any existing user_name from session
        if "user_name" in session:
            session.pop("user_name")
        # Clear any existing ticket keys from session
        for key in list(session.keys()):
            if key.startswith("ticket_"):
                session.pop(key)
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
    return render_template_string(user_template, categories=user_categories, messages=session.pop('_flashes', []))

@app.route("/ticket_page/<category>")
def ticket_page(category):
    # restrict direct access if no name in session
    if not session.get("user_name"):
        return redirect("/")
    # Protect: if a user navigates manually to a category that isn't shown, still allow if exists.
    if category not in queue:
        return "Invalid service", 404
    
    # Check if user has any unserved tickets in any category
    for cat in queue.keys():
        ticket_key = f"ticket_{cat}"
        if ticket_key in session:
            ticket_id = session[ticket_key]
            # Check if this ticket is still in the queue (unserved)
            ticket_in_queue = False
            for t in queue[cat]:
                if t['id'] == ticket_id:
                    ticket_in_queue = True
                    # If trying to get a ticket for the same category, show the existing ticket
                    if cat == category:
                        ding_url = url_for('static', filename='ding.mp3')
                        return render_template_string(ticket_page_template, ticket=t, ding_url=ding_url)
                    # If trying to get a ticket for a different category, redirect to services page
                    # with a message that they need to wait for current ticket to be served
                    else:
                        flash(f"You already have an active ticket for {cat}. Please wait until it's served before getting a new ticket.")
                        return redirect("/services")
            
            # If we get here, the ticket is no longer in the queue (it's been served)
            # If it's the same category, redirect to services page
            if cat == category:
                flash(f"Your ticket for {cat} has been served. You can now get a new ticket if needed.")
                # Remove the ticket from session
                session.pop(ticket_key)
                return redirect("/services")
    
    # If we get here, user has no unserved tickets, so generate a new one
    ticket = generate_ticket(category)
    session_ticket_key = f"ticket_{category}"
    session[session_ticket_key] = ticket['id']
    
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
    # Check if admin is authenticated
    if not session.get("admin_authenticated"):
        return redirect("/admin/login")
        
    # admins can see all categories (including EMGS & PTPTN)
    names = load_user_names()
    return render_template_string(admin_template, counters=counters, categories=list(queue.keys()), names=names)

@app.route("/admin/add_counter", methods=["POST"])
def add_counter():
    # Check if admin is authenticated
    if not session.get("admin_authenticated"):
        return redirect("/admin/login")
        
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
    # Check if admin is authenticated
    if not session.get("admin_authenticated"):
        return redirect("/admin/login")
        
    if counter_id in counters:
        del counters[counter_id]
        socketio.emit("display_update", get_display_state(), room="display")
        socketio.emit("queue_update", get_full_state(), room="all_counters")
    return ("", 200)

@app.route("/admin/clear_names", methods=["POST"])
def admin_clear_names():
    # Check if admin is authenticated
    if not session.get("admin_authenticated"):
        return redirect("/admin/login")
        
    clear_user_names()
    return redirect("/admin")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    return redirect("/admin/login")

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
    # Check if admin is authenticated
    if not session.get("admin_authenticated"):
        return
        
    join_room("all_counters")
    emit("queue_update", get_full_state(), to=request.sid)

@socketio.on("call_next")
def handle_call_next(data):
    cid = data.get('counter_id')
    call_next_ticket(cid)
    # This line is redundant as call_next_ticket already emits queue_update
    # emit("queue_update", get_full_state(), room="all_counters")

# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
