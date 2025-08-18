import asyncio
import csv
import json
import os
import re
import subprocess
from telethon import TelegramClient, events
from telethon.tl.types import Channel

# =============================
# INCIDENT KEYWORDS
# =============================
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': ['حريق','احتراق','نار','اشتعال','حرق','الدفاع المدني','إطفاء','نيران'],
                     'en': ['fire','burning','flames','blaze','ignite','combustion']},
            'accident': {'ar': ['حادث','حادثة','اصطدام','تصادم','سقوط','دهس'],
                         'en': ['accident','crash','collision','wreck','road']},
            'shooting': {'ar': ['إطلاق نار','رصاص','مسلح','هجوم مسلح'],
                         'en': ['shooting','gunfire','shots','armed']},
            'earthquake': {'ar': ['زلزال','هزة أرضية','نشاط زلزالي'],
                           'en': ['earthquake','seismic','tremor','quake']},
            'flood': {'ar': ['فيضان','سيول','أمطار','غرق'],
                      'en': ['flood','flooding','overflow','deluge']},
            'explosion': {'ar': ['انفجار','تفجير','عبوة ناسفة'],
                          'en': ['explosion','detonation','blast']},
            'protest': {'ar': ['احتجاج','تظاهرة','مظاهرة'],
                        'en': ['protest','demonstration','riot']},
            'medical': {'ar': ['إسعاف','مستشفى','طوارئ'],
                        'en': ['ambulance','hospital','emergency']}
            # Add more incident types as needed
        }

        self.casualty_keywords = {
            'killed': {'ar': ['قتيل','شهيد','وفاة'],
                       'en': ['killed','dead','death']},
            'injured': {'ar': ['جريح','مصاب'],
                        'en': ['injured','wounded']},
            'missing': {'ar': ['مفقود','اختفى'],
                        'en': ['missing','lost']}
        }

    def all_keywords(self):
        kws = []
        for cat in self.incident_keywords.values():
            for lang_list in cat.values():
                kws.extend([kw.lower() for kw in lang_list])
        for cat in self.casualty_keywords.values():
            for lang_list in cat.values():
                kws.extend([kw.lower() for kw in lang_list])
        return set(kws)

    def get_incident_type(self, text):
        text_lower = text.lower()
        for incident_type, langs in self.incident_keywords.items():
            for words in langs.values():
                if any(kw in text_lower for kw in words):
                    return incident_type
        return "other"

# =============================
# LOAD LEBANON LOCATIONS FROM CSV
# =============================
CSV_PATH = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.csv"

LEBANON_LOCATIONS = {}   # { governorate: [neighborhoods] }
ALL_LOCATIONS = set()    # flat list of all locations

if os.path.exists(CSV_PATH):
    with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            gov = row.get('NAME_1', '').strip()
            nb = row.get('NAME_3', '').strip()
            if gov:
                if gov not in LEBANON_LOCATIONS:
                    LEBANON_LOCATIONS[gov] = set()
                if nb:
                    LEBANON_LOCATIONS[gov].add(nb)
                    ALL_LOCATIONS.add(nb)
                ALL_LOCATIONS.add(gov)
                name2 = row.get('NAME_2', '').strip()
                if name2:
                    ALL_LOCATIONS.add(name2)
else:
    print("❌ CSV file not found:", CSV_PATH)

# =============================
# LOCATION EXTRACTION
# =============================
def extract_location(text):
    if not text or "غير محدد" in text or "undefined" in text.lower():
        return "Unknown / Outside Lebanon"
    for loc in ALL_LOCATIONS:
        if loc and loc in text:
            return loc
    return None  # fallback to Phi3 later

# =============================
# DETAILS EXTRACTION
# =============================
def extract_important_details(text):
    numbers = re.findall(r"\d+", text)
    casualties = []
    ik = IncidentKeywords()
    text_lower = text.lower()
    for cat, langs in ik.casualty_keywords.items():
        for words in langs.values():
            if any(kw in text_lower for kw in words):
                casualties.append(cat)
    return {
        "numbers_found": numbers,
        "casualties": list(set(casualties)),
        "summary": text[:120] + "..." if len(text) > 120 else text
    }

# =============================
# QUERY PHI3
# =============================
def query_phi3(message):
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
    result = subprocess.run(
        ["ollama", "run", "phi3:mini"],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return result.stdout.decode("utf-8").strip()

def extract_json(response_text):
    response_text = re.sub(r"```.*?```", "", response_text, flags=re.DOTALL)
    match = re.search(r"\{.*?\}", response_text, re.DOTALL)
    if match:
        return match.group()
    return None

# =============================
# TELEGRAM SETUP
# =============================
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'
output_file = 'matched_incidents.json'

async def qr_login(client):
    if not await client.is_user_authorized():
        print("Not authorized. Scan QR code:")
        qr_login = await client.qr_login()
        qr_url = qr_login.url
        import qrcode
        qr = qrcode.QRCode()
        qr.add_data(qr_url)
        qr.make()
        qr.print_ascii(invert=True)
        await qr_login.wait()
        print("Logged in!")
    else:
        print("Already authorized!")

async def get_my_channels(client):
    channels = []
    async for dialog in client.iter_dialogs():
        if isinstance(dialog.entity, Channel):
            channels.append(dialog.entity)
    return channels

# =============================
# PROCESS MESSAGE
# =============================
async def process_message(event):
    text = event.raw_text
    if not text:
        return

    ik = IncidentKeywords()
    keywords_set = ik.all_keywords()

    # Initial keyword match
    incident_type = ik.get_incident_type(text)
    threat_level = "no" if "لا تهديد" in text else "yes"
    location = extract_location(text)

    # Use Phi3 if location unknown or incident_type is 'other'
    if not location or incident_type == "other":
        response = query_phi3(text)
        json_text = extract_json(response)
        if json_text:
            try:
                data_phi = json.loads(json_text)
                location = location or data_phi.get("location", "Unknown / Outside Lebanon")
                incident_type = incident_type if incident_type != "other" else data_phi.get("incident_type", "other")
                threat_level = data_phi.get("threat_level", threat_level)
            except:
                pass
        else:
            location = location or "Unknown / Outside Lebanon"

    details = extract_important_details(text)

    channel_name = event.chat.username if event.chat else str(event.chat_id)
    msg_id = event.id

    # Save to JSON
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                matched_messages = json.load(f)
        except:
            matched_messages = []
    else:
        matched_messages = []

    existing_ids = {(msg.get('channel'), msg.get('message_id')) for msg in matched_messages}
    if (channel_name, msg_id) not in existing_ids:
        msg_data = {
            "incident_type": incident_type,
            "location": location,
            "channel": channel_name,
            "message_id": msg_id,
            "date": str(event.date),
            "threat_level": threat_level,
            "details": details
        }
        matched_messages.append(msg_data)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(matched_messages, f, ensure_ascii=False, indent=2)

        print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

# =============================
# MAIN FUNCTION
# =============================
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)
    channels = await get_my_channels(client)
    print(f"Monitoring {len(channels)} channels...")
    print("Started monitoring...")

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        await process_message(event)

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
