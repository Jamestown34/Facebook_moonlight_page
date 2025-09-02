import os
import requests
import logging
import datetime
import json
import random
import re
import gspread
from dateutil import parser
from google.oauth2.service_account import Credentials

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ====== ENVIRONMENT VARIABLES ======
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

# If you prefer an env var, set SHEET_ID in GitHub Secrets and replace the line below.
SHEET_ID = "1NvNUmFQ_p5rf5uoTnwywtsYFDuKcTZFx0kE66msLsmE"  # <- your sheet id

# ====== CONFIG ======
DAILY_POST_LIMIT = 3
HF_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IMAGE_WIDTH = 512
IMAGE_HEIGHT = 512
WORKSHEET_NAME = "FB_Bot_Memory"

# ====== GOOGLE SHEETS SETUP ======
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)

# ====== SHEET LOGGING ======
def mark_posted(message, post_number, topic, fb_post_id=None):
    """Append a log row: [YYYY-MM-DD, Topic, Message, PostNumber, FBPostID]"""
    today = datetime.date.today().isoformat()  # ISO format always
    sheet = get_sheet()
    sheet.append_row([today, topic, message, post_number, fb_post_id or ""])

def count_posts_today():
    """Count how many rows in the sheet have today's ISO date."""
    sheet = get_sheet()
    today = datetime.date.today().isoformat()
    rows = sheet.get_all_values()[1:]  # skip header
    return sum(1 for row in rows if row and len(row) > 0 and row[0] == today)

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
        "African wildlife and national parks",
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
        "Explain {topic} in a practical context for readers today.",
    ]

# ====== TEXT GENERATION (Groq) ======
def generate_text(topic, post_number=1):
    styles = get_post_styles()
    selected_style = random.choice(styles).format(topic=topic)

    prompt = (
        f"Write a unique, engaging Facebook post (max 120 words) about {topic}. "
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
        "top_p": 0.9,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # strip any unwanted boilerplate if providers inject it
        content = re.sub(r"(I think there may be a mistake.*?See more)", "", content, flags=re.DOTALL)
        return content.strip(), topic, selected_style
    except Exception as e:
        logging.error(f"Error generating text: {e}")
        return None, topic, selected_style

# ====== IMAGE GENERATION (Hugging Face) ======
def generate_image_hf(topic, style):
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    prompt = (
        f"Realistic historical illustration of {topic}, inspired by '{style}', "
        f"high detail, cinematic lighting, photo-realistic, educational style"
    )
    payload = {
        "inputs": prompt,
        "options": {"wait_for_model": True, "width": IMAGE_WIDTH, "height": IMAGE_HEIGHT},
    }
    try:
        resp = requests.post(
            f"https://api-inference.huggingface.co/models/{HF_IMAGE_MODEL}",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content  # bytes
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
            r = requests.post(fb_url, data=payload, files=files, timeout=60)
        else:
            fb_url = f"https://graph.facebook.com/{FB_PAGE_ID}/feed"
            payload = {"message": message, "access_token": FB_PAGE_ACCESS_TOKEN}
            r = requests.post(fb_url, data=payload, timeout=60)

        r.raise_for_status()
        result = r.json()
        if "id" in result:
            logging.info(f"✅ Post successful! FB Post ID: {result['id']}")
            return result["id"]
        logging.error(f"❌ Post failed: {result}")
        return None
    except Exception as e:
        logging.error(f"Error posting to Facebook: {e}")
        return None

# ====== CHECK RECENT TOPICS (avoid repeats) ======
def already_posted_topic(topic):
    """Avoid reposting same topic within the last 2 days (robust date parsing, skip header)."""
    sheet = get_sheet()
    rows = sheet.get_all_values()[1:]  # skip header
    today = datetime.date.today()
    two_days_ago = today - datetime.timedelta(days=2)

    for row in rows:
        if len(row) < 2:
            continue
        try:
            post_date = parser.parse(row[0]).date()
        except Exception:
            continue
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
    return random.choice(themes)  # fallback

# ====== MAIN (single post per run; GitHub Actions cron controls timing) ======
if __name__ == "__main__":
    required_vars = ["FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID", "GROQ_API_KEY", "HF_TOKEN", "GOOGLE_CREDS_JSON"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logging.error(f"❌ Missing env vars: {', '.join(missing_vars)}")
        raise SystemExit(1)

    # Make exactly ONE post per run; rely on Actions cron (e.g., 07:00, 13:00, 19:00 UTC)
    posts_today = count_posts_today()
    if posts_today >= DAILY_POST_LIMIT:
        logging.info(f"✅ Already posted {DAILY_POST_LIMIT} times today. Exiting.")
        raise SystemExit(0)

    post_number = posts_today + 1
    topic = pick_topic_for_today()
    text, topic, style = generate_text(topic, post_number)

    if text:
        image_bytes = generate_image_hf(topic, style)
        fb_post_id = post_to_facebook(text, image_bytes)
        if fb_post_id:
            mark_posted(text, post_number, topic, fb_post_id)
            logging.info(f"✅ Post #{post_number} completed successfully!")
    else:
        logging.error(f"❌ Could not generate text for post #{post_number}.")
