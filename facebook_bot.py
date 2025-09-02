import os
import requests
import logging
import datetime
import hashlib
import json
import time
import re
import random
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

HF_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IMAGE_WIDTH = 512
IMAGE_HEIGHT = 512

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

# ====== TEXT GENERATION WITH GROQ ======
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
        "model": "llama3-8b-8192",
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

# ====== IMAGE GENERATION WITH HUGGING FACE ======
def generate_image_hf(text_snippet, topic, style):
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    prompt = (
        f"Realistic historical illustration of African {topic}, inspired by '{style}', "
        f"high detail, cinematic lighting, photo-realistic, educational style"
    )
    payload = {
        "inputs": prompt,
        "options": {"wait_for_model": True, "width": IMAGE_WIDTH, "height": IMAGE_HEIGHT}
    }
    try:
        resp = requests.post(f"https://api-inference.huggingface.co/models/{HF_IMAGE_MODEL}", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logging.error(f"Error generating image: {e}")
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
    text, topic, style = None, None, None

    for attempt in range(5):
        candidate_text, topic, style = generate_text(post_number)
        if candidate_text and not already_posted(candidate_text):
            sentences = candidate_text.split(". ")
            text = "\n\n".join([s.strip() for s in sentences if s.strip()])
            text += "\n\nDrop your thoughts in the comments and follow us for more historical insights!"
            break
        time.sleep(1)

    if not text:
        logging.error(f"❌ Could not generate unique content for post #{post_number}")
        return

    image_bytes = generate_image_hf(text[:120], topic, style)
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
        time.sleep(10)

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
