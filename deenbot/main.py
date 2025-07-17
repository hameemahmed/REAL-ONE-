import os
import random
import schedule
import time
from datetime import datetime, timedelta
import requests
import threading
import sqlite3
from pytz import timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURATION ==========
CONFIG = {
    "TELEGRAM_BOT_TOKEN": "7887687989:AAGcNEE8Cb_tW81DxlxzBroqDvA3HpDNELM",
    "TELEGRAM_CHAT_ID": "7130589902",
    "PRAYER_TIMES_API": "http://api.aladhan.com/v1/timingsByAddress",
    "QURAN_API": "https://api.alquran.cloud/v1/",
    "LOCATION": {
        "address": "Hodge Hill, Birmingham, UK",
        "method": 2,  # ISNA
        "school": 1,  # Shafi for Asr time
        "timezone": "Europe/London"
    },
    "SCHEDULE": {
        "daily_verses_time": "08:00",  # Send 10 verses daily at this time
        "stories_time": "18:00",       # Send 2 stories daily at this time
        "random_verses_per_day": 10    # Number of daily verses to send
    }
}

DB_FILE = "quran_bot.db"

# ======== DATABASE & INITIALIZATION ========

def init_database():
    """Initialize SQLite database with verses, stories, and users tables"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verses (
                id INTEGER PRIMARY KEY,
                surah_number INTEGER,
                surah_name TEXT,
                ayah_number INTEGER,
                arabic_text TEXT,
                translation TEXT,
                last_sent DATE DEFAULT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY,
                title TEXT,
                content TEXT,
                source TEXT,
                last_sent DATE DEFAULT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_active INTEGER DEFAULT 1,
                registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()

def safe_api_request(url, params=None, max_retries=3):
    """Make API requests with retry"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data.get('data'):
                raise ValueError("Missing data in API response")
            return data
        except Exception as e:
            print(f"API request attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return None

def populate_quran_data():
    """Load Quran verses into the DB if not already loaded"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM verses")
        count = cursor.fetchone()[0]
        if count > 0:
            print("Quran verses already loaded.")
            return

        print("Loading Quran verses from API, please wait...")

        surahs_data = safe_api_request(f"{CONFIG['QURAN_API']}surah")
        if not surahs_data:
            print("Failed to load surah list.")
            return

        surahs = surahs_data['data']

        for surah in surahs:
            surah_number = surah['number']
            surah_name = surah['englishName']

            # Get Arabic text
            arabic_data = safe_api_request(f"{CONFIG['QURAN_API']}surah/{surah_number}")
            if not arabic_data:
                print(f"Failed to load Arabic verses for Surah {surah_number}")
                continue

            # Get English translation
            english_data = safe_api_request(f"{CONFIG['QURAN_API']}surah/{surah_number}/en.sahih")
            if not english_data:
                print(f"Failed to load English translation for Surah {surah_number}")
                continue

            arabic_verses = arabic_data['data']['ayahs']
            english_verses = english_data['data']['ayahs']

            # Combine Arabic and English verses
            for i, arabic_verse in enumerate(arabic_verses):
                english_text = 'Translation not available'
                if i < len(english_verses) and english_verses[i].get('text'):
                    english_text = english_verses[i]['text'].strip()
                    # Ensure we have actual translation text
                    if not english_text or english_text.lower() in ['', 'null', 'none']:
                        english_text = 'Translation not available'

                cursor.execute("""
                    INSERT INTO verses (surah_number, surah_name, ayah_number, arabic_text, translation)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    surah_number,
                    surah_name,
                    arabic_verse['numberInSurah'],
                    arabic_verse['text'],
                    english_text
                ))
            print(f"Loaded Surah {surah_number} - {surah_name}")

            # To avoid hitting API limits
            time.sleep(1)

        conn.commit()
        print("✅ Quran verses loaded successfully.")
    except Exception as e:
        print(f"Error loading Quran: {e}")
    finally:
        if conn:
            conn.close()

