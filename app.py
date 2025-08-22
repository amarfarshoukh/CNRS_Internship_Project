from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import os, json

app = Flask(__name__, static_folder='.', static_url_path='/')
CORS(app)

# Path to your matched_incidents.json
DB_PATH = os.path.join(os.path.dirname(__file__), 'matched_incidents.json')

@app.get('/incidents')
def get_incidents():
    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            items = json.load(f)
    except FileNotFoundError:
        items = []

    # Optional: map JSON fields to frontend expected keys
    incidents = []
    for i in items:
        incidents.append({
            'latitude': i.get('lat') or i.get('latitude'),
            'longitude': i.get('lon') or i.get('longitude'),
            'type': i.get('type', 'other'),
            'severity': i.get('severity', 1),
            'text': i.get('text', ''),
            'city': i.get('city', ''),
            'ts': i.get('ts', ''),
            'source_url': i.get('source_url', '')
        })
    return jsonify(incidents)

@app.get('/')
def root():
    return send_from_directory(app.static_folder, 'index.html')

@app.get('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
