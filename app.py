from flask import Flask, jsonify
from flask_cors import CORS
import json
import os
import threading
import time

app = Flask(__name__)
CORS(app)

INCIDENTS_FILE = "matched_incidents.json"
reload_interval = 10  # seconds

# Shared variable to store loaded incidents
incident_cache = []

# Map incident types to colors
INCIDENT_COLORS = {
    "fire": "red",
    "protest": "purple",
    "vehicle_accident": "orange",
    "shooting": "red",
    "natural_disaster": "blue",
    "airstrike": "black",
    "collapse": "brown",
    "pollution": "green",
    "epidemic": "pink",
    "medical": "yellow",
    "explosion": "gray",
    "other": "white"
}

def load_incidents():
    global incident_cache
    while True:
        if os.path.exists(INCIDENTS_FILE):
            try:
                with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                    incidents = json.load(f)
                # Add color based on incident_type and keep coordinates
                for inc in incidents:
                    inc["color"] = INCIDENT_COLORS.get(inc.get("incident_type", "other"), "white")
                    # Ensure coordinates exist and are properly formatted
                    if "coordinates" not in inc:
                        inc["coordinates"] = []
                incident_cache = incidents
            except Exception as e:
                print(f"Error loading incidents: {e}")
        time.sleep(reload_interval)

# Start background thread to reload incidents
threading.Thread(target=load_incidents, daemon=True).start()

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """
    Returns the latest incidents with coordinates and color for Leaflet.
    """
    return jsonify({"incidents": incident_cache})

@app.route("/")
def index():
    return "Incident Monitor Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
