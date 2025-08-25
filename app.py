from flask import Flask, jsonify
from flask_cors import CORS
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

INCIDENTS_FILE = "matched_incidents.json"

# Allowed incident categories
ALLOWED_INCIDENTS = {
    "fire",
    "protest",
    "vehicle_accident",
    "shooting",
    "natural_disaster",
    "airstrike",
    "collapse",
    "pollution",
    "epidemic",
    "medical",
    "explosion",
    "other"
}

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

def normalize_incident_type(incident_type: str) -> str:
    """
    Force unknown or unexpected incident types into 'other'.
    """
    if incident_type in ALLOWED_INCIDENTS:
        return incident_type
    return "other"

def load_incidents_once(hours_window: float = None):
    """
    Loads incidents from JSON file fresh each time.
    Adds color, normalizes types, ensures coordinates format is [lat, lon].
    If hours_window is set, only returns incidents from the last X hours.
    """
    incidents = []
    if os.path.exists(INCIDENTS_FILE):
        try:
            with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                incidents = json.load(f)

            now = datetime.utcnow()
            filtered_incidents = []

            for inc in incidents:
                # Normalize type
                inc_type = inc.get("incident_type", "other")
                inc_type = normalize_incident_type(inc_type)
                inc["incident_type"] = inc_type

                # Add color
                inc["color"] = INCIDENT_COLORS.get(inc_type, "white")

                # Fix coordinates for Leaflet
                coords = inc.get("coordinates")
                if coords and isinstance(coords, list) and len(coords) == 2:
                    lon, lat = coords
                    inc["coordinates"] = [lat, lon]  # Leaflet expects [lat, lon]
                else:
                    inc["coordinates"] = []

                # Filter by time window
                if hours_window is not None:
                    date_str = inc.get("date")
                    try:
                        inc_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if now - inc_time <= timedelta(hours=hours_window):
                            filtered_incidents.append(inc)
                    except Exception:
                        # If date parsing fails, skip filtering
                        filtered_incidents.append(inc)
                else:
                    filtered_incidents.append(inc)

            return filtered_incidents

        except Exception as e:
            print(f"Error loading incidents: {e}")
    return incidents

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """
    Always load fresh incidents from file.
    Only return incidents from the last 30 minutes (0.5 hours) for testing.
    """
    return jsonify({"incidents": load_incidents_once(hours_window=0.5)})

@app.route("/")
def index():
    return "Incident Monitor Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
