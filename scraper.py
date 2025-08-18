import asyncio
import json
import datetime
import os
import re
import qrcode
import sqlite3
import subprocess
import difflib
from telethon import TelegramClient, events
from telethon.tl.types import Channel

# =============================
# AI HELPER (Phi-3 via Ollama)
# =============================
def call_phi3(prompt: str) -> str:
    try:
        result = subprocess.run(
            ["ollama", "run", "phi3:mini"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=30
        )
        out = (result.stdout or b"").decode("utf-8", errors="ignore").strip()
        return out
    except Exception as e:
        return f"AI_Error: {e}"

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
# Arabic normalization helpers
# =============================
AR_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0617-\u061A\u06D6-\u06ED]")  # tashkeel
def normalize_ar(s: str) -> str:
    if not s:
        return ""
    s = AR_DIACRITICS_RE.sub("", s)
    s = s.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    s = s.replace("ى","ي").replace("ؤ","و").replace("ئ","ي").replace("ـ","")
    s = re.sub(r"[^\w\s\u0600-\u06FF]", " ", s)  # drop punctuation except Arabic letters/digits/underscore/space
    s = re.sub(r"\s+", " ", s).strip()
    return s

def ngrams(tokens, n):
    return [" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)]

# =============================
# LEBANON LOCATIONS from SQLite
# =============================
db_path = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.db"

LEB_ALL_ORIGINALS = set()   # all original strings (NAME_1/2/3)
LEB_NORM_TO_ORIG = {}       # normalized -> set(originals)

def add_location_string(s: str):
    s = (s or "").strip()
    if not s:
        return
    LEB_ALL_ORIGINALS.add(s)
    n = normalize_ar(s)
    if not n:
        return
    LEB_NORM_TO_ORIG.setdefault(n, set()).add(s)

try:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT NAME_1, NAME_2, NAME_3
        FROM locations
        WHERE NAME_0 = 'لبنان'
    """)
    for name_1, name_2, name_3 in cur.fetchall():
        add_location_string(name_1)
        add_location_string(name_2)
        add_location_string(name_3)
finally:
    try:
        conn.close()
    except:
        pass

LEB_NORM_KEYS = list(LEB_NORM_TO_ORIG.keys())  # for fuzzy matching

# =============================
# LOCATION EXTRACTION (DB exact -> DB fuzzy -> AI)
# =============================
def extract_location(text: str):
    if not text:
        return ("Unknown / Outside Lebanon", "none")

    # quick exact normalized substring search
    nt = normalize_ar(text)
    # exact scan
    for norm_loc, originals in LEB_NORM_TO_ORIG.items():
        if norm_loc and norm_loc in nt:
            return (next(iter(originals)), "db_exact")

    # fuzzy on uni/bi/tri-grams
    toks = nt.split()
    grams = toks + ngrams(toks, 2) + ngrams(toks, 3)

    # try longest grams first
    for g_len in (3, 2, 1):
        for g in (ngrams(toks, g_len) if g_len > 1 else toks):
            if not g:
                continue
            g_norm = g if g_len == 1 else g  # already normalized
            # exact containment on grams
            if g_norm in LEB_NORM_TO_ORIG:
                return (next(iter(LEB_NORM_TO_ORIG[g_norm])), "db_exact")

            # fuzzy closest
            best = difflib.get_close_matches(g_norm, LEB_NORM_KEYS, n=1, cutoff=0.90)
            if best:
                cand_norm = best[0]
                originals = LEB_NORM_TO_ORIG.get(cand_norm)
                if originals:
                    return (next(iter(originals)), "db_fuzzy")

    # AI fallback (restrict with a list to keep it grounded)
    ai_loc = ai_suggest_location(text)
    return (ai_loc, "ai")

def ai_suggest_location(text: str) -> str:
    # Give the model a (large) but bounded list to pick from
    loc_list = sorted(LEB_ALL_ORIGINALS)
    # If the list is huge, trim to first 1500 to keep prompt reasonable
    if len(loc_list) > 1500:
        loc_list = loc_list[:1500]

    prompt = f"""
أنت مساعد يقوم باستخراج المواقع داخل لبنان فقط.
النص:
{text}

قائمة بالمواقع اللبنانية المحتملة (محافظات/أقضية/بلدات/أحياء):
{", ".join(loc_list)}

التعليمات:
- إذا كان النص يشير إلى مكان داخل لبنان فأعد اسم المكان كما هو بالضبط من القائمة أعلاه (اختَر الأكثر تحديداً).
- إذا لم تجد مكاناً لبنانياً واضحاً فأعد: Unknown / Outside Lebanon
أجب باسم المكان فقط دون أي إضافة.
"""
    suggestion = call_phi3(prompt).strip()
    # sanitize a little
    if not suggestion or "unknown" in suggestion.lower():
        return "Unknown / Outside Lebanon"
    # if model returned something not in our list, keep it but mark it as AI-picked
    return suggestion

# =============================
# DETAILS EXTRACTION
# =============================
def extract_important_details(text):
    numbers = re.findall(r"\d+", text or "")
    casualties = []
    ik = IncidentKeywords()
    text_lower = (text or "").lower()
    for cat, langs in ik.casualty_keywords.items():
        for words in langs.values():
            if any(kw in text_lower for kw in words):
                casualties.append(cat)
    return {
        "numbers_found": numbers,
        "casualties": list(set(casualties)),
        "summary": text[:120] + "..." if text and len(text) > 120 else (text or "")
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
            loc_value, loc_source = extract_location(event.raw_text)
            details = extract_important_details(event.raw_text)

            # Prefer a readable channel name; fallback to ID
            channel_name = getattr(event.chat, "username", None) or getattr(event.chat, "title", None) or str(event.chat_id)
            msg_id = event.id

            if (channel_name, msg_id) not in existing_ids:
                msg_data = {
                    'incident_type': incident_type,
                    'location': loc_value,
                    'location_source': loc_source,   # db_exact | db_fuzzy | ai | none
                    'channel': channel_name,
                    'message_id': msg_id,
                    'date': str(event.date),
                    'details': details
                }
                matched_messages.append(msg_data)
                existing_ids.add((channel_name, msg_id))

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(matched_messages, f, ensure_ascii=False, indent=2)

                print(f"[MATCH] {incident_type} @ {loc_value} ({loc_source}) from {channel_name}")

    print("Started monitoring. Waiting for new messages...")

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
