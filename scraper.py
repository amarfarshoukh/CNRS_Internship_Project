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
MAX_NUMBER_LEN = 6   # filter out numbers longer than this (likely IDs)

# Telegram API
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

# -----------------------------
# Arabic normalization
# -----------------------------
RE_DIACRITICS = re.compile(
    "[" +
    "\u0610-\u061A" +
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
            val = r.get(col)
            if val:
                val = val.strip()
                if val:
                    norm = normalize_arabic(val)
                    if norm and norm not in norm_to_original:
                        norm_to_original[norm] = val
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
# Incident keywords
# -----------------------------
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': ['حريق','احتراق','نار','اشتعال','حرائق','اندلاع','دخان']},
            'shooting': {'ar': ['إطلاق نار','رصاص','مسلح','هجوم مسلح','اشتباك']},
            'accident': {'ar': ['حادث','حادثة','حادث سير','تصادم','انقلاب','دهس']},
            'protest': {'ar': ['احتجاج','مظاهرة','تظاهرة','اعتصام']},
            'natural_disaster': {'ar': ['زلزال','هزة أرضية','فيضان','سيول','انهيار أرضي']},
            'airstrike': {'ar': ['غارة جوية','قصف','صاروخ','قنبلة']},
            'collapse': {'ar': ['انهيار','انهيار مبنى','سقوط']},
            'pollution': {'ar': ['تلوث','تسرب نفطي','انسكاب']},
            'epidemic': {'ar': ['وباء','تفشي','إصابات جماعية']},
            'medical': {'ar': ['إسعاف','مستشفى','طوارئ','إنعاش']},
            'explosion': {'ar': ['انفجار','تفجير','عبوة ناسفة']},
        }
        self.casualty_keywords = {
            'killed': {'ar': ['قتيل','قتلى','شهيد','وفاة','مقتل']},
            'injured': {'ar': ['جريح','جرحى','مصاب','إصابة']},
            'missing': {'ar': ['مفقود','مفقودين','اختفى']}
        }
    def get_incident_type_by_keywords(self, text):
        if not text:
            return None
        tl = text.lower()
        for itype, langs in self.incident_keywords.items():
            for lst in langs.values():
                for kw in lst:
                    if kw in tl:
                        return itype
        return None
    def extract_casualties(self, text):
        tl = text.lower()
        cats = []
        for cat, langs in self.casualty_keywords.items():
            for lst in langs.values():
                for kw in lst:
                    if kw in tl:
                        cats.append(cat)
                        break
        return list(set(cats))
    def extract_numbers(self, text):
        nums = re.findall(r"[0-9]+|[٠-٩]+", text)
        conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        cleaned = []
        for n in nums:
            n_norm = n.translate(conv)
            if len(n_norm) <= MAX_NUMBER_LEN:
                cleaned.append(n_norm)
        return cleaned

IK = IncidentKeywords()

# -----------------------------
# Phi3 query
# -----------------------------
def query_phi3_json(message: str):
    prompt = f"""
You are an incident analysis assistant.
Task: Analyze the following incident report and return ONLY valid JSON.

Message: "{message}"

Output JSON format:
{{
  "location": "Extracted location or 'Unknown / Outside Lebanon'",
  "incident_type": "Choose one of: accident, shooting, protest, fire, natural_disaster, other",
  "threat_level": "yes or no"
}}

Important:
- If the message contains phrases like "لا تهديد" (no threat), threat_level must be "no".
- Respond with JSON only, no explanations.
"""
    try:
        res = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20
        )
        text = res.stdout.decode("utf-8", errors="ignore").strip()
        text_clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        m = re.search(r"\{.*?\}", text_clean, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                return None
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
    else:
        print("Already authorized!")

async def get_my_channels(client):
    out = []
    async for d in client.iter_dialogs():
        if isinstance(d.entity, Channel):
            out.append(d.entity)
    return out

# -----------------------------
# JSON storage
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
# Main processing
# -----------------------------
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)
    channels = await get_my_channels(client)
    print(f"Logged in. Monitoring {len(channels)} channels...")

    matches = load_existing_matches()
    existing_ids = {(m.get('channel'), m.get('message_id')) for m in matches}

    async def process_event(event):
        text = event.raw_text or ""
        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id

        if (channel_name, msg_id) in existing_ids:
            return

        # 1) DB-first location
        db_loc, db_norm = None, None
        text_norm = normalize_arabic(text)
        for loc_norm, loc_original in NORM_LOC_MAP.items():
            if loc_norm in text_norm:
                db_loc = loc_original
                break

        location = db_loc

        # 2) Keyword quick incident_type
        keyword_type = IK.get_incident_type_by_keywords(text)
        threat_quick = "no" if "لا تهديد" in normalize_arabic(text) else None

        # 3) Phi3 final check
        phi3_res = query_phi3_json(text)

        # Incident type: Phi3 preferred
        incident_type = phi3_res.get("incident_type") if phi3_res and phi3_res.get("incident_type") else (keyword_type or "other")

        # Threat level
        threat_level = threat_quick or (phi3_res.get("threat_level") if phi3_res and phi3_res.get("threat_level") else "yes")

        # Location: if not in DB, accept Phi3 only if it's in Lebanon
        if not location:
            if phi3_res and phi3_res.get("location") and "Unknown" not in phi3_res.get("location"):
                location_norm = normalize_arabic(phi3_res.get("location"))
                if location_norm in NORMALIZED_LOCATIONS:
                    location = NORM_LOC_MAP[location_norm]
        if not location:
            # Skip messages outside Lebanon
            return

        # Numbers & casualties
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

if __name__ == "__main__":
    asyncio.run(main())
