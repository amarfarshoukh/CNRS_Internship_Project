import asyncio
import json
from telethon import TelegramClient, errors

class IncidentKeywords:
    def __init__(self):
        # أنواع الحوادث والكلمات المفتاحية
        self.incident_keywords = {
            'fire': {
                'ar': ['حريق', 'احتراق', 'نار', 'اشتعال', 'حرق', 'الدفاع المدني', 'إطفاء', 'حراق', 'نيران', 'حريق غابة', 'احتراق منزل', 'حريق مصنع', 'حريق سوق', 'حرائق الغابات', 'الدفاع المدني اللبناني', 'فرق الإطفاء'],
                'en': ['fire', 'burning', 'flames', 'burn', 'blaze', 'ignite', 'combustion', 'firefighter', 'wildfire', 'house fire', 'factory fire', 'market fire', 'forest fire', 'civil defense', 'fire brigade']
            },
            'accident': {
                'ar': ['حادث', 'حادث سير', 'حادث مرور', 'تصادم', 'انقلاب', 'اصطدام', 'سير', 'طريق', 'إسعاف', 'مرور', 'دهس', 'حادث دراجة نارية', 'حوادث قطار', 'حادث عمل', 'حادث شاحنة', 'حادث طيران'],
                'en': ['accident', 'car accident', 'traffic accident', 'crash', 'collision', 'wreck', 'road', 'vehicle', 'ambulance', 'hit and run', 'motorcycle accident', 'train accident', 'workplace accident', 'truck accident', 'aviation accident']
            },
            'earthquake': {
                'ar': ['زلزال', 'هزة', 'أرضية', 'زلازل', 'اهتزاز', 'تصدع', 'هزة أرضية', 'نشاط زلزالي'],
                'en': ['earthquake', 'seismic', 'tremor', 'quake', 'shake', 'magnitude', 'seismic activity']
            },
            'airstrike': {
                'ar': ['غارة جوية', 'قصف', 'طائرة', 'صاروخ', 'قنبلة', 'انفجار', 'عدوان', 'طيران حربي', 'هجوم جوي', 'قصف جوي'],
                'en': ['airstrike', 'bombing', 'missile', 'rocket', 'bomb', 'explosion', 'aircraft', 'raid', 'air attack']
            },
            'flood': {
                'ar': ['فيضان', 'سيول', 'أمطار', 'غرق', 'مياه', 'فيض', 'طوفان', 'فيضانات', 'ارتفاع منسوب المياه'],
                'en': ['flood', 'flooding', 'overflow', 'deluge', 'inundation', 'water', 'rain', 'high water level']
            },
            'shooting': {
                'ar': ['إطلاق نار', 'رصاص', 'إطلاق', 'مسلح', 'رمي', 'نار', 'هجوم مسلح', 'اشتباك مسلح'],
                'en': ['shooting', 'gunfire', 'shots', 'gunman', 'bullets', 'armed', 'armed attack', 'armed clash']
            },
            'explosion': {
                'ar': ['انفجار', 'تفجير', 'عبوة ناسفة', 'انفجار أنبوب غاز', 'انفجار سيارة مفخخة', 'تفجير انتحاري'],
                'en': ['explosion', 'detonation', 'blast', 'gas explosion', 'car bomb', 'suicide bombing', 'improvised explosive device']
            },
            'collapse': {
                'ar': ['انهيار', 'انهيار مبنى', 'انهيار جسر', 'انهيار أرضي', 'سقوط رافعة', 'انهيار سقف', 'انهيار منجم'],
                'en': ['collapse', 'building collapse', 'bridge collapse', 'landslide', 'crane collapse', 'roof collapse', 'mine collapse']
            },
            'pollution': {
                'ar': ['تلوث', 'تلوث مياه', 'تلوث هواء', 'تسرب نفطي', 'تسرب مواد كيميائية', 'انسكاب كيميائي'],
                'en': ['pollution', 'water contamination', 'air pollution', 'oil spill', 'chemical spill', 'hazardous leak']
            },
            'epidemic': {
                'ar': ['وباء', 'انتشار مرض', 'حجر صحي', 'إصابات جماعية', 'تفشي'],
                'en': ['epidemic', 'disease outbreak', 'quarantine', 'mass infection', 'pandemic', 'virus spread']
            },
            'medical': {
                'ar': ['الصليب الأحمر', 'إسعاف', 'إنعاش', 'إسعاف أولي', 'نجدة', 'مستشفى', 'طوارئ', 'إسعاف الدفاع المدني'],
                'en': ['red crescent', 'ambulance', 'resuscitation', 'first aid', 'emergency', 'hospital', 'paramedics', 'civil defense ambulance']
            }
        }

        # كلمات الإصابات والضحايا
        self.casualty_keywords = {
            'killed': {
                'ar': ['قتيل', 'قتلى', 'شهيد', 'شهداء', 'موت', 'وفاة', 'متوفى', 'مات', 'قضى', 'هلك', 'فارق الحياة'],
                'en': ['killed', 'dead', 'death', 'fatality', 'died', 'deceased', 'martyred', 'perished', 'passed away']
            },
            'injured': {
                'ar': ['جريح', 'جرحى', 'مصاب', 'مصابين', 'إصابة', 'جراح', 'كسر', 'رضوض', 'حروق', 'نقل للمستشفى', 'إسعاف'],
                'en': ['injured', 'wounded', 'hurt', 'casualty', 'victim', 'hospitalized', 'trauma', 'burns', 'fracture', 'bruises']
            },
            'missing': {
                'ar': ['مفقود', 'مفقودين', 'اختفى', 'اختفاء', 'ضائع'],
                'en': ['missing', 'lost', 'disappeared', 'gone']
            }
        }

    def all_keywords(self):
        # flatten all keywords (incident + casualty) into a single set (lowercase)
        kws = []
        for cat in self.incident_keywords.values():
            for lang_list in cat.values():
                kws.extend([kw.lower() for kw in lang_list])
        for cat in self.casualty_keywords.values():
            for lang_list in cat.values():
                kws.extend([kw.lower() for kw in lang_list])
        return set(kws)


# Replace with your actual API ID and hash
api_id = 20976159
api_hash = '41bca65c99c9f4fb21ed627cc8f19ad8'

channels_to_scrape = [
    'MTVLebanoNews',
    'MTVLebanonNews',
    'lebanondebate',
    'ALJADEED_NEWS',
    'lebanonnews2',
    'lebanonNewsNow',
    'LBCI_NEWS',
    'AljadeedNewsTV',
    'LebUpdate',
    'Aljadeedtelegram'
]

output_file = 'matched_incidents.json'


async def main():
    client = TelegramClient('session', api_id, api_hash)
    await client.start()
    print("Connected to Telegram!")

    keywords = IncidentKeywords()
    keywords_set = keywords.all_keywords()

    matched_messages = []

    for channel in channels_to_scrape:
        print(f"Fetching messages from {channel}...")
        try:
            async for message in client.iter_messages(channel, limit=100):
                if message.text:
                    text_lower = message.text.lower()
                    # Check if any keyword is in the message text
                    if any(keyword in text_lower for keyword in keywords_set):
                        matched_messages.append({
                            'channel': channel,
                            'message_id': message.id,
                            'date': str(message.date),
                            'text': message.text
                        })
        except errors.ChannelInvalidError:
            print(f"Channel {channel} is invalid or private.")
        except Exception as e:
            print(f"Error fetching from {channel}: {e}")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(matched_messages, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(matched_messages)} matched messages to {output_file}")

    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
