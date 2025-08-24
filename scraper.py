import asyncio
import json
import os
import re
import subprocess
import ast
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import qrcode

# -----------------------------
# CONFIG
# -----------------------------
GEOJSON_FOLDER = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\geojson_output"
OUTPUT_FILE = "matched_incidents.json"
OLLAMA_MODEL = "phi3:mini"
MAX_NUMBER_LEN = 6
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'
PHI3_TIMEOUT = 60

LOCATION_KEYWORDS = [
    "في", "في منطقة", "في حي", "في بلدة", "بالقرب من", "عند", "جنوب", "شمال", "شرق", "غرب"
]

# -----------------------------
# Arabic normalization
# -----------------------------
RE_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u06D6-\u06ED]+")

def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = RE_DIACRITICS.sub("", text)
    text = text.replace('\u0640', '')
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ؤ]", "و", text)
    text = re.sub(r"[ئ]", "ي", text)
    text = text.replace('ة', 'ه')
    text = re.sub(r"[يى]", "ي", text)
    return re.sub(r"\s+", " ", text).strip()

def is_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text))

# -----------------------------
# Load GeoJSON locations
# -----------------------------
def extract_centroid(coords):
    if not coords:
        return None
    if isinstance(coords[0], list):
        points = coords[0] if isinstance(coords[0][0], list) else coords
    else:
        points = [coords]
    lon = sum([p[0] for p in points]) / len(points)
    lat = sum([p[1] for p in points]) / len(points)
    return [lon, lat]

def load_geojson_file(file_path):
    if not os.path.exists(file_path):
        return {}
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    features = data.get('features', data) if isinstance(data, dict) else data
    norm_map = {}
    for item in features:
        props = item.get('properties', item) if isinstance(item, dict) else item
        name = props.get('name') or item.get('name')
        coords = item.get('geometry', {}).get('coordinates') if 'geometry' in item else item.get('coordinates')
        if name and coords and is_arabic(name):
            try:
                centroid = extract_centroid(coords)
            except Exception:
                centroid = None
            norm_map[normalize_arabic(name)] = {"original": name, "coordinates": centroid}
    return norm_map

def load_all_geojson_folder(folder_path):
    all_map = {}
    for file in os.listdir(folder_path):
        if file.lower().endswith('.json'):
            file_path = os.path.join(folder_path, file)
            locations = load_geojson_file(file_path)
            all_map.update(locations)
    return all_map

ALL_LOCATIONS = load_all_geojson_folder(GEOJSON_FOLDER)
print(f"Loaded {len(ALL_LOCATIONS)} Arabic locations from GeoJSON folder")

# -----------------------------
# Location detection
# -----------------------------
def detect_location_from_map(text_norm):
    words = text_norm.split()
    for loc_norm, loc_data in ALL_LOCATIONS.items():
        loc_words = loc_norm.split()
        for i in range(len(words) - len(loc_words) + 1):
            if words[i:i+len(loc_words)] == loc_words:
                return loc_data["original"], loc_data["coordinates"]
    return None, None

def detect_location(text):
    text_norm = normalize_arabic(text)
    for kw in LOCATION_KEYWORDS:
        if kw in text_norm:
            loc, coords = detect_location_from_map(text_norm)
            if loc:
                return loc, coords
    return detect_location_from_map(text_norm)

