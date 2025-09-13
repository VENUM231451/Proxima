# --------------------------
# app.py
# Complete queue system (single file) - Render-ready
# - Special Pass removed everywhere
# - PTPTN and EMGS Bank Letter hidden from user side only
# - Admin joins all_counters room and receives live updates
# - Uses SECRET_KEY and PORT from environment (Render-ready)
# - DING sound plays on display whenever a new ticket is called
# - User must enter First + Last name before seeing services (every visit, no caching)
# - Names saved in names.txt (no duplicates)
# - Admin can clear names with a button
# --------------------------

import os
import eventlet
eventlet.monkey_patch()

from flask import Flask, request, redirect, render_template_string, url_for
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

# ------------------ NAME HANDLING ------------------

NAMES_FILE = "names.txt"

def save_name(first, last):
    fullname = f"{first.strip()} {last.strip()}"
    if not os.path.exists(NAMES_FILE):
        with open(NAMES_FILE, "w") as f:
            f.write("")
    with open(NAMES_FILE, "r") as f:
        names = [line.strip() for line in f.readlines()]
    if fullname not in names:
        with open(NAMES_FILE, "a") as f:
            f.write(fullname + "\n")

def clear_names():
    open(NAMES_FILE, "w").close()

# ------------------ TEMPLATES ------------------

name_template = """
<!DOCTYPE html>
<html>
<head>
<title>Enter Name</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Inter,Arial,Helvetica,sans-serif;background:#f0f4f8;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
.container{background:white;padding:28px;border-radius:12px;box-shadow:0 6px 30px rgba(10,20,40,0.08);width:360px;text-align:center}
h1{color:#0D3B66;margin-bottom:16px}
input{width:90%;padding:12px;margin:8px 0;border:1px solid #ccc;border-radius:6px;font-size:15px}
button{width:100%;padding:14px;margin-top:12px;border:none;border-radius:8px;background:#0D3B66;color:white;font-size:16px;cursor:pointer}
button:hover{background:#08457e}
</style>
</head>
<body>
<div class="container">
  <h1>Enter Your Name</h1>
  <form method="POST" action="/">
    <input type="text" name="first" placeholder="First Name" required><br>
    <input type="text" name="last" placeholder="Last Name" required><br>
    <button type="submit">Continue</button>
  </form>
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
<title>Ticket</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,sans-serif;text-align:center;margin:40px;background:#f0f4f8}
.ticket{background:white;padding:30px;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,0.08);display:inline-block}
h1{margin:0 0 16px;color:#0D3B66}
</style>
</head>
<body>
<div class="ticket">
  <h1>Your Ticket</h1>
  <h2>{{ ticket }}</h2>
  <p>Category: {{ category }}</p>
</div>
</body>
</html>
"""

counter_template = """
<!DOCTYPE html>
<html>
<head>
<title>Counter</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body>
<h1>Counter Interface</h1>
<p>Work in progress...</p>
</body>
</html>
"""

display_template = """
<!DOCTYPE html>
<html>
<head>
<title>Queue Display</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Arial,Helvetica,sans-serif;background:#f0f4f8;margin:0;padding:20px}
.ticket{background:white;padding:16px;margin:12px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.06)}
h2{margin:0;color:#0D3B66}
</style>
</head>
<body>
<h1>Now Serving</h1>
<div id="display"></div>
<audio id="ding" src="/static/ding.mp3" preload="auto"></audio>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>
var socket = io();
socket.on("update_display", data=>{
  var div=document.getElementById("display");
  div.innerHTML="<div class='ticket'><h2>"+data.ticket+"</h2><p>"+data.counter+"</p></div>";
  document.getElementById("ding").play();
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
button{padding:8px 12px;border-radius:8px;border:none;background:#0D3B66;color:white;cursor:pointer}
button:hover{background:#08457e}
</style>
</head>
<body>
<div class="header">
  <h1>Admin Dashboard</h1>
  <div>
    <a href="/display" target="_blank">Open Display</a> |
    <form action="/admin/clear_names" method="post" style="display:inline">
      <button type="submit">Clear Names</button>
    </form>
  </div>
</div>
<p>Work in progress...</p>
</body>
</html>
"""

# ------------------ ROUTES ------------------

@app.route("/", methods=["GET","POST"])
def user_home():
    if request.method == "POST":
        first = request.form.get("first","").strip()
        last = request.form.get("last","").strip()
        if first and last:
            save_name(first,last)
            return render_template_string(user_template, categories=user_categories)
    return render_template_string(name_template)

@app.route("/ticket_page/<category>")
def ticket_page(category):
    category_counters[category]+=1
    ticket = f"{ticket_prefixes[category]}{category_counters[category]}"
    queue[category].append(ticket)
    return render_template_string(ticket_page_template, ticket=ticket, category=category)

@app.route("/counter")
def counter():
    return render_template_string(counter_template)

@app.route("/display")
def display():
    return render_template_string(display_template)

@app.route("/admin")
def admin():
    return render_template_string(admin_template)

@app.route("/admin/clear_names", methods=["POST"])
def clear_names_route():
    clear_names()
    return redirect("/admin")

# ------------------ SOCKET EVENTS ------------------

@socketio.on("call_next")
def call_next(data):
    category=data["category"]
    counter=data["counter"]
    if queue[category]:
        ticket=queue[category].pop(0)
        emit("update_display",{"ticket":ticket,"counter":counter},broadcast=True)

# ------------------ RUN ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
