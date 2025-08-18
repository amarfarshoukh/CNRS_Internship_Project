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
MAX_NUMBER_LEN = 6  # filter out numbers longer than this (likely IDs)

# Telegram API (use your values)
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

# -----------------------------
# Arabic normalization helpers
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
    text = text.replace('\u0640', '')  # tatweel
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
        for key in ['NAME_0', 'NAME_1', 'NAME_2', 'NAME_3']:
            val = r.get(key)
            if val:
                normalized = normalize_arabic(val.strip())
                if normalized and normalized not in norm_to_original:
                    norm_to_original[normalized] = val.strip()
    return norm_to_original

# load at startup
try:
    NORM_LOC_MAP = load_locations_from_csv(CSV_PATH)
    NORMALIZED_LOCATIONS = set(NORM_LOC_MAP.keys())
    print(f"Loaded {len(NORMALIZED_LOCATIONS)} normalized locations from CSV.")
except Exception as e:
    print("Error loading CSV:", e)
    NORM_LOC_MAP = {}
    NORMALIZED_LOCATIONS = set()

# -----------------------------
# Location extraction
# -----------------------------
def extract_location_db_first(text: str):
    if not text:
        return None

    text_norm = normalize_arabic(text)
    # Longest match first
    sorted_locs = sorted(NORMALIZED_LOCATIONS, key=lambda s: -len(s))
    for nloc in sorted_locs:
        if nloc in text_norm:
            return NORM_LOC_MAP[nloc]
    return None

# -----------------------------
# Incident keywords & details
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
# Phi3 helpers
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
- If the message contains phrases like "لا تهديد", threat_level must be "no".
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
        print("Scan QR code:")
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
    print(f"Logged in. Monitoring {len(channels)} channels...")

    matches = load_existing_matches()
    existing_ids = {(m.get('channel'), m.get('message_id')) for m in matches}

    async def process_event(event):
        text = event.raw_text or ""
        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id

        if (channel_name, msg_id) in existing_ids:
            return

        # 1) Database-first location
        db_loc = extract_location_db_first(text)
        location = db_loc if db_loc else None

        # 2) Keyword quick check for incident_type
        keyword_type = IK.get_incident_type_by_keywords(text)

        # 3) threat quick check
        threat_quick = "no" if "لا تهديد" in normalize_arabic(text) else None

        # 4) Phi3 always
        phi3_res = query_phi3_json(text)

        # Incident type: prefer Phi3 if exists
        incident_type = phi3_res.get("incident_type") if phi3_res and phi3_res.get("incident_type") else keyword_type or "other"

        # Threat level
        threat_level = threat_quick if threat_quick is not None else (phi3_res.get("threat_level") if phi3_res else "yes")

        # Location: DB first; if not DB, check Phi3 only if in Lebanon
        if not location:
            if phi3_res and phi3_res.get("location") and "Unknown" not in phi3_res.get("location"):
                location = phi3_res.get("location")
            else:
                # message is outside Lebanon or unknown; skip
                return

        # Extract numbers & casualties
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
