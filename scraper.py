import asyncio
import json
import os
import re
import subprocess
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import qrcode
from rapidfuzz import fuzz

# -----------------------------
# CONFIG
# -----------------------------
CITIES_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\cities.json"
ROADS_JSON = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output\roads.json"
OUTPUT_FILE = "matched_incidents.json"
OLLAMA_MODEL = "phi3:mini"
MAX_NUMBER_LEN = 6
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

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

# -----------------------------
# Load locations from GeoJSON
# -----------------------------
def load_geojson_names(geojson_file):
    if not os.path.exists(geojson_file):
        return {}
    with open(geojson_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    norm_map = {}
    for feature in data['features']:
        name = feature['properties'].get('name')
        if name:
            name_norm = normalize_arabic(name)
            norm_map[name_norm] = name
    return norm_map

CITIES_MAP = load_geojson_names(CITIES_JSON)
ROADS_MAP = load_geojson_names(ROADS_JSON)
ALL_LOCATIONS = {**CITIES_MAP, **ROADS_MAP}

# -----------------------------
# Location detection keywords
# -----------------------------
LOCATION_KEYWORDS = [
    "في", "في منطقة", "في حي", "في بلدة", "بالقرب من", "عند", "جنوب", "شمال", "شرق", "غرب"
]

def detect_location(text):
    text_norm = normalize_arabic(text)
    # fast check using keywords
    for kw in LOCATION_KEYWORDS:
        if kw in text_norm:
            # try to match any location from map
            loc = detect_location_from_map(text_norm)
            if loc:
                return loc
    # fallback: always check map
    return detect_location_from_map(text_norm)

def detect_location_from_map(text_norm):
    words = text_norm.split()
    for loc_norm, loc_original in ALL_LOCATIONS.items():
        loc_words = loc_norm.split()
        for i in range(len(words) - len(loc_words) + 1):
            if words[i:i+len(loc_words)] == loc_words:
                # Only accept locations that are not numeric and length > 1
                if not loc_original.strip().isdigit() and len(loc_original.strip()) > 1:
                    return loc_original
    return None

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
            "airstrike": ["مسيرة", "طيران حربي", "غارة جوية", "قصف", "صاروخ", "قنبلة"],
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

    def get_incident_type_by_keywords(self, text):
        if not text:
            return None
        tl = text.lower()
        for itype, kws in self.incident_keywords.items():
            for kw in kws:
                if kw in tl:
                    return itype
        return None

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
        except:
            return []
    return []

def save_matches(matches, path=OUTPUT_FILE):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)

# -----------------------------
# Deduplication helpers
# -----------------------------
def is_redundant(new_record, existing_records, threshold=85):
    new_text = new_record['details']['summary']
    new_type = new_record['incident_type']
    new_loc = new_record['location']

    for rec in existing_records:
        if rec['incident_type'] == new_type and rec['location'] == new_loc:
            old_text = rec['details']['summary']
            similarity = fuzz.token_set_ratio(new_text, old_text)
            if similarity >= threshold:
                return True
    return False

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
                continue  # task_done will still be called in finally

            location = detect_location(text)
            if not location:
                continue  # task_done will still be called in finally

            incident_type = IK.get_incident_type_by_keywords(text)
            phi3_res = None
            if not incident_type:
                phi3_res = await query_phi3_json(text)
                if phi3_res and phi3_res.get("incident_type") and phi3_res.get("incident_type") != "other":
                    incident_type = phi3_res.get("incident_type")
                else:
                    continue  # task_done will still be called in finally

            threat_level = "no" if "لا تهديد" in text else "yes"
            if phi3_res and phi3_res.get("threat_level"):
                threat_level = phi3_res.get("threat_level")

            numbers = IK.extract_numbers(text)
            casualties = IK.extract_casualties(text)
            summary = text[:300] + ("..." if len(text) > 300 else "")

            record = {
                "incident_type": incident_type,
                "location": location,
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

            # Deduplication
            similar_records = [
                m for m in matches
                if m.get('incident_type') == record['incident_type'] and m.get('location') == record['location']
            ]
            if similar_records:
                similar_records.append(record)
                best_record = select_best_message(similar_records)
                matches = [m for m in matches if not (m.get('incident_type') == record['incident_type'] and m.get('location') == record['location'])]
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
        qr_login = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login.url)
        qr.make()
        qr.print_ascii(invert=True)
        await qr_login.wait()

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
