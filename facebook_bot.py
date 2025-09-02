import os
import requests
import logging
import datetime
import hashlib
import json
import random
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ====== ENVIRONMENT VARIABLES ======
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

POST_LOG = "post_log.json"
DAILY_POST_LIMIT = 3
HF_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IMAGE_WIDTH = 512
IMAGE_HEIGHT = 512

# ====== GOOGLE SHEETS SETUP ======
SHEET_ID = "1NvNUmFQ_p5rf5uoTnwywtsYFDuKcTZFx0kE66msLsmE"  # replace with your sheet ID
SHEET_NAME = "FB_Bot_Memory"

creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
sheets_service = build("sheets", "v4", credentials=creds)
sheet = sheets_service.spreadsheets()

# ====== HELPERS ======
def load_log():
    if os.path.exists(POST_LOG):
        with open(POST_LOG, "r") as f:
            return json.load(f)
    return {}

def save_log(data):
    with open(POST_LOG, "w") as f:
        json.dump(data, f, indent=2)

def already_posted_topic(topic):
    """Check Google Sheet for last 2 days to avoid repeating topics"""
    today = datetime.date.today()
    two_days_ago = today - datetime.timedelta(days=2)
    result = sheet.values().get(spreadsheetId=SHEET_ID, range=SHEET_NAME).execute()
    rows = result.get("values", [])
    for row in rows[1:]:  # skip header
        try:
            date_str, sheet_topic = row[0], row[1]
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            if sheet_topic == topic and date_obj >= two_days_ago:
                return True
        except:
            continue
    return False

def record_post_in_sheet(date, topic, text, post_number, fb_post_id):
    values = [[date, topic, text, str(post_number), str(fb_post_id)]]
    sheet.values().append(
        spreadsheetId=SHEET_ID,
        range=SHEET_NAME,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()

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
def generate_text(topic):
    style = random.choice(get_post_styles()).format(topic=topic)
    prompt = (
        f"Write a unique, engaging Facebook post (max 120 words) about African {topic}. "
        f"{style} "
        f"Do NOT include disclaimers or future predictions. Include 2 relevant hashtags."
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
        return content.strip()
    except Exception as e:
        logging.error(f"Error generating text: {e}")
        return None

# ====== IMAGE GENERATION ======
def generate_image_hf(topic, style):
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    prompt = f"Realistic historical illustration of African {topic}, inspired by '{style}', high detail, photo-realistic"
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
        return r.json().get("id")
    except Exception as e:
        logging.error(f"Error posting to Facebook: {e}")
        return None

# ====== MAIN LOGIC ======
if __name__ == "__main__":
    required_vars = ["FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID", "GROQ_API_KEY", "HF_TOKEN", "GOOGLE_CREDS_JSON"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logging.error(f"❌ Missing env vars: {', '.join(missing_vars)}")
        exit(1)

    themes = get_post_themes()
    random.shuffle(themes)

    posts_made = 0
    for topic in themes:
        if posts_made >= DAILY_POST_LIMIT:
            break
        if not already_posted_topic(topic):
            text = generate_text(topic)
            if not text:
                continue
            image_bytes = generate_image_hf(topic, text[:50])
            fb_post_id = post_to_facebook(text, image_bytes)
            if fb_post_id:
                record_post_in_sheet(str(datetime.date.today()), topic, text, posts_made+1, fb_post_id)
                posts_made += 1
                logging.info(f"✅ Post #{posts_made} done: {topic}")
