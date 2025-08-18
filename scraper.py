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
MAX_NUMBER_LEN = 6   # filter out numbers longer than this (likely IDs). Adjust as needed.

# Telegram API (use your values)
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
    "]+")

def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for matching: remove diacritics, normalize alef/hamza/yaa, remove punctuation/tatweel, collapse spaces."""
    if not text:
        return ""
    text = str(text)
    # remove diacritics/tashkeel
    text = RE_DIACRITICS.sub("", text)
    # tatweel
    text = text.replace('\u0640', '')
    # normalize alef variants to ا
    text = re.sub(r"[إأآا]", "ا", text)
    # normalize hamza on waw/ya
    text = re.sub(r"[ؤ]", "و", text)
    text = re.sub(r"[ئ]", "ي", text)
    # normalize taa marbuta to ه/ت? keep as ه? many systems map ة -> ه or ت; we'll map to ه to improve matching
    text = text.replace('ة', 'ه')
    # normalize ya variants
    text = re.sub(r"[يى]", "ي", text)
    # remove punctuation (Arabic + ASCII)
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    # remove extra spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text

# remove common prefixes like "منطقة", "بلدة", "مدينة", "حي", "قضاء", "بلدية"
COMMON_LOCATION_PREFIXES = [
    "منطقة", "منطقة ", "بلدة", "بلدة ", "بلدية", "مدينة", "حي", "قضاء", "منطقة", "بلدة", "محافظة", "قضاء"
]

def strip_location_prefixes(text: str) -> str:
    """Remove common prefixes before matching to help matching 'منطقة بشامون' -> 'بشامون'."""
    t = text
    for pref in COMMON_LOCATION_PREFIXES:
        # remove prefix if at word boundary
        t = re.sub(rf"\b{re.escape(pref)}\b\s*", "", t)
    return t

# -----------------------------
# Load locations from CSV
# -----------------------------
def load_locations_from_csv(csv_path: str):
    """Return set of normalized location names -> original mapping."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # Attempt to read typical column names; be permissive
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # find candidate column names
    # common names in your CSV: NAME_0, NAME_1, NAME_2, NAME_3
    candidate_cols = [c for c in (reader.fieldnames or [])]
    # choose columns that match name patterns (case-insensitive)
    name_cols = {c for c in candidate_cols if c.lower() in ('name_0','name_1','name_2','name_3','name0','name1','name2','name3')}
    # fallback: use first 4 columns if not present
    if not name_cols:
        name_cols = set(candidate_cols[:4])

    norm_to_original = {}  # normalized_name -> original_name (prefer Arabic form)
    all_originals = set()
    for r in rows:
        # prefer NAME_1 (governorate), NAME_2, NAME_3 (neighborhood)
        name_1 = r.get('NAME_1') or r.get('name_1') or r.get('NAME_1'.lower()) or r.get(list(r.keys())[0], "")
        name_2 = r.get('NAME_2') or r.get('name_2') or (r.get(list(r.keys())[1]) if len(r.keys())>1 else "")
        name_3 = r.get('NAME_3') or r.get('name_3') or (r.get(list(r.keys())[2]) if len(r.keys())>2 else "")

        for candidate in (name_3, name_2, name_1):
            if candidate:
                candidate = candidate.strip()
                if candidate:
                    all_originals.add(candidate)
                    # normalized key
                    normalized = normalize_arabic(strip_location_prefixes(candidate))
                    if normalized and normalized not in norm_to_original:
                        norm_to_original[normalized] = candidate

    return norm_to_original, all_originals

# load at startup
try:
    NORM_LOC_MAP, ALL_ORIGINAL_LOCATIONS = load_locations_from_csv(CSV_PATH)
    # Also build a normalized set for fast search
    NORMALIZED_LOCATIONS = set(NORM_LOC_MAP.keys())
    print(f"Loaded {len(NORMALIZED_LOCATIONS)} normalized locations from CSV.")
except Exception as e:
    print("Error loading CSV:", e)
    NORM_LOC_MAP = {}
    NORMALIZED_LOCATIONS = set()
    ALL_ORIGINAL_LOCATIONS = set()

