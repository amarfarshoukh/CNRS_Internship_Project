import asyncio
import csv
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
CSV_PATH = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.csv"
OUTPUT_FILE = "matched_incidents.json"
OLLAMA_MODEL = "phi3:mini"

# Telegram API (use your values)
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

MAX_NUMBER_LEN = 6

# -----------------------------
# Arabic normalization helpers
# -----------------------------
RE_DIACRITICS = re.compile("[" + "\u0610-\u061A\u064B-\u065F\u06D6-\u06ED" + "]+")
def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = str(text)
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
# Load locations from CSV
# -----------------------------
def load_locations_from_csv(csv_path: str):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    norm_to_original = {}
    for r in rows:
        for key in ['NAME_3', 'NAME_2', 'NAME_1']:
            candidate = r.get(key) or ""
            candidate = candidate.strip()
            if candidate:
                normalized = normalize_arabic(candidate)
                if normalized not in norm_to_original:
                    norm_to_original[normalized] = candidate
    return norm_to_original

try:
    NORM_LOC_MAP = load_locations_from_csv(CSV_PATH)
    NORMALIZED_LOCATIONS = set(NORM_LOC_MAP.keys())
    print(f"Loaded {len(NORMALIZED_LOCATIONS)} locations from CSV.")
except Exception as e:
    print("Error loading CSV:", e)
    NORM_LOC_MAP = {}
    NORMALIZED_LOCATIONS = set()

# -----------------------------
# Incident keywords & details
# -----------------------------
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'vehicle_accident': ['حادث سير','تصادم','دهس','انقلاب'],
            'shooting': ['إطلاق نار','رصاص','مسلح','هجوم مسلح','اشتباك'],
            'protest': ['احتجاج','مظاهرة','تظاهرة','اعتصام'],
            'fire': ['حريق','احتراق','نار','اشتعال','اندلاع','دخان'],
            'natural_disaster': ['زلزال','هزة أرضية','فيضان','سيول','انهيار أرضي'],
            'airstrike': ['طيران حربي', 'غارة جوية', 'قصف', 'صاروخ', 'قنبلة'],
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
                    break
        return list(set(cats))
    def extract_numbers(self, text):
        nums = re.findall(r"[0-9]+|[٠-٩]+", text)
        conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        cleaned = [n.translate(conv) for n in nums if len(n.translate(conv)) <= MAX_NUMBER_LEN]
        return cleaned

IK = IncidentKeywords()

# -----------------------------
# Phi3 helpers
# -----------------------------
def query_phi3_json(message: str):
    prompt = f"""
You are an incident analysis assistant.
Task: Analyze the following incident report and return ONLY valid JSON.

Message: "{message}"

Rules:
1) Choose the incident_type from this list ONLY:
['vehicle_accident','shooting','protest','fire','natural_disaster','airstrike','collapse','pollution','epidemic','medical','explosion']
2) If the message is not an incident or outside Lebanon, respond with incident_type 'other'.
3) Determine the exact location if inside Lebanon; otherwise use 'Unknown / Outside Lebanon'.
4) Threat level: 'yes' or 'no'. If the message contains phrases like 'لا تهديد', use 'no'.
5) Respond in JSON ONLY.

Output JSON format:
{{
  "location": "Extracted location or 'Unknown / Outside Lebanon'",
  "incident_type": "Choose from the list above or 'other'",
  "threat_level": "yes or no"
}}
"""
    try:
        res = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60
        )
        text = res.stdout.decode("utf-8", errors="ignore").strip()
        text_clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        m = re.search(r"\{.*?\}", text_clean, flags=re.DOTALL)
        if m:
            return json.loads(m.group())
        return None
    except Exception as e:
        print("Phi3 call failed:", e)
        return None

# -----------------------------
# Telegram helpers
# -----------------------------
async def qr_login(client):
    if not await client.is_user_authorized():
        print("Not authorized. Scan QR code:")
        qr_login = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login.url)
        qr.make()
        qr.print_ascii(invert=True)
        await qr_login.wait()
        print("Logged in!")

async def get_my_channels(client):
    out = []
    async for d in client.iter_dialogs():
        if isinstance(d.entity, Channel):
            out.append(d.entity)
    return out

# -----------------------------
# Main processing
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

async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)
    channels = await get_my_channels(client)
    print(f"Monitoring {len(channels)} channels...")

    matches = load_existing_matches()
    existing_ids = {(m.get('channel'), m.get('message_id')) for m in matches}

    async def process_event(event):
        text = event.raw_text or ""
        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id

        if (channel_name, msg_id) in existing_ids:
            return

        # DB-first location
        db_loc = None
        text_norm = normalize_arabic(text)
        for loc_norm, loc_orig in NORM_LOC_MAP.items():
            if loc_norm in text_norm:
                db_loc = loc_orig
                break

        # Keyword incident type
        keyword_type = IK.get_incident_type_by_keywords(text)
        threat_quick = "no" if "لا تهديد" in normalize_arabic(text) else None

        # Phi3 check
        phi3_res = query_phi3_json(text)

        incident_type = None
        location = db_loc
        threat_level = threat_quick or "yes"

        # Use Phi3 response if needed
        if phi3_res:
            phi3_type = phi3_res.get("incident_type")
            phi3_loc = phi3_res.get("location")
            phi3_threat = phi3_res.get("threat_level")
            if not incident_type or phi3_type != 'other':
                incident_type = phi3_type or keyword_type or "other"
            if not location and phi3_loc and "Unknown" not in phi3_loc:
                loc_norm = normalize_arabic(phi3_loc)
                if loc_norm in NORMALIZED_LOCATIONS:
                    location = NORM_LOC_MAP[loc_norm]
            if not threat_level and phi3_threat:
                threat_level = phi3_threat

        # Skip if no location inside Lebanon or not relevant
        if not location:
            return
        if incident_type == "other":
            return

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
        matches.append(record)
        existing_ids.add((channel_name, msg_id))
        save_matches(matches)
        print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        asyncio.create_task(process_event(event))

    print("Started monitoring. Waiting for new messages...")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    asyncio.run(main())