# ======== PROPHET STORIES DATA ========
PROPHET_STORIES = [
    {
        "title": "Prophet Adam (AS) and His Creation",
        "content": "Allah created Prophet Adam (AS) from clay and breathed His spirit into him. When Allah completed Adam's creation, He commanded the angels to prostrate to Adam. All angels obeyed except Iblis (Satan), who refused out of arrogance, saying 'I am better than him. You created me from fire and created him from clay.' This was the first act of disobedience and pride that led to Iblis becoming Satan.",
        "source": "Quran 2:30-34, Sahih Bukhari"
    },
    {
        "title": "Prophet Adam (AS) and Hawwa (Eve) in Paradise",
        "content": "Allah placed Adam and Hawwa in Paradise and told them they could eat from all trees except one. Satan whispered to them, making the forbidden tree seem attractive. When they ate from it, they realized their mistake and felt ashamed. Allah taught Adam words of repentance: 'Our Lord, we have wronged ourselves, and if You do not forgive us and have mercy upon us, we will surely be among the losers.' Allah accepted their repentance.",
        "source": "Quran 7:19-23, 2:37"
    },
    {
        "title": "Prophet Nuh (Noah) and the Great Flood",
        "content": "Prophet Nuh called his people to worship Allah alone for 950 years, but only a few believed. Allah commanded him to build an ark. When the flood came, it covered the entire earth. Nuh's son refused to board the ark, saying he would climb a mountain. Nuh called to him, 'There is no refuge today from Allah's decree except for whom He gives mercy.' The son drowned, and only those on the ark survived.",
        "source": "Quran 11:36-48, Sahih Bukhari"
    },
    {
        "title": "Prophet Ibrahim (Abraham) and the Fire",
        "content": "When Ibrahim destroyed the idols of his people, they decided to burn him alive. They built a huge fire, so large that birds died flying over it. Allah commanded the fire: 'O fire, be coolness and safety upon Ibrahim.' The fire burned only his ropes, and Ibrahim emerged unharmed. This miracle amazed everyone and proved Allah's power over His creation.",
        "source": "Quran 21:68-70, Tafsir Ibn Kathir"
    },
    {
        "title": "Prophet Ibrahim's Sacrifice",
        "content": "Ibrahim saw in a dream that he was sacrificing his son Ismail. Knowing that prophets' dreams are revelations, he told Ismail, who replied, 'O my father, do as you are commanded. You will find me, if Allah wills, among the patient.' As Ibrahim was about to sacrifice his son, Allah called out that the dream was fulfilled and replaced Ismail with a ram. This became the origin of Eid al-Adha.",
        "source": "Quran 37:102-107"
    },
    {
        "title": "Prophet Yusuf (Joseph) and His Brothers",
        "content": "Yusuf's brothers were jealous of their father's love for him. They threw him into a well and told their father that a wolf had killed him. Allah revealed to young Yusuf that he would one day remind them of this deed. A caravan found him and sold him as a slave in Egypt. Despite this betrayal, Yusuf never lost faith in Allah's plan.",
        "source": "Quran 12:8-20"
    },
    {
        "title": "Prophet Yusuf and Potiphar's Wife",
        "content": "The wife of the Egyptian minister (Aziz) tried to seduce Yusuf, but he refused, saying, 'I seek refuge in Allah. Indeed, my master has made good my residence. Indeed, wrongdoers will not succeed.' When she chased him to the door and tore his shirt from behind, her husband returned. Yusuf was imprisoned despite his innocence, but Allah was with him.",
        "source": "Quran 12:23-35"
    },
    {
        "title": "Prophet Musa (Moses) and the Burning Bush",
        "content": "While traveling with his family, Musa saw a fire on Mount Sinai. Hoping to bring back burning wood, he approached it. But when he came near, a voice called: 'O Musa, indeed I am your Lord. Remove your sandals; indeed, you are in the sacred valley of Tuwa. I have chosen you, so listen to what is revealed.' This was Musa's first encounter with Allah's direct communication.",
        "source": "Quran 20:9-13"
    },
    {
        "title": "Prophet Musa and Pharaoh's Magicians",
        "content": "Pharaoh gathered his best magicians to challenge Musa. They threw their ropes and staffs, which appeared to move like snakes through magic. Then Musa threw his staff, and it became a real snake that swallowed all their illusions. The magicians immediately recognized the truth and proclaimed: 'We believe in the Lord of Musa and Harun!' Despite Pharaoh's threats, they chose faith over worldly life.",
        "source": "Quran 7:109-126"
    },
    {
        "title": "Prophet Musa Splitting the Red Sea",
        "content": "When Pharaoh's army pursued the Israelites to the sea, the people panicked. Musa said, 'No! Indeed, with me is my Lord; He will guide me.' Allah commanded Musa to strike the sea with his staff. The sea split into twelve dry paths with walls of water on both sides. The Israelites crossed safely, but when Pharaoh's army followed, the waters closed upon them and they all drowned.",
        "source": "Quran 26:60-66, Exodus account"
    },
    {
        "title": "Prophet Dawud (David) and Goliath",
        "content": "Young Dawud was chosen by Allah to face the giant warrior Goliath (Jalut) when the Israelite army was afraid. Armed only with a sling and stones, Dawud said, 'You come against me with sword and spear, but I come against you in the name of Allah.' He struck Goliath in the forehead with a stone, killing him instantly. This victory made Dawud famous and began his path to kingship.",
        "source": "Quran 2:251, 1 Samuel 17"
    },
    {
        "title": "Prophet Dawud's Beautiful Voice",
        "content": "Allah blessed Dawud with the most beautiful voice among all creation. When he recited the Zabur (Psalms), birds would gather above him and repeat his praises, mountains would echo his words, and even jinns and humans would weep upon hearing him. The Prophet Muhammad (PBUH) said that Dawud was given a family of voices (beautiful voices for his family) from the voices of Paradise.",
        "source": "Quran 21:79, Sahih Bukhari"
    },
    {
        "title": "Prophet Sulaiman (Solomon) and the Hoopoe",
        "content": "Prophet Sulaiman noticed that the hoopoe bird was missing from his assembly of birds and animals. When the hoopoe returned, it said: 'I have learned something you do not know. I have come to you from Sheba with certain news. Indeed, I found a woman ruling them, and she has been given everything, and she has a great throne. I found her and her people prostrating to the sun instead of Allah.'",
        "source": "Quran 27:20-26"
    },
    {
        "title": "Prophet Sulaiman and the Queen of Sheba",
        "content": "After receiving news from the hoopoe about Queen Bilqis of Sheba, Sulaiman sent her a letter inviting her to Islam. When she visited his palace, he had her throne brought from Sheba before her arrival through supernatural means. Seeing this miracle and the grandeur of Sulaiman's kingdom, Queen Bilqis declared: 'My Lord, I have wronged myself, and I submit with Sulaiman to Allah, Lord of the worlds.'",
        "source": "Quran 27:27-44"
    },
    {
        "title": "Prophet Ayyub (Job) and His Patience",
        "content": "Prophet Ayyub was tested with the loss of his wealth, children, and health. His body was covered with painful sores, and people avoided him except his faithful wife. Despite years of suffering, Ayyub never complained against Allah. He would say: 'Truly, distress has seized me, but You are the Most Merciful of those who show mercy.' Allah eventually restored his health, wealth, and blessed him with children again, doubling what he had before.",
        "source": "Quran 21:83-84, Book of Job"
    },
    {
        "title": "Prophet Yunus (Jonah) and the Whale",
        "content": "Prophet Yunus left his people in anger before Allah gave him permission. He boarded a ship, which was caught in a storm. The sailors cast lots to see who was causing their misfortune, and Yunus was chosen. A great whale swallowed him. In the darkness of the whale's belly, Yunus called out: 'There is no deity except You; exalted are You. Indeed, I have been of the wrongdoers.' Allah saved him and caused the whale to cast him onto the shore.",
        "source": "Quran 21:87-88, 37:139-148"
    },
    {
        "title": "Prophet Isa (Jesus) Speaking as a Baby",
        "content": "When Maryam brought baby Isa to her people, they accused her of wrongdoing. Allah made the infant Isa speak from the cradle to defend his mother. He said: 'Indeed, I am the servant of Allah. He has given me the Scripture and made me a prophet. He has made me blessed wherever I am and has enjoined upon me prayer and charity as long as I remain alive.'",
        "source": "Quran 19:30-33"
    },
    {
        "title": "Prophet Isa's Miracles",
        "content": "Allah gave Isa many miracles: he would create birds from clay and breathe life into them, heal the blind and lepers, and raise the dead - all by Allah's permission. When the disciples asked for a sign, Isa prayed for a heavenly feast. Allah sent down a table spread with food, but warned that whoever disbelieved afterward would receive a punishment not given to anyone in the worlds.",
        "source": "Quran 5:110-115, 3:49"
    },
    {
        "title": "Prophet Muhammad's Birth and Childhood",
        "content": "The Prophet was born on a Monday in the month of Rabi' al-Awwal in the Year of the Elephant (570 CE). His father Abdullah died before his birth, and his mother Aminah died when he was six. His grandfather Abdul Muttalib cared for him until age eight, then his uncle Abu Talib. Even as a child, he was known for his honesty and trustworthiness, earning the title 'As-Sadiq Al-Amin' (The Truthful, The Trustworthy).",
        "source": "Sirah Ibn Hisham, Sahih Bukhari"
    },
    {
        "title": "The Prophet's First Revelation",
        "content": "At age 40, while meditating in Cave Hira, Angel Jibril appeared to Muhammad and commanded 'Iqra!' (Read!). Muhammad replied, 'I cannot read.' The angel embraced him tightly three times, each time commanding him to read, until finally revealing: 'Read in the name of your Lord who created. Created man from a clot. Read, and your Lord is the Most Generous.' This was the beginning of the Quran's revelation.",
        "source": "Sahih Bukhari, Sahih Muslim"
    },
    {
        "title": "The Prophet's Night Journey (Isra and Mi'raj)",
        "content": "One night, Angel Jibril brought the Buraq, a celestial mount, and took the Prophet from Mecca to Jerusalem (Isra), then up through the seven heavens (Mi'raj). He met previous prophets, spoke with Allah, and received the command for five daily prayers. Initially, it was fifty prayers, but through Musa's advice and the Prophet's requests, Allah reduced it to five with the reward of fifty.",
        "source": "Sahih Bukhari, Sahih Muslim, Quran 17:1"
    },
    {
        "title": "The Prophet's Forgiveness at the Conquest of Mecca",
        "content": "When the Prophet conquered Mecca with 10,000 companions, his enemies expected revenge. Instead, he stood at the Kaaba and asked: 'What do you think I will do with you?' They replied: 'Good, for you are a noble brother and the son of a noble brother.' The Prophet declared: 'Go, for you are free.' He forgave even those who had tortured and killed his companions, showing the ultimate example of mercy and forgiveness.",
        "source": "Sirah Ibn Hisham, Sahih Bukhari"
    },
    {
        "title": "Abu Bakr's Loyalty in the Cave",
        "content": "During the Hijra to Medina, the Prophet and Abu Bakr hid in Cave Thawr for three days. When their pursuers came close, Abu Bakr worried and said, 'O Prophet of Allah, if one of them looks down at his feet, he will see us.' The Prophet calmly replied: 'What do you think of two people when Allah is the third with them? Do not grieve; indeed Allah is with us.' Allah sent tranquility upon them and protected them.",
        "source": "Quran 9:40, Sahih Bukhari"
    },
    {
        "title": "Umar ibn al-Khattab's Conversion to Islam",
        "content": "Umar was initially one of Islam's fiercest enemies. One day, he set out to kill the Prophet but was told his sister Fatimah had converted. He went to her house in anger, struck her and her husband, then saw blood on her face. Feeling remorse, he asked to read what they were reciting. Upon reading Surah Ta-Ha, his heart softened and he immediately went to the Prophet to accept Islam, greatly strengthening the Muslim community.",
        "source": "Sirah Ibn Hisham, Sahih Bukhari"
    },
    {
        "title": "Uthman ibn Affan's Generosity",
        "content": "During the expedition to Tabuk, the Muslim army faced severe financial difficulties. The Prophet asked for donations, and Uthman brought 300 camels loaded with supplies and 1,000 gold dinars. He placed it all before the Prophet, who turned the money over in his hands and said: 'Nothing will harm Uthman after today, nothing will harm Uthman after today.' Uthman was known for his extraordinary generosity throughout his life.",
        "source": "Sunan at-Tirmidhi, Sahih Bukhari"
    },
    {
        "title": "Ali ibn Abi Talib's Courage at Khaybar",
        "content": "During the Battle of Khaybar, the Muslim army struggled to conquer a Jewish fortress. The Prophet said: 'Tomorrow I will give the flag to a man who loves Allah and His Messenger, and Allah and His Messenger love him.' The next morning, he called for Ali, who had eye problems. The Prophet spat in Ali's eyes and prayed for him - his eyes were immediately healed. Ali then conquered the fortress and lifted its heavy gate with such strength that several men later struggled to move it together.",
        "source": "Sahih Bukhari, Sahih Muslim"
    },
    {
        "title": "Bilal ibn Rabah's Persecution and Faith",
        "content": "Bilal was an Ethiopian slave who accepted Islam early. His master Umayyah ibn Khalaf tortured him under the scorching sun, placing a heavy rock on his chest, demanding he renounce Islam. Bilal would only say 'Ahad, Ahad' (One, One), referring to Allah's oneness. Abu Bakr bought and freed him. Later, Bilal became the Prophet's muezzin and was the first to give the call to prayer from atop the Kaaba after Mecca's conquest.",
        "source": "Sirah Ibn Hisham, Sahih Bukhari"
    },
    {
        "title": "Khalid ibn al-Walid - The Unsheathed Sword",
        "content": "Khalid initially fought against Muslims at Uhud, causing significant damage to the Muslim army. After accepting Islam, he became the greatest military tactician in Islamic history. The Prophet named him 'Sayf Allah al-Maslul' (The Unsheathed Sword of Allah). Khalid never lost a single battle and was instrumental in the Ridda wars and early Islamic conquests. He was so successful that Caliph Umar removed him from command, fearing people might start depending on Khalid instead of Allah.",
        "source": "Sirah Books, Historical Records"
    },
    {
        "title": "Salman al-Farisi's Search for Truth",
        "content": "Salman was a Persian who left Zoroastrianism to seek truth. He served Christian monks and learned about a coming prophet. Enslaved and brought to Medina, he heard about Muhammad and tested him with three signs his previous teacher had mentioned. When all signs proved true, Salman accepted Islam. The Prophet said 'Salman is from us, the household,' showing that faith transcends ethnicity. Salman suggested digging a trench to defend Medina, earning him the title 'Salman the Persian.'",
        "source": "Sahih Bukhari, Sirah Books"
    },
    {
        "title": "Ammar ibn Yasir's Family's Martyrdom",
        "content": "Ammar and his parents Yasir and Sumayyah were among the first Muslims. The Meccan polytheists tortured them severely. Sumayyah, Ammar's mother, was killed by Abu Jahl and became the first martyr in Islam. Yasir was also tortured to death. The Prophet would pass by them during their torture and say: 'Be patient, O family of Yasir, for your appointment is Paradise.' When forced to speak against Islam to save his life, Ammar was later comforted by Quranic revelation allowing such speech under extreme duress.",
        "source": "Tafsir Ibn Kathir, Sirah Books"
    },
    {
        "title": "Sa'd ibn Abi Waqqas and His Mother",
        "content": "When Sa'd accepted Islam, his mother swore she would neither eat nor drink until he abandoned his faith. She said: 'You claim Allah commanded you to be dutiful to parents. I am your mother, and I command you to give up this religion.' Sa'd replied: 'O mother, if you had a hundred souls and they departed one by one, I would not abandon this religion.' Allah revealed verses about being kind to parents but not obeying them in matters that displease Allah. His mother eventually ate.",
        "source": "Quran 29:8, Sahih Muslim"
    },
    {
        "title": "The Story of Uwais al-Qarni",
        "content": "Uwais lived in Yemen and never met the Prophet but was a sincere Muslim. The Prophet told Umar and Ali: 'There is a man in Yemen called Uwais. He has leprosy, and all of it has been healed except for a spot the size of a coin. He is very dutiful to his mother. If he takes an oath by Allah, Allah fulfills it. If you can ask him to pray for your forgiveness, do so.' Years later, Umar met Uwais during Hajj and asked for his prayers, showing the value of righteousness even without direct contact with the Prophet.",
        "source": "Sahih Muslim"
    },
    {
        "title": "The Patience of Abu Dujana",
        "content": "Abu Dujana was known for his incredible bravery in battle. At the Battle of Uhud, he wore a red headband that he only put on when determined to fight to the death. During the battle, he shielded the Prophet with his own body, and arrows struck his back while he protected the Prophet. Despite being wounded, he continued fighting. The Prophet praised his sacrifice and bravery, and Abu Dujana was known as one of the most courageous companions.",
        "source": "Sirah Ibn Hisham"
    },
    {
        "title": "The Honesty of Abdul Rahman ibn Awf",
        "content": "When Abdul Rahman migrated to Medina, his Ansar brother offered to share his wealth and even divorce one of his wives so Abdul Rahman could marry her. Abdul Rahman declined, saying: 'May Allah bless your family and wealth. Just show me the way to the market.' He started trading and became very wealthy through honest business. He was so successful that he once donated 700 camels loaded with goods to charity, making Umar weep and say, 'Go, for you have purified yourself.'",
        "source": "Sahih Bukhari"
    },
    {
        "title": "The Wisdom of Luqman the Wise",
        "content": "Luqman was a wise man (some scholars say a prophet) known for his parables and teachings. The Quran mentions his advice to his son: 'O my son, do not associate anything with Allah. Indeed, association is great injustice.' He taught about being grateful to Allah and parents, praying regularly, enjoining good and forbidding evil, and being patient. His wisdom included: 'O my son, indeed if a wrong should be the weight of a mustard seed and should be within a rock, Allah will bring it forth.'",
        "source": "Quran 31:12-19"
    },
    {
        "title": "The Story of the People of the Cave (Ashab al-Kahf)",
        "content": "A group of young believers fled their tyrannical king who forced idol worship. They sought refuge in a cave and prayed: 'Our Lord, give us mercy from Yourself and prepare for us right guidance in our affair.' Allah caused them to sleep for 309 years. When they awakened, they thought only a day had passed. One went to buy food but found everything changed - their coins were ancient, and their city was now Christian. Allah made their story known to show His power over time and death.",
        "source": "Quran 18:9-26"
    },
    {
        "title": "The Queen of Sheba's Test of Wisdom",
        "content": "Before visiting Prophet Sulaiman, Queen Bilqis wanted to test his wisdom. She sent him gifts including identical boys and girls dressed the same way to see if he could distinguish them. Sulaiman presented them with water basins - the girls washed their faces gently while boys splashed roughly, revealing their true nature. She also sent him a necklace with a twisted thread, which Sulaiman had ants straighten using honey. These tests convinced her of his God-given wisdom.",
        "source": "Islamic Historical Sources, Tafsir"
    },
    {
        "title": "The Repentance of Ka'b ibn Malik",
        "content": "Ka'b was one of three companions who missed the Battle of Tabuk without valid excuse. When the Prophet returned, Ka'b chose honesty over lies that others told. The Prophet ordered Muslims to boycott the three. For 50 days, Ka'b lived in isolation, his wife was sent away, and no one spoke to him. Finally, Allah revealed their forgiveness in the Quran. Ka'b said: 'I was never more grateful to Allah than when I heard my name in the Quran announcing our forgiveness.'",
        "source": "Quran 9:118, Sahih Bukhari"
    },
    {
        "title": "The Martyrdom of Hamza ibn Abdul Muttalib",
        "content": "Hamza, the Prophet's uncle and one of the strongest warriors, accepted Islam after learning that Abu Jahl had insulted the Prophet. At the Battle of Uhud, he fought valiantly until Wahshi, an Ethiopian slave, killed him with a javelin from hiding. After the battle, the Prophet found Hamza's mutilated body and wept bitterly. He called Hamza 'Sayyid al-Shuhada' (Master of Martyrs) and prayed for him. This loss deeply affected the Prophet, showing his human emotions and love for family.",
        "source": "Sahih Bukhari, Sirah Ibn Hisham"
    },
    {
        "title": "The Conversion of Thumama ibn Uthal",
        "content": "Thumama was a chief who came to kill the Prophet but was captured and tied to a pillar in the mosque. The Prophet visited him daily, offering food and asking about his condition. After three days, the Prophet ordered his release. Thumama was so impressed by this treatment that he immediately accepted Islam, saying: 'By Allah, there was no face on earth more hateful to me than yours, but now your face has become the most beloved to me.' He performed Umrah and announced his conversion loudly in Mecca.",
        "source": "Sahih Bukhari"
    },
    {
        "title": "The Miracle of the Splitting Moon",
        "content": "When the people of Mecca demanded a miracle from the Prophet, Allah split the moon in two halves, one appearing on each side of Mount Hira. The people saw this clearly, but the disbelievers said: 'This is continuous magic.' They claimed Muhammad had somehow bewitched them. However, travelers arriving from other regions confirmed they had also seen the moon split, proving it was a real miracle. This event is mentioned in the Quran: 'The Hour has come near, and the moon has split.'",
        "source": "Quran 54:1, Sahih Bukhari, Sahih Muslim"
    },
    {
        "title": "The Loyalty of Anas ibn Malik",
        "content": "Anas served the Prophet for ten years from age 10 to 20. His mother brought him to serve in the Prophet's household. Anas later said: 'I served the Prophet for ten years. He never said 'Uff' (expression of annoyance) to me, never asked why I did something, and never asked why I didn't do something.' This shows the Prophet's perfect character and patience. Anas was blessed with long life and died at age 103, being the last companion to die in Basra.",
        "source": "Sahih Bukhari, Sahih Muslim"
    },
    {
        "title": "The Wisdom of Ali ibn Abi Talib",
        "content": "Ali was raised in the Prophet's household and was among the first to accept Islam. Known for his wisdom, he said: 'The worth of a man is determined by his good deeds,' and 'He who knows himself knows his Lord.' When asked about the Quran, he said: 'The Quran is neither silent nor does it speak, but people make it speak.' His judicial decisions were so wise that the Prophet said: 'I am the city of knowledge and Ali is its gate.' He combined deep spirituality with practical wisdom.",
        "source": "Nahj al-Balagha, Various Hadith Collections"
    },
    {
        "title": "The Generosity of Abu Bakr",
        "content": "Abu Bakr was so generous that he once brought all his wealth for a military expedition. When the Prophet asked what he had left for his family, Abu Bakr replied: 'Allah and His Messenger.' He frequently bought and freed slaves, including Bilal. His daughter Aisha said: 'My father never kept money overnight; he would distribute it before sleeping.' The Prophet said: 'No one's wealth has benefited me as much as Abu Bakr's wealth.' This generosity continued throughout his caliphate.",
        "source": "Sahih Bukhari, Sunan Abu Dawud"
    },
    {
        "title": "The Prophecy about Imam Hasan and Husayn",
        "content": "The Prophet loved his grandsons dearly and once said while carrying them: 'These two sons of mine are leaders. Perhaps through them Allah will reconcile two great groups of Muslims.' This prophecy came true when Hasan made peace with Muawiya to prevent civil war. The Prophet also said: 'Whoever loves them loves me, and whoever hates them hates me.' He would interrupt his sermons when he saw them stumbling in their long clothes to help them, showing his deep love for family.",
        "source": "Sahih Bukhari, Sunan at-Tirmidhi"
    },
    {
        "title": "The Justice of Umar ibn Abdul Aziz",
        "content": "Umar ibn Abdul Aziz, the fifth righteous Caliph, was known for his extraordinary justice. When he became Caliph, he returned all the wealth his family had acquired illegally. He would extinguish the public candle when discussing personal matters, using his own candle instead. His wife once asked for a servant, and he replied: 'Buy one with your own money, for the Muslims' money is not for our comfort.' During his short reign of 2.5 years, justice was so complete that it was hard to find poor people to give Zakat to.",
        "source": "Historical Chronicles, Sirah Sources"
    },
    {
        "title": "The Wisdom of Imam Hassan al-Basri",
        "content": "Hassan al-Basri was one of the greatest scholars and ascetics of the early generation. When asked about the dunya (worldly life), he said: 'The dunya is three days: yesterday which has passed with its good and evil, tomorrow which you may not reach, and today which is yours so act upon it.' He emphasized that true wealth is contentment, saying: 'Whoever is content with what Allah has given him is the richest of people.' His teachings focused on preparing for the afterlife while fulfilling worldly responsibilities.",
        "source": "Classical Islamic Literature"
    },
    {
        "title": "The Devotion of Rabia al-Adawiyya",
        "content": "Rabia was a female saint known for her pure love of Allah. She would pray: 'O Allah, if I worship You for fear of Hell, burn me in Hell.If I worship You in hope of Paradise, exclude me from Paradise. But if I worship You for Your own sake, do not withhold Your everlasting beauty from me.' Once seen carrying fire and water, she explained: 'I want to burn Paradise and extinguish Hell so people worship Allah for love alone, not fear or hope.' Her prayers emphasized sincere devotion over seeking rewards.",
        "source": "Sufi Literature and Biographical Works"
    },
    {
        "title": "The Miracle of the Treaty of Hudaybiyyah",
        "content": "When the Prophet went to Mecca for Umrah but was stopped at Hudaybiyyah, the companions felt disappointed by the treaty terms that seemed unfavorable. However, Allah called it 'a clear victory' in the Quran. Within two years, Islam spread so much that at the conquest of Mecca, 10,000 Muslims entered, compared to 1,400 at Hudaybiyyah. Umar later said: 'I kept giving charity after Hudaybiyyah because of the doubt I had about it.' This showed how Allah's wisdom surpasses human understanding.",
        "source": "Quran 48:1, Sahih Bukhari"
    },
    {
        "title": "The Forgiveness of Prophet Yusuf",
        "content": "When Yusuf's brothers came to Egypt during famine, not recognizing him as the Minister, he tested them but eventually revealed his identity. Instead of seeking revenge for their betrayal, he said: 'No blame will there be upon you today. Allah forgives you; and He is the most merciful of the merciful.' He then sent his shirt to heal his father's eyesight and invited his entire family to Egypt. This story teaches the power of forgiveness and trusting Allah's plan even in the darkest times.",
        "source": "Quran 12:92-93"
    },
    {
        "title": "The Test of Prophet Ibrahim with Nimrod",
        "content": "When Ibrahim debated with the tyrant Nimrod about Allah's power, Nimrod arrogantly claimed: 'I give life and cause death.' Ibrahim responded: 'Allah brings the sun from the east; bring it from the west.' Nimrod was speechless. Ibrahim also told his people: 'I have turned my face toward He who created the heavens and earth, inclining toward truth, and I am not of those who associate others with Allah.' This debate demonstrated how simple logic can expose falsehood when supported by Allah's guidance.",
        "source": "Quran 2:258, 6:79"
    },
    {
        "title": "The Humility of Prophet Muhammad in Victory",
        "content": "When the Prophet entered Mecca as a conqueror with 10,000 companions, he rode with his head so low in humility that his beard almost touched his camel's saddle. Despite having every right to seek revenge, he declared general amnesty. He cleaned the Kaaba of idols personally and recited: 'Truth has come, and falsehood has departed. Indeed, falsehood is bound to depart.' His humility in victory became a model for Muslim leaders, showing that success should increase gratitude, not pride.",
        "source": "Sirah Ibn Hisham, Sahih Bukhari"
    },
    {
        "title": "The Charity of Khadijah bint Khuwaylid",
        "content": "Khadijah was the Prophet's first wife and first believer. She was a successful businesswoman who used her wealth to support Islam. When the Prophet received his first revelation and feared he was going mad, Khadijah comforted him saying: 'Allah would never disgrace you. You keep good relations with relatives, help the poor and needy, serve guests generously, and assist those afflicted with calamities.' She spent her entire fortune supporting the early Muslim community during the boycott years. The Prophet said he was commanded to give her glad tidings of a house in Paradise.",
        "source": "Sahih Bukhari, Sahih Muslim"
    }
]

