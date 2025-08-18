import asyncio
import json
import os
import re
import sqlite3
import subprocess
from telethon import TelegramClient, events
from telethon.tl.types import Channel

# =============================
# Incident Keywords (unchanged)
# =============================
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': ['حريق','احتراق','نار','اشتعال','حرق','الدفاع المدني','إطفاء','حراق','نيران','حريق غابة','احتراق منزل','حريق مصنع','حريق سوق','حرائق الغابات','الدفاع المدني اللبناني','فرق الإطفاء'],
                     'en': ['fire','burning','flames','burn','blaze','ignite','combustion','firefighter','wildfire','house fire','factory fire','market fire','forest fire','civil defense','fire brigade']},
            'accident': {'ar': ['حادثة','حادث','حادث سير','حادث مرور','تصادم','انقلاب','اصطدام','سير','طريق','إسعاف','مرور','دهس','حادث دراجة نارية','حوادث قطار','حادث عمل','حادث شاحنة','حادث طيران'],
                         'en': ['accident','car accident','traffic accident','crash','collision','wreck','road','vehicle','ambulance','hit and run','motorcycle accident','train accident','workplace accident','truck accident','aviation accident']},
            # Add other categories...
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
# Database setup
# =============================
DB_PATH = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

def db_match_location(text):
    """Search the database for exact Arabic location match."""
    cur.execute("SELECT NAME_3 FROM locations WHERE ? LIKE '%' || NAME_3 || '%'", (text,))
    result = cur.fetchone()
    if result and result[0]:
        return result[0]
    return None

# =============================
# Phi3 helper
# =============================
def query_phi3_for_location(message):
    prompt = f"""
    You are an assistant specialized in Lebanese locations.
    Task: Extract a Lebanese location from this message, or return 'Unknown / Outside Lebanon' if none exists.

    Message: "{message}"
    Respond ONLY with the location name in Arabic or 'Unknown / Outside Lebanon'.
    """
    result = subprocess.run(
        ["ollama", "run", "phi3:mini"],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return result.stdout.decode("utf-8").strip()

# =============================
# Location extraction
# =============================
def extract_location(text):
    db_loc = db_match_location(text)
    if db_loc:
        return db_loc
    # fallback to Phi3
    phi3_loc = query_phi3_for_location(text)
    if phi3_loc and "Unknown" not in phi3_loc:
        return phi3_loc
    return "Unknown / Outside Lebanon"

# =============================
# Threat level extraction
# =============================
def extract_threat_level(text):
    return "no" if "لا تهديد" in text else "yes"

# =============================
# Telegram / Main loop
# =============================
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'
output_file = "matched_incidents.json"

async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.start()
    print("Logged in!\nMonitoring channels...")

    keywords = IncidentKeywords()
    keywords_set = keywords.all_keywords()

    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            matched_messages = json.load(f)
    else:
        matched_messages = []

    existing_ids = {(msg.get('channel'), msg.get('message_id')) for msg in matched_messages}

    @client.on(events.NewMessage)
    async def handler(event):
        if not event.raw_text:
            return
        text = event.raw_text
        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id

        if (channel_name, msg_id) in existing_ids:
            return

        incident_type = keywords.get_incident_type(text)
        # If keyword search gives 'other', ask Phi3 for a better analysis
        if incident_type == "other":
            incident_type_prompt = f"""
            You are an incident analysis assistant.
            Message: "{text}"
            Respond with ONLY one of: accident, shooting, protest, fire, natural_disaster, other
            """
            result = subprocess.run(
                ["ollama", "run", "phi3:mini"],
                input=incident_type_prompt.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            res_text = result.stdout.decode("utf-8").strip()
            # Extract JSON-like value
            match = re.search(r"(accident|shooting|protest|fire|natural_disaster|other)", res_text)
            if match:
                incident_type = match.group(0)

        location = extract_location(text)
        threat_level = extract_threat_level(text)

        # extract minimal details (numbers/casualties/summary)
        numbers = re.findall(r"\d+", text)
        details = {
            "numbers_found": numbers,
            "casualties": [],
            "summary": text[:120] + "..." if len(text) > 120 else text
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

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(matched_messages, f, ensure_ascii=False, indent=4)

        print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
