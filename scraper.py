import asyncio
import json
import datetime
import os
import re
import sqlite3
import subprocess
from telethon import TelegramClient, events
from telethon.tl.types import Channel
import qrcode

# ----------------------------
# INCIDENT KEYWORDS
# ----------------------------
class IncidentKeywords:
    def __init__(self):
        self.incident_keywords = {
            'fire': {'ar': [...], 'en': [...]},
            'accident': {'ar': [...], 'en': [...]},
            'earthquake': {'ar': [...], 'en': [...]},
            'airstrike': {'ar': [...], 'en': [...]},
            'flood': {'ar': [...], 'en': [...]},
            'shooting': {'ar': [...], 'en': [...]},
            'explosion': {'ar': [...], 'en': [...]},
            'collapse': {'ar': [...], 'en': [...]},
            'pollution': {'ar': [...], 'en': [...]},
            'epidemic': {'ar': [...], 'en': [...]},
            'medical': {'ar': [...], 'en': [...]}
        }
        self.casualty_keywords = {
            'killed': {'ar': [...], 'en': [...]},
            'injured': {'ar': [...], 'en': [...]},
            'missing': {'ar': [...], 'en': [...]}
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

# ----------------------------
# DATABASE LOCATION
# ----------------------------
db_path = r"C:\Users\user\OneDrive - Lebanese University\Documents\GitHub\Incident_Project\lebanon_locations.db"

LEBANON_LOCATIONS = {}
ALL_LOCATIONS = set()

try:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""SELECT NAME_1, NAME_2, NAME_3 FROM locations WHERE NAME_0 = 'لبنان'""")
    temp = {}
    for name_1, name_2, name_3 in cur.fetchall():
        gov = (name_1 or "").strip()
        nb = (name_3 or "").strip()
        if not gov: continue
        if gov not in temp: temp[gov] = set()
        if nb: temp[gov].add(nb)
        ALL_LOCATIONS.update(filter(None, [gov, name_2, name_3]))
    for gov, nbs in temp.items():
        LEBANON_LOCATIONS[gov] = sorted(nbs)
finally:
    try: conn.close()
    except: pass

def extract_location(text):
    if not text or "غير محدد" in text or "undefined" in text.lower():
        return "Unknown / Outside Lebanon"
    for loc in ALL_LOCATIONS:
        if loc and loc in text:
            return loc
    return "Unknown / Outside Lebanon"

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
        "summary": text[:120] + "..." if len(text) > 120 else text
    }

# ----------------------------
# PHI3 ANALYSIS
# ----------------------------
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
    # Handle ```json ... ``` blocks first
    match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, flags=re.DOTALL)
    if match: return match.group(1).strip()
    match = re.search(r"\{.*?\}", response_text, flags=re.DOTALL)
    if match: return match.group().strip()
    return None

# ----------------------------
# TELEGRAM SETUP
# ----------------------------
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'
output_file = 'matched_incidents.json'

async def qr_login(client):
    if not await client.is_user_authorized():
        print("Scan the QR code:")
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

# ----------------------------
# MESSAGE PROCESSING
# ----------------------------
async def process_message(event, existing_ids):
    text = event.raw_text
    if not text: return
    ik = IncidentKeywords()
    keywords_set = ik.all_keywords()

    if any(kw in text.lower() for kw in keywords_set):
        channel_name = event.chat.username if event.chat else str(event.chat_id)
        msg_id = event.id
        if (channel_name, msg_id) in existing_ids: return

        # DB location first
        db_location = extract_location(text)
        details = extract_important_details(text)

        # Phi3 analysis
        phi3_resp = query_phi3(text)
        phi3_json_text = extract_json(phi3_resp)
        phi3_data = {}
        if phi3_json_text:
            try: phi3_data = json.loads(phi3_json_text)
            except: phi3_data = {}

        # Merge results: prefer DB location
        location = db_location if db_location != "Unknown / Outside Lebanon" else phi3_data.get("location", "Unknown / Outside Lebanon")
        incident_type = phi3_data.get("incident_type", ik.get_incident_type(text))
        threat_level = phi3_data.get("threat_level", "unknown")

        msg_data = {
            "incident_type": incident_type,
            "location": location,
            "channel": channel_name,
            "message_id": msg_id,
            "date": str(event.date),
            "threat_level": threat_level,
            "details": details
        }

        # Save
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                try: matched_messages = json.load(f)
                except: matched_messages = []
        else: matched_messages = []

        matched_messages.append(msg_data)
        existing_ids.add((channel_name, msg_id))
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(matched_messages, f, ensure_ascii=False, indent=2)

        print(f"[MATCH] {incident_type} @ {location} from {channel_name}")

# ----------------------------
# MAIN
# ----------------------------
async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.connect()
    await qr_login(client)
    channels = await get_my_channels(client)
    print(f"Monitoring {len(channels)} channels...")

    existing_ids = set()
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                existing_ids = {(msg.get('channel'), msg.get('message_id')) for msg in json.load(f)}
        except: existing_ids = set()

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        # Run processing asynchronously
        asyncio.create_task(process_message(event, existing_ids))

    print("Started monitoring...")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