def populate_stories():
    """Insert stories into DB if empty"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM stories")
        count = cursor.fetchone()[0]
        if count > 0:
            print("Prophet stories already loaded.")
            return

        for story in PROPHET_STORIES:
            cursor.execute("""
                INSERT INTO stories (title, content, source)
                VALUES (?, ?, ?)
            """, (story['title'], story['content'], story['source']))

        conn.commit()
        print("✅ Prophet stories loaded successfully.")
    except Exception as e:
        print(f"Error loading stories: {e}")
    finally:
        if conn:
            conn.close()

# ======== TELEGRAM MESSAGE SENDING ========

def send_telegram_message(text, chat_id=None):
    """Send a message via Telegram bot to specific chat or all users"""
    try:
        url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_BOT_TOKEN']}/sendMessage"

        if chat_id:
            # Send to specific user
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload)
            if response.status_code != 200:
                print(f"Telegram send failed for {chat_id}: {response.text}")
        else:
            # Send to all registered users
            users = get_all_active_users()
            for user_chat_id in users:
                payload = {
                    "chat_id": user_chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
                response = requests.post(url, json=payload)
                if response.status_code != 200:
                    print(f"Telegram send failed for {user_chat_id}: {response.text}")
                time.sleep(0.1)  # Small delay to avoid rate limits
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def get_all_active_users():
    """Get all active user chat IDs"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM users WHERE is_active = 1")
        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error getting active users: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_ai_response(user_message):
    """Advanced AI response system with contextual understanding"""
    try:
        message_lower = user_message.lower().strip()

        # Advanced natural language processing
        question_words = ["what", "how", "why", "when", "where", "who", "which", "can", "should", "is", "are", "do", "does", "will", "would", "could"]
        is_question = any(word in message_lower for word in question_words) or message_lower.endswith("?")

        # Extract key topics and context
        topics = {
            "greeting": ["salam", "hello", "hi", "peace", "greetings", "good morning", "good evening"],
            "prayer": ["prayer", "salah", "namaz", "pray", "praying", "dua", "supplication", "worship", "rakah", "rakat", "wudu", "ablution"],
            "quran": ["quran", "verse", "ayah", "surah", "chapter", "revelation", "holy book", "kitab", "mushaf", "recitation"],
            "prophet": ["prophet", "muhammad", "pbuh", "messenger", "rasul", "nabi", "sunnah", "hadith", "biography"],
            "allah": ["allah", "god", "creator", "99 names", "asma", "attributes", "tawhid", "monotheism"],
            "islamic_practice": ["islam", "muslim", "faith", "belief", "religion", "practice", "worship", "deen"],
            "history": ["history", "mecca", "medina", "hijra", "caliphate", "companions", "sahaba"],
            "ramadan": ["ramadan", "fasting", "sawm", "iftar", "suhur", "eid", "tarawih"],
            "hajj": ["hajj", "pilgrimage", "kaaba", "mecca", "umrah", "tawaf", "arafat"],
            "ethics": ["morality", "ethics", "character", "akhlaq", "behavior", "kindness", "justice"],
            "death": ["death", "afterlife", "paradise", "hell", "judgment", "grave", "resurrection"],
            "family": ["family", "marriage", "children", "parents", "wife", "husband", "relationships"],
            "knowledge": ["knowledge", "education", "learning", "study", "wisdom", "ilm"],
            "charity": ["charity", "zakat", "sadaqah", "giving", "poor", "needy"],
            "forgiveness": ["forgiveness", "repentance", "tawbah", "sin", "mercy", "guilt"],
            "guidance": ["guidance", "advice", "help", "lost", "confused", "direction"]
        }

        # Detect primary topic
        detected_topics = []
        for topic, keywords in topics.items():
            if any(keyword in message_lower for keyword in keywords):
                detected_topics.append(topic)

        # Advanced contextual responses based on detected topics and question type

        if "greeting" in detected_topics:
            responses = [
                "Assalamu alaikum wa rahmatullahi wa barakatuh! 🌙\n\nWelcome! I'm here to help you explore Islamic knowledge. Whether you have questions about the Quran, prayer, Prophet Muhammad (PBUH), or any aspect of Islam, I'm ready to provide detailed, authentic answers.\n\nWhat would you like to learn about today?",
                "Wa alaikum assalam wa rahmatullahi wa barakatuh! ✨\n\nMay Allah's peace and blessings be upon you. I'm equipped with comprehensive Islamic knowledge and can discuss everything from basic practices to complex theological questions.\n\nFeel free to ask me anything about Islam!",
                "Peace and blessings upon you! 🤲\n\nI'm your Islamic knowledge companion, ready to help with questions about faith, practice, history, and spirituality. My responses are based on Quran, authentic Hadith, and scholarly consensus.\n\nHow can I assist you on your Islamic journey today?"
            ]
            return random.choice(responses)

        elif "prayer" in detected_topics:
            if any(word in message_lower for word in ["how", "perform", "steps", "way"]):
                return ("🕌 **Complete Guide to Islamic Prayer (Salah)**\n\n" +
                       "**Preparation:**\n" +
                       "• Perform Wudu (ablution) - wash hands, mouth, nose, face, arms, head, ears, feet\n" +
                       "• Face the Qibla (direction of Kaaba in Mecca)\n" +
                       "• Ensure clean clothes and prayer area\n\n" +
                       "**Prayer Steps:**\n" +
                       "1️⃣ **Takbiratul Ihram** - Raise hands and say 'Allahu Akbar'\n" +
                       "2️⃣ **Qiyam** - Stand and recite Al-Fatiha + another surah\n" +
                       "3️⃣ **Ruku** - Bow and say 'Subhana Rabbiyal Azeem' (3x)\n" +
                       "4️⃣ **Sujud** - Prostrate and say 'Subhana Rabbiyal A'la' (3x)\n" +
                       "5️⃣ **Tashahhud** - Sit and recite the testimony of faith\n\n" +
                       "**Daily Prayers:**\n" +
                       "🌅 Fajr (Dawn): 2 rakats\n" +
                       "☀️ Dhuhr (Midday): 4 rakats\n" +
                       "🌅 Asr (Afternoon): 4 rakats\n" +
                       "🌅 Maghrib (Sunset): 3 rakats\n" +
                       "🌙 Isha (Night): 4 rakats\n\n" +
                       "Would you like details about any specific prayer or aspect?")
            elif any(word in message_lower for word in ["time", "when", "schedule"]):
                return ("⏰ **Prayer Times Guide**\n\n" +
                       "Prayer times vary by location and season. Here's the general schedule:\n\n" +
                       "🌅 **Fajr**: From true dawn until sunrise\n" +
                       "☀️ **Dhuhr**: From when sun passes meridian until Asr time\n" +
                       "🌆 **Asr**: When object's shadow equals its length + original shadow\n" +
                       "🌇 **Maghrib**: From sunset until twilight disappears\n" +
                       "🌙 **Isha**: From twilight until midnight (or dawn)\n\n" +
                       "📱 Use apps like 'Muslim Pro' or 'Athan Pro' for accurate local times\n" +
                       "🕌 Check with your local mosque for community prayer times\n\n" +
                       "The Prophet (PBUH) said: 'The time of prayer is among the best of times, so compete in doing good during it.'")
            else:
                return ("🤲 **The Importance of Prayer in Islam**\n\n" +
                       "Prayer (Salah) is the second pillar of Islam and the most important act after belief in Allah.\n\n" +
                       "**Benefits of Prayer:**\n" +
                       "• Direct connection with Allah\n" +
                       "• Spiritual purification and peace\n" +
                       "• Protection from sin and evil\n" +
                       "• Community bonding (congregational prayer)\n" +
                       "• Discipline and time management\n\n" +
                       "**Quranic Verse:** 'Verily, in the remembrance of Allah do hearts find rest.' (13:28)\n\n" +
                       "**Hadith:** 'Prayer is the ascension (Mi'raj) of the believer.' - Prophet Muhammad (PBUH)\n\n" +
                       "Ask me about prayer times, how to pray, or specific prayer-related questions!")

        elif "quran" in detected_topics:
            if any(word in message_lower for word in ["how many", "number", "count"]):
                return ("📖 **The Holy Quran - Complete Structure**\n\n" +
                       "**Main Statistics:**\n" +
                       "• 114 Surahs (chapters)\n" +
                       "• 6,236 verses (some count 6,348)\n" +
                       "• 77,449 words\n" +
                       "• 323,015 letters\n" +
                       "• 30 Para/Juz (sections)\n\n" +
                       "**Revelation Period:** 23 years (610-632 CE)\n" +
                       "**Languages:** Revealed in Arabic, translated into 100+ languages\n\n" +
                       "**Notable Facts:**\n" +
                       "• Longest Surah: Al-Baqarah (286 verses)\n" +
                       "• Shortest Surah: Al-Kawthar (3 verses)\n" +
                       "• Central Verse: 2:143 (middle of Quran)\n" +
                       "• Most mentioned Prophet: Musa/Moses (136 times)\n\n" +
                       "The Quran is preserved in its original form - not a single letter has changed since revelation!")

            elif any(word in message_lower for word in ["favorite", "best", "beautiful", "powerful"]):
                return ("✨ **Beautiful and Powerful Quranic Verses**\n\n" +
                       "Here are some of the most beloved verses:\n\n" +
                       "🌟 **Ayat-ul-Kursi (2:255)** - The Throne Verse\n" +
                       "'Allah - there is no deity except Him, the Ever-Living, the Sustainer...'\n\n" +
                       "💖 **Verse of Light (24:35)**\n" +
                       "'Allah is the light of the heavens and the earth...'\n\n" +
                       "🤲 **Al-Fatiha (1:1-7)** - The Opening\n" +
                       "'In the name of Allah, the Entirely Merciful, the Especially Merciful...'\n\n" +
                       "🌅 **Hope Verse (39:53)**\n" +
                       "'Say: O My servants who have transgressed against themselves, do not despair of Allah's mercy...'\n\n" +
                       "Would you like me to share the full text and explanation of any of these verses?")

            else:
                return ("📚 **The Holy Quran - Guide for Humanity**\n\n" +
                       "The Quran is Allah's final revelation, sent through Prophet Muhammad (PBUH) as guidance for all mankind.\n\n" +
                       "**Key Themes:**\n" +
                       "• Tawhid (Unity of Allah)\n" +
                       "• Stories of previous prophets\n" +
                       "• Moral and ethical guidance\n" +
                       "• Laws and social justice\n" +
                       "• Science and natural phenomena\n" +
                       "• Afterlife and spiritual development\n\n" +
                       "**Miracle Aspects:**\n" +
                       "• Linguistic perfection\n" +
                       "• Scientific accuracies\n" +
                       "• Historical preservation\n" +
                       "• Psychological and spiritual impact\n\n" +
                       "Ask me about specific surahs, verses, themes, or how to develop a relationship with the Quran!")

        elif "prophet" in detected_topics:
            if any(word in message_lower for word in ["life", "biography", "story", "birth", "death"]):
                return ("👑 **Prophet Muhammad (PBUH) - Complete Biography**\n\n" +
                       "**Early Life (570-610 CE):**\n" +
                       "• Born in Mecca to Abdullah and Aminah\n" +
                       "• Orphaned early, raised by grandfather then uncle Abu Talib\n" +
                       "• Known as 'As-Sadiq Al-Amin' (The Truthful, The Trustworthy)\n" +
                       "• Married Khadijah (RA) at age 25\n\n" +
                       "**Prophethood (610-632 CE):**\n" +
                       "• First revelation in Cave Hira at age 40\n" +
                       "• 13 years in Mecca facing persecution\n" +
                       "• Hijra to Medina in 622 CE\n" +
                       "• Established first Islamic state\n" +
                       "• Farewell Pilgrimage and death in 632 CE\n\n" +
                       "**Character Traits:**\n" +
                       "• Perfect honesty and trustworthiness\n" +
                       "• Extreme kindness to all creation\n" +
                       "• Justice and fairness\n" +
                       "• Humility despite being chosen by Allah\n" +
                       "• Forgiveness even to enemies\n\n" +
                       "Would you like details about any specific period or aspect of his life?")

            elif any(word in message_lower for word in ["character", "personality", "qualities", "example"]):
                return ("🌟 **The Perfect Character of Prophet Muhammad (PBUH)**\n\n" +
                       "Allah said: 'Indeed in the Messenger of Allah you have a good example.' (33:21)\n\n" +
                       "**His Character Qualities:**\n\n" +
                       "🤲 **With Allah:** Perfect worship, constant remembrance, complete submission\n\n" +
                       "❤️ **With Family:** Loving husband, caring father, helpful at home\n" +
                       "• 'The best of you are those who are best to their families' - His teaching\n\n" +
                       "🤝 **With People:** Just leader, trustworthy businessman, forgiving friend\n" +
                       "• Never lied, even before prophethood\n" +
                       "• Forgave those who wronged him\n\n" +
                       "🐾 **With Animals:** Kind to all creatures\n" +
                       "• Spoke against animal cruelty\n" +
                       "• A woman entered Hell for starving a cat\n\n" +
                       "💼 **As Leader:** Consulted others, served people, lived simply\n" +
                       "• Swept his own house\n" +
                       "• Mended his own clothes\n\n" +
                       "His wife Aisha (RA) said: 'His character was the Quran' - meaning he lived by every Quranic teaching perfectly.")

            else:
                return ("🕌 **Prophet Muhammad (PBUH) - The Final Messenger**\n\n" +
                       "Muhammad ibn Abdullah (570-632 CE) is the final prophet sent by Allah to guide humanity.\n\n" +
                       "**His Mission:**\n" +
                       "• Complete the message of all previous prophets\n" +
                       "• Deliver the final revelation (Quran)\n" +
                       "• Establish justice and monotheism\n" +
                       "• Be a mercy to all creation\n\n" +
                       "**His Teachings:**\n" +
                       "• Worship Allah alone\n" +
                       "• Treat all people with kindness\n" +
                       "• Seek knowledge from cradle to grave\n" +
                       "• Care for the poor and needy\n" +
                       "• Protect the environment\n\n" +
                       "**Global Impact:**\n" +
                       "• 1.8 billion Muslims follow his teachings\n" +
                       "• Influenced law, ethics, and civilization\n" +
                       "• Promoted education and scientific inquiry\n\n" +
                       "Ask me about his life events, teachings, or how to follow his example!")

        # Continue with more advanced responses for other topics...
        elif any(word in message_lower for word in ["stupid", "dumb", "useless", "bad", "terrible"]):
            return ("I understand you're looking for more sophisticated responses! 🤔\n\n" +
                   "I'm designed to provide detailed, accurate Islamic knowledge. To give you the best answer, please ask me specific questions like:\n\n" +
                   "📚 'Explain the concept of predestination in Islam'\n" +
                   "🔬 'What does the Quran say about embryology?'\n" +
                   "⚖️ 'How does Islamic law approach social justice?'\n" +
                   "🧠 'What is the Islamic perspective on mental health?'\n" +
                   "🌍 'How did early Muslims contribute to science?'\n\n" +
                   "The more specific your question, the more detailed and insightful my response will be. What Islamic topic would you like to explore deeply?")

        # If it's a complex question but no specific topic detected
        elif is_question:
            return ("🤔 I'd love to provide you with a comprehensive answer! \n\n" +
                   "Your question seems to be looking for detailed Islamic knowledge. To give you the most accurate and helpful response, could you specify what aspect of Islam you're interested in?\n\n" +
                   "I can provide in-depth discussions about:\n" +
                   "📖 Quranic interpretation and context\n" +
                   "🕌 Islamic jurisprudence and rulings\n" +
                   "📚 Hadith sciences and authentication\n" +
                   "🏛️ Islamic history and civilization\n" +
                   "🧠 Islamic philosophy and theology\n" +
                   "⚖️ Ethics and moral guidance\n" +
                   "🔬 Islam and modern science\n\n" +
                   "Please rephrase your question with more specific details, and I'll provide a thorough, scholarly response!")

        else:
            # Default intelligent response
            return ("AssalamuAlaikum! 🌙\n\n" +
                   "I'm equipped with comprehensive Islamic knowledge and ready to engage in meaningful discussions about faith, practice, and spirituality.\n\n" +
                   "**I can help you with:**\n" +
                   "🎯 Complex theological questions\n" +
                   "📊 Detailed Quranic analysis\n" +
                   "🏛️ Islamic history and civilization\n" +
                   "⚖️ Fiqh (Islamic jurisprudence)\n" +
                   "🧠 Spiritual development guidance\n" +
                   "🔬 Islam and modern issues\n\n" +
                   "What specific aspect of Islam would you like to explore? The more detailed your question, the more comprehensive my response will be!")

    except Exception as e:
        print(f"Error in AI response: {e}")
        return ("I apologize for the technical issue. Please ask me any Islamic question - I'm designed to provide detailed, scholarly responses about Quran, Hadith, Islamic law, history, and spiritual guidance. What would you like to know?")

