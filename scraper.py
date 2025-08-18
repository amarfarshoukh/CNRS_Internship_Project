import asyncio
import json
import os
import re
import sqlite3
import subprocess
import difflib
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import qrcode

# =============================
# INCIDENT KEYWORDS
# =============================
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': ['حريق','احتراق','نار','اشتعال','حرق','الدفاع المدني','إطفاء','حراق','نيران','حريق غابة','احتراق منزل','حريق مصنع','حريق سوق','حرائق الغابات','الدفاع المدني اللبناني','فرق الإطفاء'],
                     'en': ['fire','burning','flames','burn','blaze','ignite','combustion','firefighter','wildfire','house fire','factory fire','market fire','forest fire','civil defense','fire brigade']},
            'accident': {'ar': ['حادثة','حادث','حادث سير','حادث مرور','تصادم','انقلاب','اصطدام','سير','طريق','إسعاف','مرور','دهس','حادث دراجة نارية','حوادث قطار','حادث عمل','حادث شاحنة','حادث طيران'],
                         'en': ['accident','car accident','traffic accident','crash','collision','wreck','road','vehicle','ambulance','hit and run','motorcycle accident','train accident','workplace accident','truck accident','aviation accident']},
            'shooting': {'ar': ['إطلاق نار','رصاص','إطلاق','مسلح','رمي','نار','هجوم مسلح','اشتباك مسلح'],
                         'en': ['shooting','gunfire','shots','gunman','bullets','armed','armed attack','armed clash']},
            'protest': {'ar': ['احتجاج','تظاهرة','مظاهرة','اعتصام','اعتصامات'],
                        'en': ['protest','demonstration','riot','strike','march','rally']},
            'natural_disaster': {'ar': ['زلزال','هزة','أرضية','زلازل','اهتزاز','تصدع','هزة أرضية','نشاط زلزالي','فيضان','سيول','أمطار','غرق','مياه','فيض','طوفان','فيضانات','ارتفاع منسوب المياه'],
                                 'en': ['earthquake','seismic','tremor','quake','shake','magnitude','seismic activity','flood','flooding','overflow','deluge','inundation','water','rain','high water level']},
        }

        self.casualty_keywords = {
            'killed': {'ar': ['قتيل','قتلى','شهيد','شهداء','موت','وفاة','متوفى','مات','قضى','هلك','فارق الحياة'],
                       'en': ['killed','dead','death','fatality','died','deceased','martyred','perished','passed away']},
            'injured': {'ar': ['جريح','جرحى','مصاب','مصابين','إصابة','جراح','كسر','رضوض','حروق','نقل للمستشفى','إسعاف'],
                        'en': ['injured','wounded','hurt','casualty','victim','hospitalized','trauma','burns','fracture','bruises']},
            'missing': {'ar': ['مفقود','مفقودين','اختفى','اختفاء','ضائع'],
                        'en': ['missing','lost','disappeared','gone']}
        }

    def all_keywords(self):
        kws = []
        for cat in self.incident_keywords.values():
            for lang_list in cat.values():
                if lang_list is not Ellipsis:  # fix previous error
                    kws.extend([kw.lower() for kw in lang_list])
        for cat in self.casualty_keywords.values():
            for lang_list in cat.values():
                if lang_list is not Ellipsis:
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
# LEBANON LOCATIONS FROM DATABASE
# =============================
db_path = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.db"
LEBANON_LOCATIONS = {}   # { governorate: [neighborhoods] }
ALL_LOCATIONS = set()    # flat list of all Lebanese places

try:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT NAME_1, NAME_2, NAME_3 FROM locations WHERE NAME_0 = 'لبنان'")
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
        ALL_LOCATIONS.add(gov)
        if name_2:
            ALL_LOCATIONS.add(name_2.strip())
        if name_3:
            ALL_LOCATIONS.add(name_3.strip())
    for gov, nbs in temp.items():
        LEBANON_LOCATIONS[gov] = sorted(nbs)
finally:
    try:
        conn.close()
    except:
        pass


# =============================
# PHI3 HELPER
# =============================
def query_phi3(message):
    prompt = f"""
    You are an incident analysis assistant.
    Analyze the following message and return ONLY valid JSON.

    Message: "{message}"

    Output JSON format:
    {{
        "location": "Extracted location or 'Unknown / Outside Lebanon'",
        "incident_type": "Choose one of: accident, shooting, protest, fire, natural_disaster, other",
        "threat_level": "yes or no"
    }}

    Important:
    - If the message contains 'لا تهديد', threat_level must be 'no'.
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
# LOCATION EXTRACTION WITH PHI3 FALLBACK
# =============================
def extract_location(text):
    for loc in ALL_LOCATIONS:
        if loc in text:
            return loc
    # fallback to Phi3
    try:
        response = query_phi3(text)
        json_text = extract_json(response)
        if json_text:
            data = json.loads(json_text)
            if data.get("location"):
                return data["location"]
    except Exception:
        pass
    return "Unknown / Outside Lebanon"


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
# MAIN SCRAPER LOOP
# =============================
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)

    ik = IncidentKeywords()
    keywords_set = ik.all_keywords()
    channels = await get_my_channels(client)
    print(f"Monitoring {len(channels)} channels...")
    print("Started monitoring...")

    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                matched_messages = json.load(f)
        except:
            matched_messages = []
    else:
        matched_messages = []

    existing_ids = {(msg.get('channel'), msg.get('message_id')) for msg in matched_messages}

    async def process_message(event):
        if not event.raw_text:
            return

        text_lower = event.raw_text.lower()
        incident_type = ik.get_incident_type(text_lower)
        location = extract_location(event.raw_text)

        # Fallback to Phi3 if incident_type is "other"
        if incident_type == "other":
            try:
                response = query_phi3(event.raw_text)
                json_text = extract_json(response)
                if json_text:
                    data = json.loads(json_text)
                    incident_type = data.get("incident_type", "other")
            except Exception:
                pass

        threat_level = "no" if "لا تهديد" in event.raw_text else "yes"

        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id

        if (channel_name, msg_id) not in existing_ids:
            details = {
                "numbers_found": re.findall(r"\d+", event.raw_text),
                "casualties": [],
                "summary": event.raw_text[:120] + "..." if len(event.raw_text) > 120 else event.raw_text
            }
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
                json.dump(matched_messages, f, ensure_ascii=False, indent=2)

            print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

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
