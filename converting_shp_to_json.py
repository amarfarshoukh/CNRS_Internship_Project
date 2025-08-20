import geopandas as gpd
import os

# -----------------------------
# Paths
# -----------------------------
ROADS_SHP = r"C:\Users\user\Downloads\lebanon-latest-free.shp\gis_osm_roads_free_1.shp"
OUTPUT_DIR = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output"
OUTPUT_ROADS_JSON = os.path.join(OUTPUT_DIR, "roads.json")

# -----------------------------
# Lebanon bounding box (approx.)
# -----------------------------
LEBANON_BBOX = {
    "min_lat": 33.0,
    "max_lat": 34.7,
    "min_lon": 35.1,
    "max_lon": 36.6
}

# -----------------------------
# Ensure output folder exists
# -----------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -----------------------------
# Load roads shapefile
# -----------------------------
roads_gdf = gpd.read_file(ROADS_SHP)

# Keep only essential columns
keep_cols = ["osm_id", "fclass", "name", "ref", "oneway", "maxspeed", "layer", "bridge", "tunnel", "geometry"]
roads_gdf = roads_gdf[keep_cols]

# -----------------------------
# Filter inside Lebanon
# -----------------------------
roads_gdf = roads_gdf[
    (roads_gdf.geometry.bounds.minx <= LEBANON_BBOX["max_lon"]) &
    (roads_gdf.geometry.bounds.maxx >= LEBANON_BBOX["min_lon"]) &
    (roads_gdf.geometry.bounds.miny <= LEBANON_BBOX["max_lat"]) &
    (roads_gdf.geometry.bounds.maxy >= LEBANON_BBOX["min_lat"])
]

# -----------------------------
# Simplify geometry (reduces file size)
# -----------------------------
roads_gdf["geometry"] = roads_gdf["geometry"].simplify(tolerance=0.0001, preserve_topology=True)

# -----------------------------
# Export to GeoJSON
# -----------------------------
roads_gdf.to_file(OUTPUT_ROADS_JSON, driver="GeoJSON")
print(f"Roads GeoJSON saved: {OUTPUT_ROADS_JSON}")
print("Conversion complete! All roads kept, simplified, and ready for QGIS.")