def register_user(chat_id, username=None, first_name=None):
    """Register a new user"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO users (chat_id, username, first_name, is_active)
            VALUES (?, ?, ?, 1)
        """, (str(chat_id), username, first_name))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error registering user: {e}")
        return False
    finally:
        if conn:
            conn.close()

def deactivate_user(chat_id):
    """Deactivate a user (unsubscribe)"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE chat_id = ?", (str(chat_id),))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deactivating user: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ======== PRAYER TIME FUNCTIONS ========

def get_prayer_times():
    """Get today's prayer times for configured location"""
    try:
        params = {
            "address": CONFIG['LOCATION']['address'],
            "method": CONFIG['LOCATION']['method'],
            "school": CONFIG['LOCATION']['school'],
            "date": datetime.now().strftime("%d-%m-%Y")
        }
        resp = requests.get(CONFIG['PRAYER_TIMES_API'], params=params, timeout=10)
        data = resp.json()

        if data['code'] != 200:
            print("Failed to get prayer times:", data)
            return None

        return data['data']['timings']
    except Exception as e:
        print("Error fetching prayer times:", e)
        return None

def schedule_prayer_reminders():
    """Schedule prayer reminders for today"""
    prayer_times = get_prayer_times()
    if not prayer_times:
        print("Using fallback prayer times")
        prayer_times = {
            "Fajr": "05:30",
            "Dhuhr": "13:00", 
            "Asr": "16:00",
            "Maghrib": "19:00",
            "Isha": "20:30"
        }

    schedule.clear('prayers')

    for prayer, time_str in prayer_times.items():
        if prayer in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
            # Extract just HH:MM if there are seconds
            clean_time = time_str.split(' ')[0] if ' ' in time_str else time_str
            schedule.every().day.at(clean_time).do(
                send_prayer_reminder, prayer
            ).tag('prayers')
            print(f"Scheduled {prayer} at {clean_time}")

