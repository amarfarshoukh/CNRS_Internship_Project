Incident Monitor - Starter Project
==================================

What is included:
- backend/
  - app.py       -> Flask API with endpoints: GET /incidents, GET /incidents/<id>, POST /report
  - db.json      -> simple JSON database (list of incidents)
  - requirements.txt

- frontend/
  - index.html   -> Single-file React + Leaflet frontend (uses CDN libs). Polls /incidents and posts to /report

Quick start (local development)
-------------------------------
1. Create a Python virtualenv and install requirements:
   python3 -m venv venv
   source venv/bin/activate
   pip install -r backend/requirements.txt

2. Run the backend:
   cd backend
   python app.py

3. Open your browser to http://localhost:5000/ (the Flask server serves the frontend)

Notes:
- This is a prototype. In production, use PostgreSQL/PostGIS and a proper React build (Vite/CRA).
- The frontend is intentionally simple (CDN + single file) so you can iterate quickly.
