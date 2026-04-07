"""
ZeroSeg Event Server
====================
Tiny Flask server that serves live events from the Ryu controller
to the dashboard running in the browser.

Usage (Terminal 3 in Mininet VM):
    pip3 install flask flask-cors
    python3 event_server.py

Then open the dashboard in the browser on the host and it will
poll http://<MININET_VM_IP>:5000/events every second.
"""

import json
import os
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow browser requests from any origin

EVENTS_FILE = "/tmp/zeroseg_events.json"
last_sent = 0

@app.route("/events")
def get_events():
    """Return all events since last request."""
    global last_sent
    try:
        if not os.path.exists(EVENTS_FILE):
            return jsonify({"events": [], "stats": {}})

        with open(EVENTS_FILE, 'r') as f:
            all_events = json.load(f)

        # Only send new events
        new_events = all_events[last_sent:]
        last_sent = len(all_events)

        # Compute stats
        total   = len(all_events)
        blocked = sum(1 for e in all_events if e["action"] == "BLOCK")
        allowed = total - blocked
        exploit = sum(1 for e in all_events if e["type"] == "Exploit" and e["action"] == "BLOCK")
        recon   = sum(1 for e in all_events if e["type"] == "Reconnaissance" and e["action"] == "BLOCK")

        return jsonify({
            "events": new_events,
            "stats": {
                "total": total,
                "allowed": allowed,
                "blocked": blocked,
                "exploit": exploit,
                "recon": recon
            }
        })
    except Exception as e:
        return jsonify({"events": [], "stats": {}, "error": str(e)})

@app.route("/reset")
def reset():
    """Reset events file."""
    global last_sent
    last_sent = 0
    with open(EVENTS_FILE, 'w') as f:
        json.dump([], f)
    return jsonify({"ok": True})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    print("ZeroSeg Event Server starting on http://0.0.0.0:5000")
    print("Dashboard should poll http://<MININET_VM_IP>:5000/events")
    app.run(host="0.0.0.0", port=5000, debug=False)
