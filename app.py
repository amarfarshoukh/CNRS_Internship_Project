from flask import Flask, jsonify
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)

INCIDENTS_FILE = "matched_incidents.json"

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

def load_incidents_once():
    """
    Loads incidents from JSON file fresh each time.
    Adds color & ensures coordinates format is [lat, lon].
    """
    incidents = []
    if os.path.exists(INCIDENTS_FILE):
        try:
            with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                incidents = json.load(f)

            for inc in incidents:
                inc["color"] = INCIDENT_COLORS.get(inc.get("incident_type", "other"), "white")
                coords = inc.get("coordinates")
                if coords and isinstance(coords, list) and len(coords) == 2:
                    lon, lat = coords
                    inc["coordinates"] = [lat, lon]  # Leaflet expects [lat, lon]
                else:
                    inc["coordinates"] = []
        except Exception as e:
            print(f"Error loading incidents: {e}")
    return incidents

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """
    Always load fresh incidents from file.
    """
    return jsonify({"incidents": load_incidents_once()})

@app.route("/")
def index():
    return "Incident Monitor Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
