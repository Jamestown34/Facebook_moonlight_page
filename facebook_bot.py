import os
import requests
import logging
import datetime
import hashlib
import json
import time
import re
import schedule

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ====== ENVIRONMENT VARIABLES ======
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")

POST_LOG = "post_log.json"   # track posted content
DAILY_POST_LIMIT = 3         # Number of posts per day
POST_TIMES = ["07:00", "13:00", "19:00"]  # Scheduled posting times

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
    if today in data and any(p["hash"] == post_hash for p in data[today]):
        return True
    return False

def mark_posted(message, post_number):
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

def count_posts_today():
    today = str(datetime.date.today())
    data = load_log()
    return len(data.get(today, []))

def get_post_themes():
    return [
        "independence movements and freedom fighters",
        "colonial resistance and liberation struggles", 
        "post-independence achievements and challenges",
        "cultural preservation during colonial period",
        "economic developments and trade history",
        "educational and intellectual movements",
        "women's roles in African history",
        "Pan-African movements and unity efforts"
    ]

# ====== TEXT GENERATION WITH GROQ ======
def generate_text(post_number=1):
    themes = get_post_themes()
    selected_theme = themes[(post_number - 1) % len(themes)]
    
    prompt = f"""Write a unique, engaging Facebook post (max 120 words) about African {selected_theme} that happened historically. 
Do NOT include any disclaimers about future dates or uncertainties. 
Structure the text in clear paragraphs for readability and include 2 relevant hashtags."""
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.7
    }

    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # Remove AI disclaimers
        content = re.sub(r"(I think there may be a mistake.*?See more)", "", content, flags=re.DOTALL)
        return content.strip()
    except Exception as e:
        logging.error(f"Error generating text: {e}")
        return None

# ====== IMAGE GENERATION WITH HUGGING FACE ======
HF_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IMAGE_WIDTH = 256   # Smaller image width
IMAGE_HEIGHT = 256  # Smaller image height

def generate_image_hf(prompt):
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {
        "inputs": f"Historical illustration: {prompt}, detailed artwork, educational style, warm colors",
        "options": {
            "wait_for_model": True,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT
        }
    }
    try:
        resp = requests.post(f"https://api-inference.huggingface.co/models/{HF_IMAGE_MODEL}", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content  # raw image bytes
    except Exception as e:
        logging.error(f"Error generating image (HF): {e}")
        return None

# ====== FACEBOOK POSTING ======
def post_to_facebook(message, image_bytes=None, post_number=1):
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
            logging.info(f"✅ Post #{post_number} successful! FB Post ID: {result['id']}")
            return result
        logging.error(f"❌ Post #{post_number} failed: {result}")
        return None
    except Exception as e:
        logging.error(f"Error posting to Facebook (Post #{post_number}): {e}")
        return None

# ====== POST CREATION FUNCTION ======
def create_single_post(post_number):
    logging.info(f"\n🔄 Working on scheduled post #{post_number}...")
    text = None
    for attempt in range(5):
        candidate_text = generate_text(post_number)
        if candidate_text and not already_posted(candidate_text):
            sentences = candidate_text.split(". ")
            text = "\n\n".join([s.strip() for s in sentences if s.strip()])
            text += "\n\nDrop your thoughts in the comments and follow us for more historical insights!"
            break
        time.sleep(1)
    if not text:
        logging.error(f"❌ Could not generate unique content for post #{post_number}")
        return

    image_bytes = generate_image_hf(text[:120])
    result = post_to_facebook(text, image_bytes, post_number)
    if result:
        mark_posted(text, post_number)
        logging.info(f"✅ Scheduled post #{post_number} completed successfully!")

# ====== SCHEDULING POSTS ======
def schedule_posts():
    posts_today = count_posts_today()
    remaining_posts = DAILY_POST_LIMIT - posts_today
    if remaining_posts <= 0:
        logging.info(f"✅ Already posted {DAILY_POST_LIMIT} times today.")
        return

    for i, post_time in enumerate(POST_TIMES[:remaining_posts], 1):
        schedule.every().day.at(post_time).do(create_single_post, post_number=posts_today + i)
        logging.info(f"⏰ Scheduled post #{posts_today + i} for {post_time}")

    logging.info("🕒 Bot is now running and waiting for scheduled post times...")
    while True:
        schedule.run_pending()
        time.sleep(10)  # check every 10 seconds

# ====== STATUS ======
def show_status():
    today = str(datetime.date.today())
    posts_today = count_posts_today()
    data = load_log()
    print(f"\n📊 DAILY STATUS FOR {today}")
    print(f"Posts made today: {posts_today}/{DAILY_POST_LIMIT}")
    if today in data:
        for i, post in enumerate(data[today], 1):
            timestamp = post.get('timestamp', 'Unknown')
            preview = post.get('preview', 'No preview')
            print(f"{i}. {timestamp[:19]} - {preview}")

# ====== MAIN ======
if __name__ == "__main__":
    required_vars = ["FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID", "GROQ_API_KEY", "HF_TOKEN"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logging.error(f"❌ Missing env vars: {', '.join(missing_vars)}")
        exit(1)

    show_status()
    schedule_posts()
