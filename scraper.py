import asyncio
import json
import datetime
import os
import re
import qrcode
import sqlite3
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import subprocess

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
            'earthquake': {'ar': ['زلزال','هزة','أرضية','زلازل','اهتزاز','تصدع','هزة أرضية','نشاط زلزالي'],
                           'en': ['earthquake','seismic','tremor','quake','shake','magnitude','seismic activity']},
            'airstrike': {'ar': ['غارة جوية','قصف','طائرة','صاروخ','قنبلة','انفجار','عدوان','طيران حربي','هجوم جوي','قصف جوي'],
                          'en': ['airstrike','bombing','missile','rocket','bomb','explosion','aircraft','raid','air attack']},
            'flood': {'ar': ['فيضان','سيول','أمطار','غرق','مياه','فيض','طوفان','فيضانات','ارتفاع منسوب المياه'],
                      'en': ['flood','flooding','overflow','deluge','inundation','water','rain','high water level']},
            'shooting': {'ar': ['إطلاق نار','رصاص','إطلاق','مسلح','رمي','نار','هجوم مسلح','اشتباك مسلح'],
                         'en': ['shooting','gunfire','shots','gunman','bullets','armed','armed attack','armed clash']},
            'explosion': {'ar': ['انفجار','تفجير','عبوة ناسفة','انفجار أنبوب غاز','انفجار سيارة مفخخة','تفجير انتحاري'],
                          'en': ['explosion','detonation','blast','gas explosion','car bomb','suicide bombing','improvised explosive device']},
            'collapse': {'ar': ['انهيار','انهيار مبنى','انهيار جسر','انهيار أرضي','سقوط رافعة','انهيار سقف','انهيار منجم'],
                         'en': ['collapse','building collapse','bridge collapse','landslide','crane collapse','roof collapse','mine collapse']},
            'pollution': {'ar': ['تلوث','تلوث مياه','تلوث هواء','تسرب نفطي','تسرب مواد كيميائية','انسكاب كيميائي'],
                          'en': ['pollution','water contamination','air pollution','oil spill','chemical spill','hazardous leak']},
            'epidemic': {'ar': ['وباء','انتشار مرض','حجر صحي','إصابات جماعية','تفشي'],
                         'en': ['epidemic','disease outbreak','quarantine','mass infection','pandemic','virus spread']},
            'medical': {'ar': ['الصليب الأحمر','إسعاف','إنعاش','إسعاف أولي','نجدة','مستشفى','طوارئ','إسعاف الدفاع المدني'],
                        'en': ['red crescent','ambulance','resuscitation','first aid','emergency','hospital','paramedics','civil defense ambulance']}
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
# LOCATION DATABASE
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
        nb = (name_3 or "").strip()
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
# LOCATION & DETAILS EXTRACTION
# =============================
def extract_location(text):
    if not text or "غير محدد" in text or "undefined" in text.lower():
        return "Unknown / Outside Lebanon"
    for loc in ALL_LOCATIONS:
        if loc and loc in text:
            return loc
    return "Unknown / Outside Lebanon"

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
# PHI3 INCIDENT TYPE ANALYSIS
# =============================
def query_phi3_incident_type(message):
    prompt = f"""
    You are an incident analysis assistant.
    Task: Analyze the following incident report and return ONLY the incident type.

    Message: "{message}"

    Output JSON format:
    {{
        "incident_type": "Choose one of: accident, shooting, protest, fire, natural_disaster, other"
    }}

    Important:
    - Respond with JSON only, no explanations.
    """
    result = subprocess.run(
        ["ollama", "run", "phi3:mini"],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    text = result.stdout.decode("utf-8").strip()
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get("incident_type", "other")
        except json.JSONDecodeError:
            return "other"
    return "other"


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
    print("Started monitoring...")

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
        if not event.raw_text:
            return

        text_lower = event.raw_text.lower()
        if any(kw in text_lower for kw in keywords_set):
            location = extract_location(event.raw_text)
            details = extract_important_details(event.raw_text)
            threat_level = "no" if "لا تهديد" in event.raw_text else "yes"
            incident_type = keywords.get_incident_type(event.raw_text)

            # If keywords return 'other', use Phi3 to classify
            if incident_type == "other":
                incident_type = query_phi3_incident_type(event.raw_text)

            channel_name = event.chat.username if event.chat else str(event.chat_id)
            msg_id = event.id

            if (channel_name, msg_id) not in existing_ids:
                msg_data = {
                    'incident_type': incident_type,
                    'location': location,
                    'channel': channel_name,
                    'message_id': msg_id,
                    'date': str(event.date),
                    'threat_level': threat_level,
                    'details': details
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