def send_prayer_reminder(prayer_name):
    """Send prayer time reminder with Quran verse"""
    verse = get_random_verse()
    if not verse:
        print("No verse available for prayer reminder")
        return

    message = (f"<b>{prayer_name} Reminder</b>\n\n"
               f"<b>{verse['surah_name']} ({verse['surah_number']}:{verse['ayah_number']})</b>\n"
               f"{verse['arabic_text']}\n\n"
               f"{verse['translation']}\n\n"
               "May Allah accept your prayer ❤️")
    send_telegram_message(message)

# ======== VERSE FUNCTIONS ========

def get_random_verse():
    """Get a random Quran verse not sent recently"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # First try to get verses with proper translations
        cursor.execute("""
            SELECT id, surah_number, surah_name, ayah_number, arabic_text, translation
            FROM verses
            WHERE (last_sent IS NULL OR last_sent < ?) 
            AND translation != 'Translation not available'
            AND translation != 'No translation available'
            AND translation IS NOT NULL
            AND LENGTH(translation) > 10
            ORDER BY RANDOM()
            LIMIT 1
        """, (cutoff_date,))

        verse = cursor.fetchone()
        
        # If no verse with good translation found, get any verse and try to fix translation
        if not verse:
            cursor.execute("""
                SELECT id, surah_number, surah_name, ayah_number, arabic_text, translation
                FROM verses
                WHERE last_sent IS NULL OR last_sent < ?
                ORDER BY RANDOM()
                LIMIT 1
            """, (cutoff_date,))
            verse = cursor.fetchone()
            
            if not verse:
                return None
                
            # Try to fetch better translation from API
            verse_id, surah_num, surah_name, ayah_num, arabic, translation = verse
            better_translation = fetch_verse_translation(surah_num, ayah_num)
            if better_translation:
                translation = better_translation
                # Update in database
                cursor.execute("UPDATE verses SET translation = ? WHERE id = ?", (translation, verse_id))
                conn.commit()

        if not verse:
            return None

        verse_id, surah_num, surah_name, ayah_num, arabic, translation = verse

        # Update last_sent
        cursor.execute("UPDATE verses SET last_sent = ? WHERE id = ?", 
                      (datetime.now().strftime("%Y-%m-%d"), verse_id))
        conn.commit()

        return {
            "surah_number": surah_num,
            "surah_name": surah_name,
            "ayah_number": ayah_num,
            "arabic_text": arabic,
            "translation": translation
        }
    except Exception as e:
        print(f"Error getting random verse: {e}")
        return None
    finally:
        if conn:
            conn.close()

def fetch_verse_translation(surah_number, ayah_number):
    """Fetch a specific verse translation from API"""
    try:
        url = f"{CONFIG['QURAN_API']}ayah/{surah_number}:{ayah_number}/en.sahih"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('data') and data['data'].get('text'):
                return data['data']['text'].strip()
    except Exception as e:
        print(f"Error fetching translation for {surah_number}:{ayah_number}: {e}")
    return None

def send_daily_verses():
    """Send daily Quran verses"""
    verses = get_random_verses(CONFIG['SCHEDULE']['random_verses_per_day'])
    if not verses:
        print("No verses available to send")
        return

    for verse in verses:
        message = (f"<b>Daily Quran Verse</b>\n\n"
                  f"<b>{verse['surah_name']} ({verse['surah_number']}:{verse['ayah_number']})</b>\n"
                  f"{verse['arabic_text']}\n\n"
                  f"{verse['translation']}")
        send_telegram_message(message)
        time.sleep(1)  # Small delay between verses

def get_random_verses(count):
    """Get multiple random verses not sent recently"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT id, surah_number, surah_name, ayah_number, arabic_text, translation
            FROM verses
            WHERE (last_sent IS NULL OR last_sent < ?) 
            AND translation != 'Translation not available'
            AND translation != 'No translation available'
            AND translation IS NOT NULL
            AND LENGTH(translation) > 10
            ORDER BY RANDOM()
            LIMIT ?
        """, (cutoff_date, count))

        verses = cursor.fetchall()
        if not verses:
            return None

        # Update last_sent for these verses
        verse_ids = [v[0] for v in verses]
        cursor.executemany(
            "UPDATE verses SET last_sent = ? WHERE id = ?",
            [(datetime.now().strftime("%Y-%m-%d"), vid) for vid in verse_ids]
        )
        conn.commit()

        return [{
            "surah_number": v[1],
            "surah_name": v[2],
            "ayah_number": v[3],
            "arabic_text": v[4],
            "translation": v[5]
        } for v in verses]
    except Exception as e:
        print(f"Error getting random verses: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ======== STORY FUNCTIONS ========

def send_daily_stories():
    """Send daily Prophet stories"""
    stories = get_random_stories(2)
    if not stories:
        print("No stories available to send")
        return

    for story in stories:
        message = (f"<b>{story['title']}</b>\n\n"
                  f"{story['content']}\n\n"
                  f"<i>Source: {story['source']}</i>")
        send_telegram_message(message)
        time.sleep(1)  # Small delay between stories

def get_random_stories(count):
    """Get random stories not sent recently"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT id, title, content, source
            FROM stories
            WHERE last_sent IS NULL OR last_sent < ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (cutoff_date, count))

        stories = cursor.fetchall()
        if not stories:
            return None

        # Update last_sent for these stories
        story_ids = [s[0] for s in stories]
        cursor.executemany(
            "UPDATE stories SET last_sent = ? WHERE id = ?",
            [(datetime.now().strftime("%Y-%m-%d"), sid) for sid in story_ids]
        )
        conn.commit()

        return [{
            "title": s[1],
            "content": s[2],
            "source": s[3]
        } for s in stories]
    except Exception as e:
        print(f"Error getting random stories: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ======== SCHEDULING ========

def run_scheduler():
    """Run the scheduler continuously"""
    while True:
        schedule.run_pending()
        time.sleep(1)

def schedule_daily_tasks():
    """Schedule all daily tasks"""
    # Schedule prayer times refresh at midnight
    schedule.every().day.at("00:01").do(schedule_prayer_reminders)

    # Initial schedule of prayer times
    schedule_prayer_reminders()

    # Schedule daily verses
    schedule.every().day.at(CONFIG['SCHEDULE']['daily_verses_time']).do(send_daily_verses)

    # Schedule daily stories
    schedule.every().day.at(CONFIG['SCHEDULE']['stories_time']).do(send_daily_stories)

# ======== TELEGRAM COMMANDS ========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    # Register the user
    if register_user(chat_id, username, first_name):
        await update.message.reply_text(
            "Assalamu alaikum! Welcome to the Quran Reminder Bot! 🕌\n\n"
            "You are now subscribed to receive:\n"
            "📖 10 Quran verses daily at 8:00 AM\n"
            "📚 2 Prophet stories daily at 6:00 PM\n"
            "🕌 Prayer time reminders with verses\n\n"
            "Commands:\n"
            "/start - Subscribe to messages\n"
            "/stop - Unsubscribe from messages\n"
            "/status - Check your subscription status\n"
            "/quran - Get a random Quran verse with translation\n\n"
            "May Allah bless your journey with the Quran! ❤️",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "There was an error registering you. Please try again later."
        )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command"""
    chat_id = update.effective_chat.id

    if deactivate_user(chat_id):
        await update.message.reply_text(
            "You have been unsubscribed from daily messages.\n"
            "Send /start anytime to subscribe again.\n\n"
            "JazakAllahu khair! 🤲"
        )
    else:
        await update.message.reply_text(
            "There was an error unsubscribing you. Please try again later."
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    chat_id = update.effective_chat.id

    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT is_active, registered_date FROM users WHERE chat_id = ?", (str(chat_id),))
        result = cursor.fetchone()

        if result:
            is_active, reg_date = result
            status_text = "✅ Active" if is_active else "❌ Inactive"
            await update.message.reply_text(
                f"Your subscription status: {status_text}\n"
                f"Registered: {reg_date}\n\n"
                f"Total active users: {len(get_all_active_users())}"
            )
        else:
            await update.message.reply_text(
                "You are not registered. Send /start to subscribe!"
            )
    except Exception as e:
        await update.message.reply_text(
            "Error checking status. Please try again later."
        )
    finally:
        if conn:
            conn.close()

async def test_zuhr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a test Zuhr prayer reminder"""
    verse = get_random_verse()
    if not verse:
        await update.message.reply_text("No verse available for test message")
        return

    message = (f"<b>Dhuhr Reminder</b>\n\n"
               f"<b>{verse['surah_name']} ({verse['surah_number']}:{verse['ayah_number']})</b>\n"
               f"{verse['arabic_text']}\n\n"
               f"{verse['translation']}\n\n"
               "May Allah accept your prayer ❤️")

    await update.message.reply_text(message, parse_mode="HTML")

async def quran(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random Quran verse with translation"""
    verse = get_random_verse()
    if not verse:
        await update.message.reply_text("No verse available at the moment. Please try again later.")
        return

    message = (f"📖 <b>Random Quran Verse</b>\n\n"
               f"<b>{verse['surah_name']} ({verse['surah_number']}:{verse['ayah_number']})</b>\n\n"
               f"{verse['arabic_text']}\n\n"
               f"<i>Translation:</i>\n{verse['translation']}")

    await update.message.reply_text(message, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages for conversational chat"""
    user_message = update.message.text
    chat_id = update.effective_chat.id

    # Auto-register user if they're not registered
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    register_user(chat_id, username, first_name)

    # Get AI response
    ai_response = get_ai_response(user_message)

    # Send response
    await update.message.reply_text(ai_response)

# ======== MAIN APPLICATION ========

def main():
    """Main application entry point"""
    print("Starting Quran Reminder Bot...")

    # Initialize database and data
    init_database()
    populate_quran_data()
    populate_stories()

    # Schedule all tasks
    schedule_daily_tasks()

    # Start scheduler thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Create and run Telegram bot
    application = Application.builder().token(CONFIG['TELEGRAM_BOT_TOKEN']).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("testzuhr", test_zuhr))
    application.add_handler(CommandHandler("quran", quran))

    # Add message handler for conversational chat (non-command messages)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    # Install required packages if not already installed
    os.system("pip install python-telegram-bot==20.3 requests schedule pytz")
    main()