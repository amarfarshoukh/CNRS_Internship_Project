import asyncio
import json
import os
import re
import subprocess
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import qrcode

# -----------------------------
# CONFIG
# -----------------------------
CITIES_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\gis_osm_places_a_free_1.json"
ROADS_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\gis_osm_roads_free_1.json"
OUTPUT_FILE = "matched_incidents.json"
OLLAMA_MODEL = "phi3:mini"
MAX_NUMBER_LEN = 6
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

LOCATION_KEYWORDS = [
    "في", "في منطقة", "في حي", "في بلدة", "بالقرب من", "عند", "جنوب", "شمال", "شرق", "غرب"
]

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

def is_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text))

# -----------------------------
# Load locations from JSON with coordinates (custom structure)
# -----------------------------
def extract_centroid(coords):
    """
    Accepts coordinates as a list containing one polygon ring (list of [lon, lat]).
    Returns centroid [lon, lat].
    """
    if not coords or not isinstance(coords, list) or not coords[0]:
        return None
    ring = coords[0]
    lon = sum([p[0] for p in ring]) / len(ring)
    lat = sum([p[1] for p in ring]) / len(ring)
    return [lon, lat]

def load_geojson_locations(geojson_file):
    """
    Loads Arabic location names with coordinates from your custom JSON structure.
    Returns: {normalized_name: {"original": name, "coordinates": [lon, lat]}}
    Supports a file containing a list of dicts with 'name' and 'coordinates'.
    """
    if not os.path.exists(geojson_file):
        return {}
    with open(geojson_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    features = data if isinstance(data, list) else [data]
    norm_map = {}
    for item in features:
        name = item.get('name')
        coords = item.get('coordinates')
        if name and is_arabic(name) and coords:
            try:
                centroid = extract_centroid(coords)
            except Exception:
                centroid = None
            name_norm = normalize_arabic(name)
            norm_map[name_norm] = {"original": name, "coordinates": centroid}
    return norm_map

CITIES_MAP = load_geojson_locations(CITIES_JSON)
ROADS_MAP = load_geojson_locations(ROADS_JSON)
ALL_LOCATIONS = {**CITIES_MAP, **ROADS_MAP}

# -----------------------------
# Location detection
# -----------------------------
def detect_location_from_map(text_norm):
    words = text_norm.split()
    for loc_norm, loc_data in ALL_LOCATIONS.items():
        loc_words = loc_norm.split()
        for i in range(len(words) - len(loc_words) + 1):
            if words[i:i+len(loc_words)] == loc_words:
                return loc_data["original"], loc_data["coordinates"]
    return None, None

def detect_location(text):
    text_norm = normalize_arabic(text)
    for kw in LOCATION_KEYWORDS:
        if kw in text_norm:
            loc, coords = detect_location_from_map(text_norm)
            if loc:
                return loc, coords
    return detect_location_from_map(text_norm)

# -----------------------------
# Incident keywords
# -----------------------------
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'vehicle_accident': ['حادث سير','حوادث سير','تصادم','دهس','انقلاب'],
            'shooting': ['إطلاق نار','رصاص','مسلح','هجوم مسلح','اشتباك'],
            'protest': ['احتجاج','مظاهرة','تظاهرة','اعتصام'],
            'fire': ['حريق','احتراق','نار','اشتعال','اندلاع','دخان'],
            'natural_disaster': ['زلزال','هزة أرضية','فيضان','سيول','انهيار أرضي'],
            'airstrike': ["مسيرة", "طيران حربي", "غارة جوية", "قصف", "صاروخ", "قنبلة"],
            'collapse': ['انهيار','انهيار مبنى','سقوط'],
            'pollution': ['تلوث','تسرب نفطي','انسكاب'],
            'epidemic': ['وباء','تفشي','إصابات جماعية'],
            'medical': ['إسعاف','مستشفى','طوارئ','إنعاش'],
            'explosion': ['انفجار','تفجير','عبوة ناسفة'],
        }
        self.casualty_keywords = {
            'killed': ['قتيل','قتلى','شهيد','وفاة','مقتل'],
            'injured': ['جريح','جرحى','مصاب','إصابة'],
            'missing': ['مفقود','مفقودين','اختفى']
        }

    def extract_casualties(self, text):
        tl = text.lower()
        cats = []
        for cat, kws in self.casualty_keywords.items():
            for kw in kws:
                if kw in tl:
                    cats.append(cat)
        return list(set(cats))

    def extract_numbers(self, text):
        nums = re.findall(r"[0-9]+|[٠-٩]+", text)
        conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        cleaned = [n.translate(conv) for n in nums if len(n.translate(conv)) <= MAX_NUMBER_LEN]
        return cleaned

IK = IncidentKeywords()

