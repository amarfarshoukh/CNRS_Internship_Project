from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from datetime import datetime, timedelta
import re

app = Flask(__name__)
CORS(app)

# -----------------------------
# CONFIG
# -----------------------------
INCIDENTS_FILE = "matched_incidents.json"
GEOJSON_FOLDER = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output_2"

ALLOWED_INCIDENTS = {
    "fire", "protest", "vehicle_accident", "shooting",
    "natural_disaster", "airstrike", "collapse", "pollution",
    "epidemic", "medical", "explosion", "other"
}

INCIDENT_COLORS = {
    "fire": "red", "protest": "purple", "vehicle_accident": "orange",
    "shooting": "red", "natural_disaster": "blue", "airstrike": "black",
    "collapse": "brown", "pollution": "green", "epidemic": "pink",
    "medical": "yellow", "explosion": "gray", "other": "white"
}

# -----------------------------
# Arabic normalization
# -----------------------------
RE_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u06D6-\u06ED]+")

def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = RE_DIACRITICS.sub("", text)
    text = text.replace('\u0640', '')
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ؤ]", "و", text)
    text = re.sub(r"[ئ]", "ي", text)
    text = text.replace('ة', 'ه')
    text = re.sub(r"[يى]", "ي", text)
    return re.sub(r"\s+", " ", text).strip()

# -----------------------------
# Load GeoJSON locations robustly
# -----------------------------
def flatten_coords(coords):
    """Recursively flatten nested coordinate lists into a list of [lon, lat] pairs."""
    if not coords:
        return []
    if isinstance(coords[0], (int, float)) and len(coords) == 2:
        return [coords]
    flattened = []
    for c in coords:
        flattened.extend(flatten_coords(c))
    return flattened

def extract_centroid(coords):
    """Compute approximate centroid of polygon/multipolygon."""
    points = flatten_coords(coords)
    if not points:
        return None
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return [lon, lat]


def load_all_locations(folder_path):
    locations = {}
    for file in os.listdir(folder_path):
        if not file.lower().endswith(".json"):
            continue
        file_path = os.path.join(folder_path, file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            features = []
            if isinstance(data, dict):
                features = data.get("features", [])
            elif isinstance(data, list):
                features = data
            else:
                continue  # skip unknown format
            
            for feat in features:
                if isinstance(feat, dict):
                    props = feat.get("properties", feat)
                    geom = feat.get("geometry", {}) if "geometry" in feat else feat
                    name = props.get("name")
                    coords = None
                    if isinstance(geom, dict) and "coordinates" in geom:
                        coords = extract_centroid(geom["coordinates"])
                    if name and coords:
                        locations[normalize_arabic(name)] = {
                            "original": name,
                            "coordinates": coords
                        }
        except Exception as e:
            print(f"Error loading {file}: {e}")
    print(f"Loaded {len(locations)} Arabic locations from folder.")
    return locations

ALL_LOCATIONS = load_all_locations(GEOJSON_FOLDER)

# -----------------------------
# Incident type helpers
# -----------------------------
def normalize_incident_type(incident_type: str) -> str:
    return incident_type if incident_type in ALLOWED_INCIDENTS else "other"

def load_incidents(hours_window: float = None):
    incidents = []
    if os.path.exists(INCIDENTS_FILE):
        try:
            with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                incidents = json.load(f)
            now = datetime.utcnow()
            filtered_incidents = []
            for inc in incidents:
                # Normalize type
                inc_type = normalize_incident_type(inc.get("incident_type", "other"))
                inc["incident_type"] = inc_type
                # Add color
                inc["color"] = INCIDENT_COLORS.get(inc_type, "white")
                # Fix coordinates for Leaflet
                coords = inc.get("coordinates")
                if coords and isinstance(coords, list) and len(coords) == 2:
                    lon, lat = coords
                    inc["coordinates"] = [lat, lon]
                else:
                    inc["coordinates"] = []
                # Filter by time
                if hours_window is not None:
                    date_str = inc.get("date")
                    try:
                        inc_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if now - inc_time <= timedelta(hours=hours_window):
                            filtered_incidents.append(inc)
                    except Exception:
                        filtered_incidents.append(inc)
                else:
                    filtered_incidents.append(inc)
            return filtered_incidents
        except Exception as e:
            print(f"Error loading incidents: {e}")
    return incidents

# -----------------------------
# Search location by text
# -----------------------------
@app.route("/search_location", methods=["GET"])
def search_location():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"found": False})
    
    norm_query = normalize_arabic(query)
    best_match = None
    for loc_norm, loc_data in ALL_LOCATIONS.items():
        if norm_query in loc_norm:
            best_match = loc_data
            break
    if best_match:
        return jsonify({
            "found": True,
            "name": best_match["original"],
            "coordinates": best_match["coordinates"]
        })
    return jsonify({"found": False})

# -----------------------------
# Get incidents
# -----------------------------
@app.route("/incidents", methods=["GET"])
def get_incidents():
    return jsonify({"incidents": load_incidents(hours_window=0.5)})

@app.route("/")
def index():
    return "Incident Monitor Backend Running. Use /incidents or /search_location?q=TEXT"

# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
