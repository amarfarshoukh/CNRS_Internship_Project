import asyncio
import json
import datetime
import os
import re
import qrcode
import sqlite3
import subprocess
from telethon import TelegramClient, events
from telethon.tl.types import Channel

# =============================
# INCIDENT KEYWORDS
# =============================
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': ['حريق','احتراق','نار','اشتعال','حرق','الدفاع المدني','إطفاء'],
                     'en': ['fire','burning','flames','burn','blaze','ignite','combustion']},
            'accident': {'ar': ['حادثة','حادث','حادث سير','تصادم','انقلاب','اصطدام','سير','طريق'],
                         'en': ['accident','car accident','traffic accident','crash','collision']},
            'earthquake': {'ar': ['زلزال','هزة','أرضية','زلازل','اهتزاز'],
                           'en': ['earthquake','seismic','tremor','quake','shake']},
            'airstrike': {'ar': ['غارة جوية','قصف','صاروخ','قنبلة','انفجار'],
                          'en': ['airstrike','bombing','missile','rocket','bomb','explosion']},
            'flood': {'ar': ['فيضان','سيول','أمطار','غرق','مياه'],
                      'en': ['flood','flooding','overflow','deluge','inundation']},
            'shooting': {'ar': ['إطلاق نار','رصاص','مسلح','هجوم مسلح'],
                         'en': ['shooting','gunfire','shots','gunman','armed','armed attack']},
            'explosion': {'ar': ['انفجار','تفجير','عبوة ناسفة','انفجار سيارة مفخخة','تفجير انتحاري'],
                          'en': ['explosion','detonation','blast','car bomb','suicide bombing']},
            'collapse': {'ar': ['انهيار','انهيار مبنى','انهيار جسر','انهيار أرضي'],
                         'en': ['collapse','building collapse','bridge collapse','landslide']},
            'pollution': {'ar': ['تلوث','تلوث مياه','تلوث هواء','تسرب نفطي','تسرب مواد كيميائية'],
                          'en': ['pollution','water contamination','air pollution','oil spill','chemical spill']},
            'epidemic': {'ar': ['وباء','انتشار مرض','حجر صحي','تفشي'],
                         'en': ['epidemic','disease outbreak','quarantine','pandemic','virus spread']},
            'medical': {'ar': ['الصليب الأحمر','إسعاف','إنعاش','إسعاف أولي','نجدة','مستشفى','طوارئ'],
                        'en': ['red crescent','ambulance','resuscitation','first aid','emergency','hospital']}
        }

        self.casualty_keywords = {
            'killed': {'ar': ['قتيل','قتلى','شهيد','شهداء','موت','وفاة'],
                       'en': ['killed','dead','death','fatality','died']},
            'injured': {'ar': ['جريح','جرحى','مصاب','مصابين','إصابة','جراح','كسر'],
                        'en': ['injured','wounded','hurt','casualty','victim']},
            'missing': {'ar': ['مفقود','مفقودين','اختفى','اختفاء','ضائع'],
                        'en': ['missing','lost','disappeared']}
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
# LOAD LEBANON LOCATIONS FROM SQLITE
# =============================
def load_locations_from_db(db_path="lebanon_locations.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT NAME_1, NAME_2, NAME_3 FROM locations WHERE NAME_0='لبنان'")
    rows = cursor.fetchall()
    conn.close()
    locations = set()
    for name_1, name_2, name_3 in rows:
        if name_1: locations.add(name_1.strip())
        if name_2: locations.add(name_2.strip())
        if name_3: locations.add(name_3.strip())
    return locations

LEBANON_LOCATIONS = load_locations_from_db()

# =============================
# LOCATION EXTRACTION
# =============================
def extract_location(text):
    if not text or "غير محدد" in text or "undefined" in text.lower():
        return "Unknown / Outside Lebanon"
    for loc in LEBANON_LOCATIONS:
        if loc in text:
            return loc
    return None  # None means let Phi3 analyze

# =============================
# DETAILS EXTRACTION
# =============================
def extract_important_details(text):
    numbers = re.findall(r"\d+", text)
    ik = IncidentKeywords()
    text_lower = text.lower()
    casualties = []
    for cat, langs in ik.casualty_keywords.items():
        for words in langs.values():
            if any(kw in text_lower for kw in words):
                casualties.append(cat)
    return {
        "numbers_found": numbers,
        "casualties": list(set(casualties)),
        "summary": text[:120]+"..." if len(text) > 120 else text
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
    - If the message contains phrases like "لا تهديد" (no threat), threat_level must be "no".
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
        qr = qrcode.QRCode()
        qr.add_data(qr_login.url)
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
# MAIN
# =============================
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)
    keywords = IncidentKeywords()
    keywords_set = keywords.all_keywords()
    channels = await get_my_channels(client)
    print(f"Monitoring {len(channels)} channels...")

    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                matched_messages = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            matched_messages = []
    else:
        matched_messages = []

    existing_ids = {(msg.get('channel'), msg.get('message_id')) for msg in matched_messages}

    async def process_message(event):
        text = event.raw_text
        if not text:
            return
        # Default keyword detection
        incident_type = keywords.get_incident_type(text)
        location = extract_location(text)
        threat_level = "no" if "لا تهديد" in text else "yes"

        # Use Phi3 if location or incident type uncertain
        if location is None or incident_type=="other":
            phi3_response = query_phi3(text)
            phi3_json_text = extract_json(phi3_response)
            if phi3_json_text:
                try:
                    phi3_data = json.loads(phi3_json_text)
                    if location is None:
                        location = phi3_data.get("location","Unknown / Outside Lebanon")
                    incident_type = phi3_data.get("incident_type", incident_type)
                    threat_level = phi3_data.get("threat_level", threat_level)
                except:
                    pass
            if location is None:
                location = "Unknown / Outside Lebanon"

        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id
        if (channel_name, msg_id) not in existing_ids:
            details = extract_important_details(text)
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
            existing_ids.add((channel_name, msg_id))
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(matched_messages, f, ensure_ascii=False, indent=4)
            print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

    @client.on(events.NewMessage())
    async def handler(event):
        await process_message(event)

    print("Started monitoring...")
    await client.run_until_disconnected()

# =============================
# RUN
# =============================
if __name__ == "__main__":
    asyncio.run(main())
