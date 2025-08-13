import asyncio
import json
import datetime
import os
import re
import qrcode
import sqlite3
from telethon import TelegramClient, events
from telethon.tl.types import Channel

# =============================
# ARABIC DIGIT NORMALIZATION
# =============================
ARABIC_DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
def normalize_digits(text: str) -> str:
    return text.translate(ARABIC_DIGITS_MAP)

# =============================
# INCIDENT KEYWORDS
# =============================
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': ['حريق','احتراق','نار','اشتعال','حرق','الدفاع المدني','إطفاء','حراق','نيران'],
                     'en': ['fire','burning','flames','burn','blaze','ignite','combustion']},
            'accident': {'ar': ['حادثة','حادث','حادث سير','حادث مرور','تصادم','انقلاب','اصطدام'],
                         'en': ['accident','car accident','traffic accident','crash','collision','wreck']},
            'earthquake': {'ar': ['زلزال','هزة','أرضية','زلازل'],
                           'en': ['earthquake','seismic','tremor','quake']},
            'explosion': {'ar': ['انفجار','تفجير','عبوة ناسفة'],
                          'en': ['explosion','detonation','blast']},
        }

        self.casualty_keywords = {
            'killed': {'ar': ['قتيل','قتلى','شهيد','شهداء','وفاة','مات'],
                       'en': ['killed','dead','death','fatality']},
            'injured': {'ar': ['جريح','جرحى','مصاب','إصابة','كسر','رضوض'],
                        'en': ['injured','wounded','hurt','casualty']},
            'missing': {'ar': ['مفقود','مفقودين','اختفى'],
                        'en': ['missing','lost','disappeared']},
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
        return "unknown"

# =============================
# LEBANON LOCATIONS HIERARCHY
# =============================
db_path = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.db"

LEBANON_LOCATIONS = {}
ALL_LOCATIONS = set()

try:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT NAME_1, NAME_2, NAME_3
        FROM locations
        WHERE NAME_0 = 'لبنان'
    """)

    temp = {}
    for name_1, name_2, name_3 in cur.fetchall():
        gov = (name_1 or "").strip()
        nb  = (name_3 or "").strip()

        if not gov:
            continue

        if gov not in temp:
            temp[gov] = set()

        if nb:
            temp[gov].add(nb)

        ALL_LOCATIONS.update(filter(None, {gov, name_2, name_3}))

    for gov, nbs in temp.items():
        LEBANON_LOCATIONS[gov] = sorted(nbs)

finally:
    try:
        conn.close()
    except:
        pass

# =============================
# LOCATION EXTRACTION
# =============================
def extract_location(text):
    if not text:
        return None

    if "غير محدد" in text or "undefined" in text.lower():
        return None

    for loc in ALL_LOCATIONS:
        if loc and loc in text:
            return loc
    return None

# =============================
# DETAILS EXTRACTION
# =============================
def extract_important_details(text):
    text = normalize_digits(text)  # normalize Arabic numerals
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
# TELEGRAM SETUP
# =============================
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'
output_file = 'matched_incidents.json'

async def qr_login(client):
    if not await client.is_user_authorized():
        print("Not authorized. Please scan the QR code to log in:")
        qr_login = await client.qr_login()
        qr_url = qr_login.url
        qr = qrcode.QRCode()
        qr.add_data(qr_url)
        qr.make()
        qr.print_ascii(invert=True)
        print("Scan this QR code from Telegram app: Settings > Devices > Link Desktop Device")
        await qr_login.wait()
        print("Logged in successfully!")
    else:
        print("Already authorized!")

async def get_my_channels(client):
    channels = []
    async for dialog in client.iter_dialogs():
        if isinstance(dialog.entity, Channel):
            channels.append(dialog.entity)
    return channels

# =============================
# MAIN FUNCTION
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

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        if not event.raw_text:
            return

        text_lower = event.raw_text.lower()
        if any(kw in text_lower for kw in keywords_set):
            incident_type = keywords.get_incident_type(text_lower)
            location = extract_location(event.raw_text)
            details = extract_important_details(event.raw_text)

            channel_name = event.chat.username if event.chat else str(event.chat_id)
            msg_id = event.id

            if (channel_name, msg_id) not in existing_ids:
                msg_data = {
                    'incident_type': incident_type,
                    'location': location if location else "Unknown / Outside Lebanon",
                    'channel': channel_name,
                    'message_id': msg_id,
                    'date': str(event.date),
                    'details': details
                }
                matched_messages.append(msg_data)
                existing_ids.add((channel_name, msg_id))

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(matched_messages, f, ensure_ascii=False, indent=2)

                print(f"[MATCH] {incident_type} @ {msg_data['location']} from {channel_name}")

    print("Started monitoring. Waiting for new messages...")

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
