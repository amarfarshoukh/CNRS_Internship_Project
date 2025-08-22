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

geojson_cache = {"type": "FeatureCollection", "features": []}

# Incident type colors
INCIDENT_COLORS = {
    "vehicle_accident": "orange",
    "shooting": "red",
    "protest": "purple",
    "fire": "red",
    "natural_disaster": "brown",
    "airstrike": "black",
    "collapse": "gray",
    "pollution": "green",
    "epidemic": "yellow",
    "medical": "blue",
    "explosion": "darkred",
    "other": "white"
}

# Helper to safely get [lat, lon]
def get_point_coordinates(inc):
    coords = inc.get("coordinates")
    if coords and isinstance(coords, (list, tuple)):
        try:
            # flatten nested arrays if needed
            point = coords
            while isinstance(point[0], list):
                point = point[0]
            if len(point) >= 2 and all(isinstance(c, (int, float)) for c in point[:2]):
                # convert [lon, lat] -> [lat, lon] for Leaflet
                return [point[1], point[0]]
        except Exception:
            return None
    return None

def load_incidents():
    global geojson_cache
    while True:
        if os.path.exists(INCIDENTS_FILE):
            try:
                with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                    incidents = json.load(f)

                features = []
                for inc in incidents:
                    coords = get_point_coordinates(inc)
                    if not coords:
                        continue

                    incident_type = inc.get("incident_type", "other")
                    color = INCIDENT_COLORS.get(incident_type, "white")

                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": coords
                        },
                        "properties": {
                            "incident_type": incident_type,
                            "color": color,
                            "location": inc.get("location"),
                            "channel": inc.get("channel"),
                            "date": inc.get("date"),
                            "threat_level": inc.get("threat_level"),
                            "details": inc.get("details")
                        }
                    })

                geojson_cache = {"type": "FeatureCollection", "features": features}
            except Exception as e:
                print(f"Error loading incidents: {e}")
        time.sleep(reload_interval)

threading.Thread(target=load_incidents, daemon=True).start()

@app.route("/incidents", methods=["GET"])
def get_incidents():
    return jsonify(geojson_cache)

@app.route("/")
def index():
    return "Leaflet Map Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
