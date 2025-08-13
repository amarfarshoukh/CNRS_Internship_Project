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
        return "unknown"

# =============================
# LEBANON LOCATIONS HIERARCHY (from DB)
# =============================
conn = sqlite3.connect(r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.db")
cursor = conn.cursor()
# Adjust table name if different
cursor.execute("SELECT NAME_0, NAME_1, NAME_2, NAME_3 FROM lebanon_locations") 
LEBANON_LOCATIONS = {}
for country, governorate, district, neighborhood in cursor.fetchall():
    if not governorate or not neighborhood:
        continue
    if governorate not in LEBANON_LOCATIONS:
        LEBANON_LOCATIONS[governorate] = []
    LEBANON_LOCATIONS[governorate].append(neighborhood)
conn.close()

# =============================
# LOCATION EXTRACTION
# =============================
def extract_location(text):
    if not text:
        return "غير محدد"
    text_lower = text.lower()
    for city, neighborhoods in LEBANON_LOCATIONS.items():
        if not city:
            continue
        for nb in neighborhoods:
            if nb and nb.lower() in text_lower:
                return f"{city}, {nb}"
        if city.lower() in text_lower:
            return city
    return "غير محدد"

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
                    'location': location,
                    'channel': channel_name,
                    'message_id': msg_id,
                    'date': str(event.date),
                    'details': details
                }
                matched_messages.append(msg_data)
                existing_ids.add((channel_name, msg_id))

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(matched_messages, f, ensure_ascii=False, indent=2)

                print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

    print("Started monitoring. Waiting for new messages...")

    try:
        while True:
            now = datetime.datetime.now()
            if now.hour == 0 and now.minute == 0:
                print("Midnight reached, stopping.")
                break
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
