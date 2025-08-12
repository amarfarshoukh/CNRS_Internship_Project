from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, json, datetime
from math import radians, cos, sin, asin, sqrt

app = Flask(__name__, static_folder='../frontend', static_url_path='/')
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "db.json")

if not os.path.exists(DB_PATH):
    with open(DB_PATH, "w") as f:
        json.dump([], f)

def read_db():
    with open(DB_PATH, "r") as f:
        return json.load(f)

def write_db(data):
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees).
    Returns distance in kilometers.
    """
    # convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # haversine formula
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 

    km = 6371 * c  # Radius of earth in kilometers
    return km

@app.route("/incidents", methods=["GET"])
def list_incidents():
    data = read_db()
    return jsonify(data), 200

@app.route("/incidents/<int:incident_id>", methods=["GET"])
def get_incident(incident_id):
    data = read_db()
    for item in data:
        if item.get("id") == incident_id:
            return jsonify(item), 200
    return jsonify({"error":"not found"}), 404

@app.route("/incidents/near", methods=["GET"])
def incidents_near():
    try:
        lat = float(request.args.get("lat"))
        lng = float(request.args.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid or missing 'lat' or 'lng' parameters"}), 400

    radius_km = float(request.args.get("radius", 1.0))  # default radius 1 km

    data = read_db()
    nearby = []
    for incident in data:
        ilat = incident.get("latitude")
        ilng = incident.get("longitude")
        if ilat is None or ilng is None:
            continue
        distance = haversine(lat, lng, ilat, ilng)
        if distance <= radius_km:
            nearby.append(incident)

    return jsonify(nearby), 200

@app.route("/report", methods=["POST"])
def report_incident():
    payload = request.get_json(force=True)
    if not payload or "type" not in payload or "description" not in payload:
        return jsonify({"error":"invalid payload, require 'type' and 'description'"}), 400

    data = read_db()
    new_id = (max([it["id"] for it in data]) + 1) if data else 1
    incident = {
        "id": new_id,
        "type": payload.get("type"),
        "description": payload.get("description"),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "location_name": payload.get("location_name"),
        "reported_at": payload.get("reported_at") or datetime.datetime.utcnow().isoformat()+"Z",
        "source": payload.get("source", "Website"),
        "confidence": payload.get("confidence", 0.5),
        "evidence": payload.get("evidence", [])
    }
    data.append(incident)
    write_db(data)
    return jsonify(incident), 201

# Serve frontend static index
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