# -----------------------------
# Incident keywords
# -----------------------------
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'vehicle_accident': ['حادث سير', 'حوادث سير', 'تصادم', 'تصادم سيارات', 'تصادم مركبات', 'دهس', 'حالة دهس', 'حوادث دهس', 'انقلاب', 'انقلاب سيارة', 'انقلاب مركبة', 'اصطدام', 'اصطدام سيارات', 'اصطدام مركبات', 'حادث مروري', 'حوادث مرورية', 'حادث طرق', 'حوادث طرق', 'حادث مرور', 'حوادث مرور', 'تصادم مروري', 'حادث باص', 'حادث شاحنة', 'حادث دراجة', 'حادث دراجة نارية'],
            'shooting': ['إطلاق نار', 'إطلاق الرصاص', 'رصاص', 'رصاصة', 'مسلح', 'مسلحين', 'هجوم مسلح', 'هجمات مسلحة', 'اشتباك', 'اشتباكات', 'إطلاق أعيرة نارية', 'إطلاق نار كثيف', 'إطلاق نار عشوائي', 'إطلاق نار مباشر', 'إطلاق نار متبادل', 'إطلاق نار في الهواء', 'إطلاق نار على تجمع', 'إطلاق نار على سيارة', 'إطلاق نار على منزل', 'إطلاق نار على دورية', 'إطلاق نار على حاجز'],
            'protest': ['احتجاج', 'احتجاجات', 'مظاهرة', 'مظاهرات', 'تظاهرة', 'تظاهرات', 'اعتصام', 'اعتصامات', 'مسيرة احتجاجية', 'مسيرات احتجاجية', 'مسيرة', 'مسيرات', 'تجمع احتجاجي', 'تجمعات احتجاجية', 'وقف احتجاجي', 'وقفات احتجاجية', 'إضراب', 'إضرابات', 'تجمهر'],
            'fire': ['حريق', 'احتراق', 'نار', 'اشتعال', 'اندلاع', 'اندلاع حريق', 'دخان', 'دخان كثيف', 'تصاعد دخان', 'لهب', 'ألسنة اللهب', 'حريق كبير', 'حريق ضخم', 'حريق هائل', 'حريق مبنى', 'حريق منزل', 'حريق غابة', 'اشتعال النيران', 'اندلاع النيران', 'اندلاع نار'],
            'earthquake': ['زلزال','زلازل','هزة','هزات','هزة أرضية','هزات أرضية','رجفة','رجفات','رجفة أرضية','رجفات أرضية','اهتزاز','اهتزازات','ارتجاج','ارتجاجات','ارتعاش أرضي','ارتجاف الأرض','انشقاق الأرض','تشقق الأرض','صدع أرضي','شروخ أرضية'],
            'flood': ['فيضان','فيضانات','طوفان','طوفانات','تسونامي','سيول','سيل','السيول','سيول جارفة','فيضانات جارفة','غمر مائي','تدفق مائي','ارتفاع منسوب المياه','غرق الشوارع','غرق الطرقات','غرق المنازل','انفجار سد','انهيار سد','أمطار غزيرة','غزارة الأمطار','تراكم مياه','تجميع مياه','برك مياه','بحيرات مؤقتة','غمر الأراضي الزراعية','كارثة مائية'],
            'tree_down': ['انهيار','انهيارات','انهيار أرضي','انهيارات أرضية','سقوط صخور','انزلاق صخور','انزلاق تربة','انزلاقات تربة','انهيار جبلي','انهيارات جبلية','سقوط شجر','سقوط أشجار','اقتلاع شجرة','اقتلاع أشجار','اقتلاع جذور','عاصفة','عواصف','عاصفة رعدية','عواصف رعدية','عاصفة ثلجية','عواصف ثلجية','عاصفة مطرية','عواصف مطرية','عاصفة هوائية','عواصف هوائية','عاصفة ترابية','عواصف ترابية','رياح قوية','عواصف رملية','إعصار','أعاصير','إعصار مدمر','إعصار قوي','عاصفة مدارية','حرائق غابات','حريق غابة','جفاف','موجة جفاف','تساقط الصخور','انحدار صخري','موجة عاتية','موجة رياح','عاصفة قوية','عاصفة مدمرة'],
            'airstrike': ['مسيرة', 'طيران', 'حربي', 'طيران حربي', 'غارة', 'غارة جوية', 'قصف', 'قصف جوي', 'قصف صاروخي', 'قصف مدفعي', 'صاروخ', 'صواريخ', 'قنبلة', 'قنابل', 'طائرة', 'طائرات', 'مقاتلة', 'مقاتلات', 'قصف بالطائرات', 'ضربة جوية', 'هجوم جوي', 'تفجير جوي', 'غارة جوية إسرائيلية', 'غارة إسرائيلية', 'سلاح الجو', 'ضربة صاروخية', 'هجوم صاروخي', 'قذيفة', 'قذائف'],
            'collapse': ['انهيار', 'انهيار مبنى', 'انهيارات', 'سقوط', 'سقوط مبنى', 'سقوط مبانٍ', 'سقوط جدار', 'سقوط سقف', 'انهيار سقف', 'انهيار جدار', 'انهيار منزل', 'انهيار عمارة', 'انهيار بناء', 'انهيار طريق', 'انهيار جسر', 'انهيار أرضي', 'هبوط أرضي', 'تصدع', 'تصدعات'],
            'pollution': ['اعتداء', 'بيئي', 'اعتداء بيئي', 'تلوث', 'تعدي', 'تعدي على البيئة', 'تسريب', 'نفطي', 'تسريب نفطي', 'تلوث المياه', 'تلوث الهواء', 'تلوث نفايات', 'مكب', 'مكب عشوائي', 'مياه ملوثة', 'صرف صحي', 'مجارير', 'دخان', 'دخان سام', 'نفايات', 'تسرب مواد كيميائية', 'تسريب مواد سامة', 'تلوث صناعي', 'تلوث زراعي', 'مياه آسنة', 'صرف صناعي', 'تسرب نفط', 'تسرب وقود', 'تسرب غاز'],
            'epidemic': ['وباء', 'تفشي', 'تفشي وباء', 'انتشار وباء', 'تفشي مرض', 'مرض معد', 'أمراض معدية', 'إصابة جماعية', 'إصابات جماعية', 'عدوى', 'انتشار عدوى', 'حالات عدوى', 'حجر صحي', 'حالة وبائية', 'حالات وبائية', 'حالة طوارئ صحية', 'حجر صحي جماعي', 'انتشار مرض'],
            'medical': ['إسعاف', 'اسعاف', 'مستشفى', 'مستشفيات', 'طوارئ', 'قسم الطوارئ', 'إنعاش', 'انعاش', 'سيارة إسعاف', 'سيارات إسعاف', 'خدمة طبية', 'خدمات طبية', 'إصابة طبية', 'إصابات طبية', 'فريق طبي', 'طبيب', 'أطباء', 'ممرض', 'ممرضة', 'طاقم طبي', 'علاج', 'رعاية طبية', 'حالة صحية', 'حالات حرجة', 'مصاب', 'مصابين', 'نقل طبي', 'إخلاء طبي', 'إسعافات أولية'],
            'explosion': ['انفجار', 'تفجير', 'عبوة', 'ناسفة', 'عبوة ناسفة', 'انفجارات', 'تفجيرات', 'قنبلة', 'قنابل', 'انفجار قوي', 'انفجار عنيف', 'انفجار عبوة', 'انفجار سيارة مفخخة', 'سيارة مفخخة', 'انفجار ذخيرة', 'انفجار لغم', 'انفجار غامض', 'دوي انفجار', 'دوي قوي', 'انفجار صوتي', 'انفجار منزل', 'انفجار مبنى'],
        }
        self.casualty_keywords = {
            'killed': ['قتيل', 'قتلى', 'شهداء', 'شهيد', 'وفاة', 'وفيات', 'مقتل', 'مقتل شخص', 'مقتل أشخاص', 'مقتل مدني', 'مقتل مدنيين', 'مقتل طفل', 'مقتل أطفال', 'مقتل امرأة', 'مقتل نساء', 'قتل', 'قتلى الحادث', 'سقوط قتلى', 'سقوط ضحايا', 'ضحايا', 'ضحايا القتل'],
            'injured': ['جريح', 'جرحى', 'مصاب', 'مصابون', 'مصابين', 'إصابة', 'إصابات', 'إصابات حرجة', 'إصابات بالغة', 'إصابات طفيفة', 'إصابة شخص', 'إصابة أشخاص', 'إصابة مدني', 'إصابة مدنيين', 'إصابة طفل', 'إصابة أطفال', 'إصابة امرأة', 'إصابة نساء'],
            'missing': ['مفقود', 'مفقودين', 'مفقودة', 'مفقودات', 'اختفى', 'اختفاء', 'فقدان', 'حالة فقدان', 'بلاغ فقدان', 'مفقود الشخص', 'مفقودة الشخص']
        }

    def extract_casualties(self, text):
        tl = text.lower()
        cats = []
        for cat, kws in self.casualty_keywords.items():
            for kw in kws:
                if kw in tl:
                    cats.append(cat)
        return list(set(cats))

    def extract_numbers(self, text):
        nums = re.findall(r"[0-9]+|[٠-٩]+", text)
        conv = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        cleaned = [n.translate(conv) for n in nums if len(n.translate(conv)) <= MAX_NUMBER_LEN]
        return cleaned

