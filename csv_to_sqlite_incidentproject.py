import pandas as pd
import sqlite3
import os

# ------------------------------
# File paths
# ------------------------------
csv_path = r"C:\Users\user\OneDrive - Lebanese University\Desktop\lebanon_locations-arabic.csv"
db_path = "lebanon_locations.db"
chunksize = 100_000  # adjust if needed

# ------------------------------
# Count total rows (optional)
# ------------------------------
print(f"Estimating total number of lines in {csv_path} (this may take a while)...")
with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
    total_lines = sum(1 for _ in f)
total_rows = total_lines - 1  # subtract header
print(f"Estimated total rows (excluding header): {total_rows}")

# ------------------------------
# Connect to SQLite
# ------------------------------
print(f"Connecting to SQLite DB at {db_path}...")
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode = OFF;")
conn.execute("PRAGMA synchronous = OFF;")

# ------------------------------
# Create table if not exists
# ------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS locations (
    NAME_0 TEXT,
    NAME_1 TEXT,
    NAME_2 TEXT,
    NAME_3 TEXT
)
""")

# ------------------------------
# Import CSV in chunks
# ------------------------------
rows_inserted = 0
chunk_num = 0
print("Starting CSV import in chunks...")

for chunk in pd.read_csv(csv_path, dtype=str, chunksize=chunksize, encoding='utf-8'):
    chunk.to_sql("locations", conn, if_exists="append", index=False)
    rows_inserted += len(chunk)
    chunk_num += 1
    pct = (rows_inserted / total_rows) * 100
    print(f"Chunk {chunk_num}: Inserted {rows_inserted}/{total_rows} rows ({pct:.2f}%)")

# ------------------------------
# Create index for fast lookup
# ------------------------------
# If you have a unique ID column in your CSV, replace "NAME_3" below with that column
print("Creating index for fast lookup...")
conn.execute("CREATE INDEX IF NOT EXISTS idx_name3 ON locations(NAME_3);")

conn.commit()
conn.close()
print("CSV successfully imported to SQLite and indexed!")
