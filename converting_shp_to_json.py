import geopandas as gpd
import os
import json

# -----------------------------
# CONFIG
# -----------------------------
BASE_FOLDER = r"C:\Users\user\Downloads\lebanon-latest-free.shp"
OUTPUT_FOLDER = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# -----------------------------
# HELPER
# -----------------------------
def save_layer_to_geojson(shp_path, layer_name, output_file):
    gdf = gpd.read_file(shp_path, layer=layer_name)
    # Keep only useful columns
    if layer_name.startswith("gis_osm_roads"):
        gdf = gdf[["osm_id", "fclass", "name", "geometry"]]
    elif layer_name.startswith("gis_osm_places"):
        gdf = gdf[["osm_id", "fclass", "name", "geometry"]]
    geojson_str = gdf.to_json()
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(geojson_str)
    print(f"Saved {layer_name} with {len(gdf)} features to {output_file}")

# -----------------------------
# SAVE ROADS
# -----------------------------
roads_shp = os.path.join(BASE_FOLDER, "gis_osm_roads_free_1.shp")
save_layer_to_geojson(roads_shp, "gis_osm_roads_free_1", os.path.join(OUTPUT_FOLDER, "roads.json"))

# -----------------------------
# SAVE CITIES
# -----------------------------
cities_shp = os.path.join(BASE_FOLDER, "gis_osm_places_free_1.shp")
save_layer_to_geojson(cities_shp, "gis_osm_places_free_1", os.path.join(OUTPUT_FOLDER, "cities.json"))
