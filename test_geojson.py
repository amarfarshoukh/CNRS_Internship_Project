import json
import os
import re

# -----------------------------
# CONFIG
# -----------------------------
ROADS_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\roads.json"

# Lebanon bounding box (approx.)
LEBANON_BBOX = {
    "min_lat": 33.0,
    "max_lat": 34.7,
    "min_lon": 35.1,
    "max_lon": 36.6
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
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# -----------------------------
# Load roads GeoJSON (Lebanon only)
# -----------------------------
def load_lebanon_roads(geojson_file):
    if not os.path.exists(geojson_file):
        return {}
    with open(geojson_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    roads_map = {}
    for feature in data['features']:
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        coords = geom.get('coordinates', None)
        if not coords:
            continue

        # coords can be [lon, lat] or a list for LineString/Polygon
        if isinstance(coords[0], list):
            lon, lat = coords[0][0:2]
        else:
            lon, lat = coords[0], coords[1]

        # Filter inside Lebanon bbox
        if (LEBANON_BBOX["min_lat"] <= lat <= LEBANON_BBOX["max_lat"] and
            LEBANON_BBOX["min_lon"] <= lon <= LEBANON_BBOX["max_lon"]):
            name = props.get("name")
            if name:
                roads_map[normalize_arabic(name)] = name
    return roads_map

# -----------------------------
# Test function
# -----------------------------
def is_road_in_lebanon(road_name, roads_map):
    return normalize_arabic(road_name) in roads_map

# -----------------------------
# Main loop
# -----------------------------
if __name__ == "__main__":
    roads_map = load_lebanon_roads(ROADS_JSON)
    print(f"Loaded {len(roads_map)} roads in Lebanon.")

    while True:
        road_input = input("Enter road name to test (or 'exit' to quit): ").strip()
        if road_input.lower() == 'exit':
            break
        exists = is_road_in_lebanon(road_input, roads_map)
        print(f"Road '{road_input}' exists in Lebanon map? {exists}")