IK = IncidentKeywords()

# -----------------------------
# Incident detection helper (multi)
# -----------------------------
def find_incident_types(text, incident_keywords):
    norm_text = normalize_arabic(text)
    found = []
    for inc_type, keywords in incident_keywords.items():
        if any(kw in norm_text for kw in keywords):
            found.append(inc_type)
    return list(set(found))

# -----------------------------
# Robust Phi3 JSON Extractor
# -----------------------------
def robust_json_extract(text):
    text = re.sub(r'```json|```', '', text).strip()
    text = re.sub(r'^"{3,}', '', text).strip()
    text = re.sub(r'"{3,}$', '', text).strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        print("Could not find JSON object in:", text)
        return None
    json_str = text[start:end+1]
    json_str = re.sub(r'//.*', '', json_str)
    json_str = re.sub(r',(?![^{}]*\})[^\n]*', ',', json_str)
    json_str = '\n'.join([line for line in json_str.splitlines() if ':' in line or '}' in line or '{' in line])
    try:
        data = json.loads(json_str)
        if "threat_level" in data and data["threat_level"] not in ["yes", "no"]:
            data["threat_level"] = "yes"
        return data
    except Exception:
        print("Phi3 returned invalid JSON after cleanup:", json_str)
        return None

# -----------------------------
# Phi3 JSON query
# -----------------------------
def query_phi3_json(message: str):
    prompt = f"""
You are an incident analysis assistant.
Return ONLY valid JSON. Do NOT include any explanations.
{{"location": ..., "incident_type": ..., "threat_level": ..., "casualties": [...], "numbers": [...]}}

Message: "{message}"
"""

    try:
        res = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PHI3_TIMEOUT
        )
        text = res.stdout.decode("utf-8", errors="ignore").strip()
        return robust_json_extract(text)
    except Exception as e:
        print("Phi3 call failed:", e)
        return None

