import geopandas as gpd
import os

# -----------------------------
# Paths to your shapefiles
# -----------------------------
ROADS_SHP = r"C:\Users\user\Downloads\lebanon-latest-free.shp\gis_osm_roads_free_1.shp"
PLACES_SHP = r"C:\Users\user\Downloads\lebanon-latest-free.shp\gis_osm_places_free_1.shp"

OUTPUT_DIR = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output"
OUTPUT_ROADS_JSON = os.path.join(OUTPUT_DIR, "roads.json")
OUTPUT_CITIES_JSON = os.path.join(OUTPUT_DIR, "cities.json")

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
# Helper: filter inside Lebanon
# -----------------------------
def filter_lebanon(gdf):
    # Filter by bounding box
    return gdf.cx[LEBANON_BBOX["min_lon"]:LEBANON_BBOX["max_lon"],
                  LEBANON_BBOX["min_lat"]:LEBANON_BBOX["max_lat"]]

# -----------------------------
# Convert roads
# -----------------------------
roads_gdf = gpd.read_file(ROADS_SHP)

# Filter roads inside Lebanon
roads_gdf = roads_gdf[roads_gdf.geometry.bounds.minx <= LEBANON_BBOX["max_lon"]]
roads_gdf = roads_gdf[roads_gdf.geometry.bounds.maxx >= LEBANON_BBOX["min_lon"]]
roads_gdf = roads_gdf[roads_gdf.geometry.bounds.miny <= LEBANON_BBOX["max_lat"]]
roads_gdf = roads_gdf[roads_gdf.geometry.bounds.maxy >= LEBANON_BBOX["min_lat"]]

# Export to GeoJSON
roads_gdf.to_file(OUTPUT_ROADS_JSON, driver="GeoJSON")
print(f"Roads GeoJSON saved: {OUTPUT_ROADS_JSON}")

# -----------------------------
# Convert cities/places
# -----------------------------
cities_gdf = gpd.read_file(PLACES_SHP)

# Filter inside Lebanon
cities_gdf = cities_gdf[cities_gdf.geometry.y.between(LEBANON_BBOX["min_lat"], LEBANON_BBOX["max_lat"])]
cities_gdf = cities_gdf[cities_gdf.geometry.x.between(LEBANON_BBOX["min_lon"], LEBANON_BBOX["max_lon"])]

# Export to GeoJSON
cities_gdf.to_file(OUTPUT_CITIES_JSON, driver="GeoJSON")
print(f"Cities GeoJSON saved: {OUTPUT_CITIES_JSON}")

print("Conversion complete! Roads and cities are ready for your project.")
