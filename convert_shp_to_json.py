import os
import json
import re
import shapefile  # pip install pyshp
from shapely.geometry import shape, mapping

# -----------------------------
# CONFIG
# -----------------------------
INPUT_FOLDER = r"C:\Users\user\Downloads\admin\admin"
OUTPUT_FOLDER = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output_2"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Arabic normalization
RE_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u06D6-\u06ED]+")

def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = RE_DIACRITICS.sub("", text)
    text = text.replace('\u0640', '')  # Tatweel
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ؤ]", "و", text)
    text = re.sub(r"[ئ]", "ي", text)
    text = text.replace('ة', 'ه')
    text = re.sub(r"[يى]", "ي", text)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def is_arabic(text):
    if not text:
        return False
    return bool(re.search(r'[\u0600-\u06FF]', text))

# -----------------------------
# Detect appropriate name field
def detect_name_field(fields):
    # Prefer Arabic
    for candidate in [
        "ADM4_AR", "ADM3_AR", "ADM2_AR", "ADM1_AR", "ADM0_AR",
        "ADM4ALT1AR", "ADM3ALT1AR", "ADM2ALT1AR", "ADM1ALT1AR", "ADM0ALT1AR",
        "ADM4ALT2AR", "ADM3ALT2AR", "ADM2ALT2AR", "ADM1ALT2AR", "ADM0ALT2AR"
    ]:
        if candidate in fields:
            return candidate

    # Fall back to English
    for candidate in [
        "ADM4_EN", "ADM3_EN", "ADM2_EN", "ADM1_EN", "ADM0_EN",
        "NAME", "name", "fclass", "type"
    ]:
        if candidate in fields:
            return candidate

    return None

# -----------------------------
# Convert a SHP file to JSON with coordinates
def shp_to_json(shp_path, json_path):
    try:
        sf = shapefile.Reader(shp_path)
    except Exception as e:
        print(f"[SKIP] Cannot read {shp_path}: {e}")
        return

    fields = [f[0] for f in sf.fields[1:]]  # skip DeletionFlag
    name_field = detect_name_field(fields)

    if not name_field:
        print(f"[SKIP] No suitable name field in {shp_path}")
        return

    name_idx = fields.index(name_field)

    features = []
    for rec, shp in zip(sf.records(), sf.shapes()):
        name = rec[name_idx]
        if not name:
            continue

        # Normalize if Arabic
        if is_arabic(name):
            name = normalize_arabic(name)

        geom = shape(shp.__geo_interface__)
        coords = mapping(geom)['coordinates']  # all coordinates

        feature = {
            "name": name,
            "coordinates": coords
        }
        features.append(feature)

    if features:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(features, f, ensure_ascii=False, indent=2)
        print(f"[DONE] {json_path} -> {len(features)} features")
    else:
        print(f"[EMPTY] {json_path}")

# -----------------------------
# Process all SHP files in INPUT_FOLDER
for file in os.listdir(INPUT_FOLDER):
    if file.lower().endswith(".shp"):
        shp_path = os.path.join(INPUT_FOLDER, file)
        base_name = os.path.splitext(file)[0]
        json_path = os.path.join(OUTPUT_FOLDER, f"{base_name}.json")
        shp_to_json(shp_path, json_path)
