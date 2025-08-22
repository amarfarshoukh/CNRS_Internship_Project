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

# City-to-coordinates lookup
city_coords = {
    "Beirut": [33.8938, 35.5018],
    "Tripoli": [34.4333, 35.8497],
    "Sidon": [33.5599, 35.3728],
    "Tyre": [33.2702, 35.2037],
    "Baalbek": [34.0064, 36.2034],
    "Zahle": [33.8446, 35.8973],
    "Byblos": [34.1233, 35.6510]
}

# Incident type to color mapping
incident_colors = {
    "fire": "red",
    "protest": "purple",
    "accident": "orange",
    "flood": "blue",
    "other": "gray"
}

def get_point_coordinates(inc):
    """
    Returns [lat, lon] for the incident. 
    Uses coordinates if available, otherwise city lookup.
    """
    coords = inc.get("coordinates")
    if coords and isinstance(coords, list) and len(coords) > 0:
        # Take first point if nested
        first_point = coords[0]
        while isinstance(first_point[0], list):  # handle polygons
            first_point = first_point[0]
        return [first_point[0][1], first_point[0][0]]  # lat, lon
    elif inc.get("location") and inc["location"] in city_coords:
        return city_coords[inc["location"]]
    else:
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
                    if coords:
                        inc_type = inc.get("incident_type", "other")
                        features.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": coords
                            },
                            "properties": {
                                "incident_type": inc_type,
                                "color": incident_colors.get(inc_type, "gray"),
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

# Start background thread
threading.Thread(target=load_incidents, daemon=True).start()

@app.route("/incidents", methods=["GET"])
def get_incidents():
    """Returns the latest incidents in GeoJSON format for Leaflet."""
    return jsonify(geojson_cache)

@app.route("/")
def index():
    return "Leaflet Map Backend Running. Use /incidents to fetch data."

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
