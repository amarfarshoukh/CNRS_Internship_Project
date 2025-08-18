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
MAX_NUMBER_LEN = 6  # Filter out long numbers (likely IDs)

# Telegram API credentials
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

# -----------------------------
# Arabic normalization helpers
# -----------------------------
RE_DIACRITICS = re.compile(
    "[" +
    "\u0610-\u061A" +  # Arabic diacritics ranges
    "\u064B-\u065F" +
    "\u06D6-\u06ED" +
    "]+"
)

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
        for col in ['NAME_3', 'NAME_2', 'NAME_1']:
            candidate = r.get(col, "").strip()
            if candidate:
                normalized = normalize_arabic(candidate)
                if normalized not in norm_to_original:
                    norm_to_original[normalized] = candidate
    return norm_to_original

NORM_LOC_MAP = load_locations_from_csv(CSV_PATH)
NORMALIZED_LOCATIONS = set(NORM_LOC_MAP.keys())
print(f"Loaded {len(NORMALIZED_LOCATIONS)} normalized locations from CSV.")

# -----------------------------
# Incident keywords class
# -----------------------------
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'vehicle_accident': ['حادث سير','تصادم','دهس','انقلاب'],
            'shooting': ['إطلاق نار','رصاص','مسلح','هجوم مسلح','اشتباك'],
            'protest': ['احتجاج','مظاهرة','تظاهرة','اعتصام'],
            'fire': ['حريق','احتراق','نار','اشتعال','اندلاع','دخان'],
            'natural_disaster': ['زلزال','هزة أرضية','فيضان','سيول','انهيار أرضي'],
            'airstrike': ['غارة جوية','قصف','صاروخ','قنبلة'],
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
        cats = []
        text_lower = text.lower()
        for cat, kws in self.casualty_keywords.items():
            for kw in kws:
                if kw in text_lower:
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
# Phi3 query
# -----------------------------
def query_phi3_json(message: str):
    prompt = f"""
You are an incident analysis assistant.
Task: Analyze the following news report and return ONLY valid JSON.

Message: "{message}"

Output JSON format:
{{
  "location": "Extracted location or 'Unknown / Outside Lebanon'",
  "incident_type": "Choose one of: vehicle_accident, shooting, protest, fire, natural_disaster, airstrike, collapse, explosion, medical, epidemic, pollution, other",
  "threat_level": "yes or no"
}}

Important:
- Only return an incident if it affects government/public safety or emergency situations.
- If it is normal news or outside Lebanon, do not return any JSON (ignore the message).
- If the message contains phrases like "لا تهديد", set threat_level to "no".
- Respond with JSON only.
"""
    try:
        res = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25
        )
        text = res.stdout.decode("utf-8", errors="ignore").strip()
        m = re.search(r"\{.*?\}", text, flags=re.DOTALL)
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
        qr_login_task = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login_task.url)
        qr.make()
        qr.print_ascii(invert=True)
        await qr_login_task.wait()

async def get_my_channels(client):
    out = []
    async for d in client.iter_dialogs():
        if isinstance(d.entity, Channel):
            out.append(d.entity)
    return out

# -----------------------------
# Load & save matches
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
# Main event processing
# -----------------------------
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

        text_norm = normalize_arabic(text)
        location = None

        # 1) DB-first location
        for loc_norm, loc_original in NORM_LOC_MAP.items():
            if loc_norm in text_norm:
                location = loc_original
                break

        # 2) Phi3 fallback if no DB location
        phi3_res = None
        if not location:
            phi3_res = query_phi3_json(text)
            if not phi3_res:
                return  # Ignore if Phi3 fails
            phi3_loc = phi3_res.get("location", "Unknown / Outside Lebanon")
            if "Unknown" in phi3_loc:
                return  # Outside Lebanon -> ignore
            loc_norm = normalize_arabic(phi3_loc)
            location = NORM_LOC_MAP.get(loc_norm, phi3_loc)

        # 3) Incident type
        incident_type = None
        for itype, kws in IK.incident_keywords.items():
            for kw in kws:
                if kw in text_norm:
                    incident_type = itype
                    break
            if incident_type:
                break
        if not incident_type and phi3_res:
            incident_type = phi3_res.get("incident_type", "other")

        if incident_type == "other" and not phi3_res:
            # Not an incident, ignore
            return

        # 4) Threat level
        threat_level = "no" if "لا تهديد" in text_norm else "yes"
        if phi3_res and phi3_res.get("threat_level"):
            threat_level = phi3_res.get("threat_level")

        # 5) Numbers, casualties, summary
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
