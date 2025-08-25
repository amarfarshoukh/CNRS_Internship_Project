import os
import shapefile

INPUT_FOLDER = r"C:\Users\user\Downloads\admin\admin"

seen = set()
total_records = 0

for file in os.listdir(INPUT_FOLDER):
    if file.lower().endswith(".shp"):
        base_name = os.path.splitext(file)[0]
        if base_name in seen:
            continue  # skip duplicates
        seen.add(base_name)

        shp_path = os.path.join(INPUT_FOLDER, file)
        try:
            sf = shapefile.Reader(shp_path)
            count = len(sf.records())
            print(f"{base_name}.shp → {count} records")
            total_records += count
        except Exception as e:
            print(f"[SKIP] Cannot read {file}: {e}")

print("\n==============================")
print(f"📊 TOTAL (unique files) = {total_records}")
print("==============================")
