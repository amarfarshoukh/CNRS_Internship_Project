from flask import Flask, jsonify
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)  # Allow requests from your frontend

# Path to your processed incident file
INCIDENTS_FILE = "matched_incidents.json"

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """
    Returns all incidents in GeoJSON-like format for Leaflet map.
    """
    if not os.path.exists(INCIDENTS_FILE):
        return jsonify({"type": "FeatureCollection", "features": []})

    with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
        incidents = json.load(f)

    # Convert incidents to GeoJSON features
    features = []
    for inc in incidents:
        coords = inc.get("coordinates")
        if coords and isinstance(coords, (list, tuple)) and len(coords) == 2:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": coords  # [lng, lat]
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

    return jsonify({"type": "FeatureCollection", "features": features})

@app.route("/")
def index():
    return "Leaflet Map Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
