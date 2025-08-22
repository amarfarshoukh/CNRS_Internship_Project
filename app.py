from flask import Flask, jsonify
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests for your frontend

# Path to your incidents GeoJSON
INCIDENTS_FILE = "geojson_output/incidents.geojson"

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """
    Returns all incidents in GeoJSON format for Leaflet map.
    """
    if not os.path.exists(INCIDENTS_FILE):
        return jsonify({"type": "FeatureCollection", "features": []})

    with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Ensure it's a proper FeatureCollection
    if data.get("type") != "FeatureCollection":
        return jsonify({"type": "FeatureCollection", "features": []})

    return jsonify(data)

@app.route("/")
def index():
    return "Leaflet Map Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