# -----------------------------
# Phi3 async worker
# -----------------------------
async def query_phi3_json(message: str):
    prompt = f"""
You are an incident analysis assistant.
Task: Analyze the following incident report and return ONLY valid JSON.

Message: "{message}"

Output JSON format:
{{
  "location": "Extracted location or 'Unknown / Outside Lebanon'",
  "incident_type": "Choose one of: vehicle_accident, shooting, protest, fire, natural_disaster, airstrike, collapse, pollution, epidemic, medical, explosion, other",
  "threat_level": "yes or no"
}}

Important:
- Only return incidents that concern Lebanon.
- Respond with JSON only.
"""
    loop = asyncio.get_running_loop()
    def run_subprocess():
        try:
            res = subprocess.run(
                ["ollama", "run", OLLAMA_MODEL],
                input=prompt.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60
            )
            text = res.stdout.decode("utf-8", errors="ignore").strip()
            m = re.search(r"\{.*?\}", text, flags=re.DOTALL)
            if m:
                return json.loads(m.group())
            return None
        except Exception as e:
            print("Phi3 call failed:", e)
            return None
    return await loop.run_in_executor(None, run_subprocess)

# -----------------------------
# Load/save matches
# -----------------------------
def load_existing_matches(path=OUTPUT_FILE):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_matches(matches, path=OUTPUT_FILE):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)

# -----------------------------
# Deduplication helpers
# -----------------------------
def select_best_message(records):
    records.sort(key=lambda m: (
        len(m['details'].get('numbers_found', [])) +
        len(m['details'].get('casualties', [])) +
        len(m['details'].get('summary', ''))
    ), reverse=True)
    return records[0]

# -----------------------------
# Main Phi3 worker
# -----------------------------
message_queue = asyncio.Queue()

async def phi3_worker(matches, existing_ids):
    while True:
        event = await message_queue.get()
        try:
            text = event.raw_text or ""
            channel_name = event.chat.username if event.chat and getattr(event.chat, 'username', None) else str(event.chat_id)
            msg_id = event.id

            if (channel_name, msg_id) in existing_ids:
                continue

            has_kw = any(kw in normalize_arabic(text) for kw in LOCATION_KEYWORDS)
            location, coordinates = detect_location(text) if has_kw else (None, None)

            if not location or not coordinates:
                continue

            phi3_res = await query_phi3_json(text)
            if not phi3_res:
                continue

            incident_type = phi3_res.get("incident_type")
            if not incident_type or incident_type == "other":
                continue

            threat_level = phi3_res.get("threat_level", "yes")
            numbers = IK.extract_numbers(text)
            casualties = IK.extract_casualties(text)
            summary = text[:300] + ("..." if len(text) > 300 else "")

            record = {
                "incident_type": incident_type,
                "location": location,
                "coordinates": coordinates,
                "channel": channel_name,
                "message_id": msg_id,
                "date": str(event.date),
                "threat_level": threat_level,
                "details": {
                    "numbers_found": numbers,
                    "casualties": casualties,
                    "summary": summary
                }
            }

            # Deduplicate on incident_type, location, and date (date string up to day)
            date_prefix = record["date"][:10]
            similar_records = [
                m for m in matches
                if m.get('incident_type') == record['incident_type']
                and m.get('location') == record['location']
                and m.get('date', '')[:10] == date_prefix
            ]
            if similar_records:
                similar_records.append(record)
                best_record = select_best_message(similar_records)
                matches[:] = [
                    m for m in matches if not (
                        m.get('incident_type') == record['incident_type']
                        and m.get('location') == record['location']
                        and m.get('date', '')[:10] == date_prefix
                    )
                ]
                matches.append(best_record)
            else:
                matches.append(record)

            existing_ids.add((channel_name, msg_id))
            save_matches(matches)
            print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

        finally:
            message_queue.task_done()

# -----------------------------
# Telegram login / channels
# -----------------------------
async def qr_login(client):
    if not await client.is_user_authorized():
        print("Scan QR code:")
        qr_login_obj = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login_obj.url)
        qr.make()
        qr.print_ascii(invert=True)
        await qr_login_obj.wait()

async def get_my_channels(client):
    out = []
    async for d in client.iter_dialogs():
        if isinstance(d.entity, Channel):
            out.append(d.entity)
    return out

# -----------------------------
# Main async
# -----------------------------
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)
    channels = await get_my_channels(client)
    print(f"Monitoring {len(channels)} channels...")

    matches = load_existing_matches()
    existing_ids = {(m.get('channel'), m.get('message_id')) for m in matches}

    asyncio.create_task(phi3_worker(matches, existing_ids))

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        await message_queue.put(event)

    print("Started monitoring. Waiting for new messages...")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())