# -----------------------------
# Location extraction (DB-first, robust)
# -----------------------------
def extract_location_db_first(text: str):
    """Try to find a location in CSV using normalized matching.
       Returns (location_original_name or None, normalized_key or None).
    """
    if not text:
        return None, None

    text_norm = normalize_arabic(text)
    # remove prefixes like "منطقة" before searching
    text_norm_stripped = strip_location_prefixes(text_norm)

    # Quick exact substring search on normalized forms
    # We check longer location names first to avoid partial collisions
    sorted_locs = sorted(NORMALIZED_LOCATIONS, key=lambda s: -len(s))
    for nloc in sorted_locs:
        if not nloc:
            continue
        if nloc in text_norm or nloc in text_norm_stripped:
            return NORM_LOC_MAP.get(nloc), nloc

    # try token-by-token matching: if any token equals a loc
    tokens = re.split(r"\s+", text_norm_stripped)
    for t in tokens:
        if t in NORMALIZED_LOCATIONS:
            return NORM_LOC_MAP.get(t), t

    return None, None

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
    def all_keywords(self):
        kws = set()
        for cat in self.incident_keywords.values():
            for lst in cat.values():
                kws.update([w.lower() for w in lst])
        for cat in self.casualty_keywords.values():
            for lst in cat.values():
                kws.update([w.lower() for w in lst])
        return kws
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
        # find arabic-indic or latin digits
        nums = re.findall(r"[0-9]+|[٠-٩]+", text)
        # convert arabic-indic digits to latin equivalent for counting/usage
        conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        cleaned = []
        for n in nums:
            n_norm = n.translate(conv)
            # filter out very long numeric strings that are likely IDs (tweak threshold)
            if len(n_norm) <= MAX_NUMBER_LEN:
                cleaned.append(n_norm)
        return cleaned

IK = IncidentKeywords()

# -----------------------------
# Phi3 helpers
# -----------------------------
def query_phi3_json(message: str):
    """Ask phi3 to return only JSON with location, incident_type, threat_level."""
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
        # remove markdown triple backticks and extract first {...}
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
        print("Scan the above QR from Telegram > Settings > Devices > Link Desktop Device")
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

        # 1) Database-first location (robust)
        db_loc, db_norm = extract_location_db_first(text)
        if db_loc:
            location = db_loc
            location_known_by_db = True
        else:
            location = None
            location_known_by_db = False

        # 2) Keyword quick check for incident_type (helps but final decision will use Phi3)
        keyword_type = IK.get_incident_type_by_keywords(text)
        # 3) threat quick check
        threat_quick = "no" if "لا تهديد" in normalize_arabic(text) else None

        # 4) Always call Phi3 for final classification (you wanted Phi3 validation always)
        phi3_res = query_phi3_json(text)
        incident_type = keyword_type or (phi3_res.get("incident_type") if phi3_res else "other")
        # If both exist, prefer phi3 but keep keyword result if phi3 missing:
        if phi3_res and phi3_res.get("incident_type"):
            incident_type = phi3_res.get("incident_type")
        # threat level: prefer quick detection by phrase, otherwise phi3, default "yes"
        if threat_quick is not None:
            threat_level = threat_quick
        else:
            threat_level = (phi3_res.get("threat_level") if phi3_res and phi3_res.get("threat_level") else "yes")

        # 5) If DB had no location, accept phi3 location only if it's not "Unknown / Outside Lebanon"
        if not location_known_by_db:
            if phi3_res and phi3_res.get("location") and "Unknown" not in phi3_res.get("location"):
                location = phi3_res.get("location")
            else:
                location = "Unknown / Outside Lebanon"

        # 6) Extract numbers & casualties (filtering long IDs)
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
        # Helpful logging
        if not location_known_by_db and location == "Unknown / Outside Lebanon":
            print(f"⚠️ Location unknown (DB & Phi3): {summary}")
        print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        # process concurrently but don't flood
        asyncio.create_task(process_event(event))

    print("Started monitoring. Waiting for new messages...")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