# -----------------------------
# Load/save matches
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
# Deduplication
# -----------------------------
def select_best_message(records):
    records.sort(key=lambda m: (
        len(m['details'].get('numbers_found', [])) +
        len(m['details'].get('casualties', [])) +
        len(m['details'].get('summary', ''))
    ), reverse=True)
    return records[0]

# -----------------------------
# Phi3 worker queue (multi-incident)
# -----------------------------
message_queue = asyncio.Queue()

async def phi3_worker(matches, existing_ids):
    while True:
        event = await message_queue.get()
        try:
            text = event.raw_text or ""
            channel_name = event.chat.username if event.chat and getattr(event.chat, 'username', None) else str(event.chat_id)
            msg_id = event.id

            if (channel_name, msg_id) in existing_ids:
                continue  # no task_done here, finally will handle it

            # --- Location detection
            has_kw = any(kw in normalize_arabic(text) for kw in LOCATION_KEYWORDS)
            location, coordinates = detect_location(text) if has_kw else (None, None)
            if not location or not coordinates:
                continue

            # --- Incident type detection
            incident_types = find_incident_types(text, IK.incident_keywords)

            if not incident_types:
                # fallback to Phi3
                phi3_res = query_phi3_json(text)
                if not phi3_res:
                    continue  # skip non-incident

                raw_type = str(phi3_res.get("incident_type", "")).lower().strip()
                allowed_types = set(IK.incident_keywords.keys())

                if raw_type in allowed_types:
                    incident_types = [raw_type]
                elif raw_type:  
                    # if Phi3 says it's an incident but not in our list → classify as "other"
                    incident_types = ["other"]
                else:
                    continue  # not an incident → skip

            # Ensure always a list
            if isinstance(incident_types, str):
                incident_types = [incident_types]

            # --- Only allow incident_types that are in our schema or "other"
            incident_types = [itype for itype in incident_types if itype in IK.incident_keywords or itype == "other"]

            if not incident_types:
                continue

            # --- Common fields
            numbers = IK.extract_numbers(text)
            casualties = IK.extract_casualties(text)
            summary = text[:300] + ("..." if len(text) > 300 else "")

            for incident_type in incident_types:
                record = {
                    "incident_type": incident_type,
                    "location": location,
                    "coordinates": coordinates,
                    "channel": channel_name,
                    "message_id": msg_id,
                    "date": str(event.date),
                    "threat_level": "yes",  # default, or override with Phi3 if available
                    "details": {
                        "numbers_found": numbers,
                        "casualties": casualties,
                        "summary": summary
                    }
                }

                # --- Deduplicate (same type/location/day)
                date_prefix = record["date"][:10]
                similar_records = [
                    m for m in matches
                    if m.get('incident_type') == record['incident_type']
                    and m.get('location') == record['location']
                    and m.get('date', '')[:10] == date_prefix
                ]

                if similar_records:
                    similar_records.append(record)
                    best_record = select_best_message(similar_records)
                    matches[:] = [
                        m for m in matches if not (
                            m.get('incident_type') == record['incident_type']
                            and m.get('location') == record['location']
                            and m.get('date', '')[:10] == date_prefix
                        )
                    ]
                    matches.append(best_record)
                else:
                    matches.append(record)

                print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

            existing_ids.add((channel_name, msg_id))
            save_matches(matches)

        finally:
            message_queue.task_done()  # only here!


# -----------------------------
# Telegram login
# -----------------------------
async def qr_login(client):
    if not await client.is_user_authorized():
        print("Scan QR code:")
        qr_login_obj = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login_obj.url)
        qr.make()
        qr.print_ascii(invert=True)
        await qr_login_obj.wait()

async def get_my_channels(client):
    out = []
    async for d in client.iter_dialogs():
        if isinstance(d.entity, Channel):
            out.append(d.entity)
    return out

# -----------------------------
# Main async
# -----------------------------
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.start()
    await qr_login(client)
    channels = await get_my_channels(client)
    channel_ids = [c.id for c in channels]
    print(f"Monitoring {len(channel_ids)} channels...")

    matches = load_existing_matches()
    existing_ids = {(m.get('channel'), m.get('message_id')) for m in matches}

    asyncio.create_task(phi3_worker(matches, existing_ids))

    @client.on(events.NewMessage(chats=channel_ids))
    async def handler(event):
        await message_queue.put(event)

    print("Started monitoring. Waiting for new messages...")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
