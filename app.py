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
geojson_cache = {"type": "FeatureCollection", "features": []}

def load_incidents():
    global geojson_cache
    while True:
        if os.path.exists(INCIDENTS_FILE):
            try:
                with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                    incidents = json.load(f)

                features = []
                for inc in incidents:
                    coords = inc.get("coordinates")
                    if coords and isinstance(coords, (list, tuple)) and len(coords) == 2:
                        features.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": coords
                            },
                            "properties": {
                                "incident_type": inc.get("incident_type"),
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

# Start background thread to reload incidents
threading.Thread(target=load_incidents, daemon=True).start()

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """
    Returns the latest incidents in GeoJSON format for Leaflet.
    """
    return jsonify(geojson_cache)

@app.route("/")
def index():
    return "Leaflet Map Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
