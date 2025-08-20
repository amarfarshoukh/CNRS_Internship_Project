import json

# -----------------------------
# Paths to your converted GeoJSON
# -----------------------------
ROADS_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\roads.json"
CITIES_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\cities.json"

# -----------------------------
# Load GeoJSON features
# -----------------------------
def load_geojson_names(geojson_file, name_field_candidates=None):
    """Return a set of location names from GeoJSON."""
    if name_field_candidates is None:
        name_field_candidates = ["name", "NAME", "ref", "road_name"]
    
    with open(geojson_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    names = set()
    for feature in data["features"]:
        props = feature.get("properties", {})
        for field in name_field_candidates:
            if field in props and props[field]:
                names.add(props[field])
                break  # take first matching field
    return names

roads_names = load_geojson_names(ROADS_JSON)
cities_names = load_geojson_names(CITIES_JSON)

print(f"Number of roads loaded: {len(roads_names)}")
print(f"Number of cities loaded: {len(cities_names)}")

# -----------------------------
# Test if specific locations exist
# -----------------------------
test_locations = ["بيروت", "شارع الثورة", "بعبدا", "شارع الشيخ صباح السالم الصباح", "UnknownPlace"]

for loc in test_locations:
    in_cities = loc in cities_names
    in_roads = loc in roads_names
    exists = in_cities or in_roads
    print(f"{loc}: {exists}")
