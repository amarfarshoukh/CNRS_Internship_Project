import asyncio
import json
import os
import re
import subprocess
import ast
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import qrcode

# -----------------------------
# CONFIG
# -----------------------------
GEOJSON_FOLDER = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output"
OUTPUT_FILE = "matched_incidents.json"
OLLAMA_MODEL = "phi3:mini"
MAX_NUMBER_LEN = 6
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'
PHI3_TIMEOUT = 60

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
    return re.sub(r"\s+", " ", text).strip()

def is_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text))

# -----------------------------
# Load GeoJSON locations
# -----------------------------
def extract_centroid(coords):
    if not coords:
        return None
    if isinstance(coords[0], list):
        points = coords[0] if isinstance(coords[0][0], list) else coords
    else:
        points = [coords]
    lon = sum([p[0] for p in points]) / len(points)
    lat = sum([p[1] for p in points]) / len(points)
    return [lon, lat]

def load_geojson_file(file_path):
    if not os.path.exists(file_path):
        return {}
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    features = data.get('features', data) if isinstance(data, dict) else data
    norm_map = {}
    for item in features:
        props = item.get('properties', item) if isinstance(item, dict) else item
        name = props.get('name') or item.get('name')
        coords = item.get('geometry', {}).get('coordinates') if 'geometry' in item else item.get('coordinates')
        if name and coords and is_arabic(name):
            try:
                centroid = extract_centroid(coords)
            except Exception:
                centroid = None
            norm_map[normalize_arabic(name)] = {"original": name, "coordinates": centroid}
    return norm_map

def load_all_geojson_folder(folder_path):
    all_map = {}
    for file in os.listdir(folder_path):
        if file.lower().endswith('.json'):
            file_path = os.path.join(folder_path, file)
            locations = load_geojson_file(file_path)
            all_map.update(locations)
    return all_map

ALL_LOCATIONS = load_all_geojson_folder(GEOJSON_FOLDER)
print(f"Loaded {len(ALL_LOCATIONS)} Arabic locations from GeoJSON folder")

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
# Helper: check for incident keywords
# -----------------------------
def find_incident_type(text, incident_keywords):
    norm_text = normalize_arabic(text)
    for inc_type, keywords in incident_keywords.items():
        for kw in keywords:
            if kw in norm_text:
                return inc_type
    return None

# -----------------------------
# Robust Phi3 JSON Extractor
# -----------------------------
def robust_json_extract(text):
    # Remove markdown code block markers
    text = re.sub(r'```json|```', '', text).strip()
    # Remove triple quotes if present
    text = re.sub(r'^"{3,}', '', text).strip()
    text = re.sub(r'"{3,}$', '', text).strip()
    # Remove any lines that start with // (comments)
    lines = text.splitlines()
    lines = [line for line in lines if not line.strip().startswith("//")]
    text = "\n".join(lines)
    # Find the first and last curly brace
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end+1]
        try:
            return json.loads(json_str)
        except Exception:
            try:
                # fallback: safely evaluate literal JSON-like dict
                return ast.literal_eval(json_str)
            except Exception as e:
                print("Phi3 returned invalid JSON after cleanup:", json_str)
                return None
    print("Could not find JSON object in:", text)
    return None

# -----------------------------
# Phi3 JSON query (strict prompt)
# -----------------------------
def query_phi3_json(message: str):
    prompt = f"""
You are an incident analysis assistant.
Return ONLY valid JSON. Do NOT include any explanations, comments, or markdown (no code blocks, no // comments, no extra notes).
Just output a single JSON object like:
{{"location": ..., "incident_type": ..., "threat_level": ..., "casualties": [...], "numbers": [...]}}

Message: "{message}"

Rules:
- Only consider incidents inside Lebanon
- Detect incident type using Arabic keywords first; if detected, keep it
- Never include explanations or any extra text outside JSON
- Always use double quotes for keys and string values
- If location cannot be determined in Lebanon, use "Unknown / Outside Lebanon"
"""

    try:
        res = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PHI3_TIMEOUT
        )
        text = res.stdout.decode("utf-8", errors="ignore").strip()
        return robust_json_extract(text)
    except Exception as e:
        print("Phi3 call failed:", e)
        return None

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
# Deduplication
# -----------------------------
def select_best_message(records):
    records.sort(key=lambda m: (
        len(m['details'].get('numbers_found', [])) +
        len(m['details'].get('casualties', [])) +
        len(m['details'].get('summary', ''))
    ), reverse=True)
    return records[0]

# -----------------------------
# Phi3 worker queue
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

            # Priority: check incident_keywords first
            incident_type = find_incident_type(text, IK.incident_keywords)

            if incident_type:
                # Use extracted incident_type, no Phi3 call
                threat_level = "yes"  # Or implement your own logic if needed
            else:
                # Fallback to Phi3 for incident type extraction
                phi3_res = query_phi3_json(text)
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

            # Deduplicate
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
# Telegram login
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
    await client.start()
    await qr_login(client)
    channels = await get_my_channels(client)
    channel_ids = [c.id for c in channels]
    print(f"Monitoring {len(channel_ids)} channels...")

    matches = load_existing_matches()
    existing_ids = {(m.get('channel'), m.get('message_id')) for m in matches}

    asyncio.create_task(phi3_worker(matches, existing_ids))

    @client.on(events.NewMessage(chats=channel_ids))
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