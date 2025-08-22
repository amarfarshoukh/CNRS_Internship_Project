# Incident Map Starter (Leaflet + Flask)

## What you get

- Backend: Flask API serving /api/incidents from backend/data/incidents.json
- Frontend: Leaflet map with clustering, type filters, search, and optional Lebanon boundary overlay.
- Sample data: 6 incidents in Lebanon so you can see it working immediately.

## How to run (Windows)

1. Open Command Prompt and cd to this folder:
   cd incident-map-starter

2. Create & activate a virtual environment:
   python -m venv venv
   venv\Scripts\activate

3. Install dependencies:
   pip install flask flask-cors

4. Start the backend:
   python backend\app.py

   The app serves the frontend at http://127.0.0.1:5000

5. Open your browser at:
   http://127.0.0.1:5000

## Replacing sample data with your Telegram pipeline

- Your pipeline should write JSON objects into backend/data/incidents.json
  with this format (array of objects):
  [
  {
  "id": "unique-id",
  "type": "accident|fire|protest|roadblock|shooting|explosion|weather|other",
  "severity": 1-5,
  "text": "Short description",
  "city": "City name",
  "lat": 33.9,
  "lon": 35.5,
  "ts": "2025-08-22T18:00:00Z",
  "source_url": "https://t.me/..."
  },
  ...
  ]

## Lebanon-only map view

- The map is constrained to a Lebanon bounding box so users cannot pan away.
- (Optional) Export your Lebanon boundary from QGIS as GeoJSON and overwrite
  frontend/lebanon.geojson to draw the outline. No extra configuration needed.

## Tips

- The map auto-refreshes every 30 seconds. Click "Refresh" for manual refresh.
- Use the Type checkboxes and the search box to filter what you see.
- Circle size reflects severity; color reflects type.

## Common issues

- If the page is blank, check the browser console (F12) for errors.
- If /api/incidents returns 0 items, verify backend/data/incidents.json exists
  and is valid JSON.
