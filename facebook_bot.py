import os
import requests
import logging
import datetime
import hashlib
import json
import time
import re
import random
import gspread
from google.oauth2.service_account import Credentials

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ====== ENVIRONMENT VARIABLES ======
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SHEET_ID = "1NvNUmFQ_p5rf5uoTnwywtsYFDuKcTZFx0kE66msLsmE"
SHEET_RANGE = "FB_Bot_Memory!A:E"

POST_LOG = "post_log.json"
DAILY_POST_LIMIT = 3
HF_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IMAGE_WIDTH = 512
IMAGE_HEIGHT = 512

# ====== GOOGLE SHEETS SETUP ======
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet("FB_Bot_Memory")
    return sheet

# ====== HELPERS ======
def load_log():
    if os.path.exists(POST_LOG):
        with open(POST_LOG, "r") as f:
            return json.load(f)
    return {}

def save_log(data):
    with open(POST_LOG, "w") as f:
        json.dump(data, f, indent=2)

def already_posted(message):
    today = str(datetime.date.today())
    data = load_log()
    post_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return today in data and any(p["hash"] == post_hash for p in data[today])

def mark_posted(message, post_number, topic, fb_post_id=None):
    today = str(datetime.date.today())
    data = load_log()
    post_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if today not in data:
        data[today] = []
    data[today].append({
        "hash": post_hash,
        "post_number": post_number,
        "timestamp": datetime.datetime.now().isoformat(),
        "preview": message[:100] + "..." if len(message) > 100 else message
    })
    save_log(data)

    # Also write to Google Sheets
    sheet = get_sheet()
    sheet.append_row([today, topic, message, post_number, fb_post_id or ""])

def count_posts_today():
    today = str(datetime.date.today())
    data = load_log()
    return len(data.get(today, []))

# ====== TOPICS & STYLES ======
def get_post_themes():
    return [
        "African fashion trends and designers",
        "African innovations and technology breakthroughs",
        "Stories of everyday life in different African countries",
        "Economic developments and trade history",
        "Modern African leaders and diplomacy",
        "African cuisine and traditional recipes",
        "Educational and intellectual movements",
        "African sports achievements and history",
        "Cultural preservation during colonial period",
        "African languages and linguistic diversity",
        "Travel and tourism destinations in Africa",
        "Notable African scientists and inventors",
        "Women’s roles in African history",
        "Environmental conservation in Africa",
        "Festivals, rituals, and cultural celebrations",
        "Health initiatives and medical breakthroughs",
        "Community projects and social impact initiatives",
        "Emerging African entrepreneurs and startups",
        "Post-independence achievements and challenges",
        "Tech hubs and innovation centers across Africa",
        "African art, music, and literature",
        "African wildlife and national parks"
    ]

def get_post_styles():
    return [
        "Share an inspiring story about {topic} that everyone can learn from.",
        "Highlight the historical significance of {topic}.",
        "Explain {topic} in a way that educates and engages readers.",
        "Tell a little-known fact about {topic}.",
        "Discuss how {topic} shaped African history and culture.",
        "Celebrate achievements in {topic} and their lasting impact.",
        "Provide an interesting anecdote about {topic}.",
        "Showcase the people behind {topic} and their contributions.",
        "Explain {topic} in a practical context for readers today."
    ]

# ====== TEXT GENERATION ======
def generate_text(post_number=1):
    themes = get_post_themes()
    selected_theme = themes[(post_number - 1) % len(themes)]
    styles = get_post_styles()
    selected_style = random.choice(styles).format(topic=selected_theme)

    prompt = (
        f"Write a unique, engaging Facebook post (max 120 words) about African {selected_theme}. "
        f"{selected_style} "
        f"Do NOT include any disclaimers about future dates or uncertainties. "
        f"Structure the text in clear paragraphs and include 2 relevant hashtags."
    )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.7,
        "top_p": 0.9
    }

    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = re.sub(r"(I think there may be a mistake.*?See more)", "", content, flags=re.DOTALL)
        return content.strip(), selected_theme, selected_style
    except Exception as e:
        logging.error(f"Error generating text: {e}")
        return None, selected_theme, selected_style

# ====== IMAGE GENERATION ======
def generate_image_hf(topic, style):
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    prompt = (
        f"Realistic historical illustration of African {topic}, inspired by '{style}', "
        f"high detail, cinematic lighting, photo-realistic, educational style"
    )
    payload = {"inputs": prompt, "options": {"wait_for_model": True, "width": IMAGE_WIDTH, "height": IMAGE_HEIGHT}}
    try:
        resp = requests.post(f"https://api-inference.huggingface.co/models/{HF_IMAGE_MODEL}", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logging.error(f"Error generating image: {e}")
        return None

# ====== FACEBOOK POST ======
def post_to_facebook(message, image_bytes=None):
    try:
        if image_bytes:
            fb_url = f"https://graph.facebook.com/{FB_PAGE_ID}/photos"
            files = {"source": ("image.png", image_bytes, "image/png")}
            payload = {"caption": message, "access_token": FB_PAGE_ACCESS_TOKEN}
            r = requests.post(fb_url, data=payload, files=files)
        else:
            fb_url = f"https://graph.facebook.com/{FB_PAGE_ID}/feed"
            payload = {"message": message, "access_token": FB_PAGE_ACCESS_TOKEN}
            r = requests.post(fb_url, data=payload)

        r.raise_for_status()
        result = r.json()
        if 'id' in result:
            logging.info(f"✅ Post successful! FB Post ID: {result['id']}")
            return result['id']
        logging.error(f"❌ Post failed: {result}")
        return None
    except Exception as e:
        logging.error(f"Error posting to Facebook: {e}")
        return None

# ====== CHECK LAST 2 DAYS TOPICS ======
def already_posted_topic(topic):
    sheet = get_sheet()
    rows = sheet.get_all_values()
    today = datetime.date.today()
    two_days_ago = today - datetime.timedelta(days=2)
    for row in rows:
        if len(row) < 2:
            continue
        post_date = datetime.datetime.strptime(row[0], "%Y-%m-%d").date()
        posted_topic = row[1]
        if post_date >= two_days_ago and posted_topic == topic:
            return True
    return False

def pick_topic_for_today():
    themes = get_post_themes()
    random.shuffle(themes)
    for t in themes:
        if not already_posted_topic(t):
            return t
    return random.choice(themes)  # fallback if all were used

# ====== MAIN POST CREATION ======
if __name__ == "__main__":
    required_vars = ["FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID", "GROQ_API_KEY", "HF_TOKEN", "GOOGLE_CREDS_JSON"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logging.error(f"❌ Missing env vars: {', '.join(missing_vars)}")
        exit(1)

    posts_today = count_posts_today()
    if posts_today >= DAILY_POST_LIMIT:
        logging.info(f"✅ Already posted {DAILY_POST_LIMIT} times today.")
        exit(0)

    for post_number in range(posts_today + 1, DAILY_POST_LIMIT + 1):
        topic = pick_topic_for_today()
        text, _, style = generate_text(post_number)
        if text:
            image_bytes = generate_image_hf(topic, style)
            fb_post_id = post_to_facebook(text, image_bytes)
            if fb_post_id:
                mark_posted(text, post_number, topic, fb_post_id)
                logging.info(f"✅ Post #{post_number} completed successfully!")
        else:
            logging.error(f"❌ Could not generate text for post #{post_number}.")
