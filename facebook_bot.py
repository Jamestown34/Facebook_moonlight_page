import os
import requests
import logging
import datetime
import hashlib
import json
import time
import random

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Env vars
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY")

POST_LOG = "post_log.json"   # keep track of what was posted today
DAILY_POST_LIMIT = 3  # Number of posts per day

# =============== HELPERS =====================
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

    if today in data and post_hash in data[today]:
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
    """Different themes to ensure variety in daily posts"""
    themes = [
        "independence movements and freedom fighters",
        "colonial resistance and liberation struggles", 
        "post-independence achievements and challenges",
        "cultural preservation during colonial period",
        "economic developments and trade history",
        "educational and intellectual movements",
        "women's roles in African history",
        "Pan-African movements and unity efforts"
    ]
    return themes

# =============== AI TEXT WITH GROQ =====================
def generate_text(post_number=1):
    today = datetime.date.today().strftime("%B %d, %Y")
    themes = get_post_themes()
    selected_theme = themes[(post_number - 1) % len(themes)]
    
    # Different prompts for variety
    prompts = [
        f"Write a short post (max 120 words) about an important event in African {selected_theme} that happened on {today}. Focus on lesser-known but significant stories. Make it engaging and educational. End with 2 relevant hashtags.",
        
        f"Create an informative post (max 120 words) highlighting African {selected_theme} connected to {today} in history. Include specific names, places, or movements. Write for a general audience interested in African heritage. End with 2 relevant hashtags.",
        
        f"Compose a compelling post (max 120 words) about {selected_theme} in African history tied to {today}. Share inspiring stories of resilience and achievement. Make it accessible and thought-provoking. End with 2 relevant hashtags."
    ]
    
    selected_prompt = prompts[(post_number - 1) % len(prompts)]
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama-3.1-70b-versatile",
        "messages": [
            {"role": "system", "content": f"You are an expert African history writer for a Facebook page. Create unique, engaging content that educates about African colonial and post-colonial history. Always tie events to specific dates when possible. Post #{post_number} of 3 daily posts - make it distinct from the others."},
            {"role": "user", "content": selected_prompt}
        ],
        "max_tokens": 300,
        "temperature": 0.8  # Add some randomness for variety
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"Error generating text: {e}")
        return None

# =============== IMAGE WITH REPLICATE =====================
def generate_image(prompt):
    url = "https://api.replicate.com/v1/predictions"
    headers = {"Authorization": f"Token {REPLICATE_API_KEY}", "Content-Type": "application/json"}
    
    # Create a focused image prompt
    image_prompt = f"Historical illustration of African colonial or post-colonial history: {prompt[:100]}, detailed artwork, educational style, warm colors"
    
    data = {
        "version": "stability-ai/stable-diffusion:27b93a2413e7f36cd83da926f3656280b2931564ff050bf9575f1fdf9bcd7478",
        "input": {
            "prompt": image_prompt,
            "image_dimensions": "512x512",
            "num_outputs": 1,
            "guidance_scale": 7.5,
            "num_inference_steps": 20
        }
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        prediction = resp.json()
        prediction_url = prediction["urls"]["get"]

        # Poll for completion
        max_attempts = 30
        for attempt in range(max_attempts):
            result = requests.get(prediction_url, headers=headers)
            result.raise_for_status()
            result_data = result.json()
            
            if result_data["status"] == "succeeded":
                return result_data["output"][0] if result_data["output"] else None
            elif result_data["status"] == "failed":
                logging.error(f"Image generation failed: {result_data.get('error', 'Unknown error')}")
                return None
            
            time.sleep(3)
        
        logging.warning("Image generation timed out")
        return None
    except Exception as e:
        logging.error(f"Error generating image: {e}")
        return None

# =============== POST TO FACEBOOK =====================
def post_to_facebook(message, image_url=None, post_number=1):
    try:
        if image_url:
            # Post with image
            fb_url = f"https://graph.facebook.com/{FB_PAGE_ID}/photos"
            payload = {
                "caption": message,
                "url": image_url,
                "access_token": FB_PAGE_ACCESS_TOKEN
            }
        else:
            # Text-only post
            fb_url = f"https://graph.facebook.com/{FB_PAGE_ID}/feed"
            payload = {
                "message": message,
                "access_token": FB_PAGE_ACCESS_TOKEN
            }
        
        r = requests.post(fb_url, data=payload)
        r.raise_for_status()
        result = r.json()
        
        if 'id' in result:
            logging.info(f"✅ Post #{post_number} successful! FB Post ID: {result['id']}")
            return result
        else:
            logging.error(f"❌ Post #{post_number} failed: {result}")
            return None
            
    except Exception as e:
        logging.error(f"Error posting to Facebook (Post #{post_number}): {e}")
        return None

# =============== MAIN POSTING FUNCTION =====================
def create_daily_posts():
    posts_today = count_posts_today()
    remaining_posts = DAILY_POST_LIMIT - posts_today
    
    if remaining_posts <= 0:
        logging.info(f"✅ Already posted {DAILY_POST_LIMIT} times today. All done!")
        return
    
    logging.info(f"📝 Creating {remaining_posts} post(s) for today...")
    
    successful_posts = 0
    
    for post_num in range(posts_today + 1, DAILY_POST_LIMIT + 1):
        logging.info(f"\n🔄 Working on post #{post_num}...")
        
        # Try to generate unique content (up to 5 attempts)
        text = None
        for attempt in range(5):
            candidate_text = generate_text(post_num)
            if candidate_text and not already_posted(candidate_text):
                text = candidate_text
                break
            else:
                logging.info(f"🔁 Post #{post_num} - Attempt {attempt + 1}: Duplicate or error, regenerating...")
                time.sleep(2)  # Brief pause between attempts
        
        if not text:
            logging.error(f"❌ Could not generate unique content for post #{post_num}")
            continue
        
        # Generate image (optional - will post text-only if image fails)
        image_url = generate_image(text[:120])
        if not image_url:
            logging.warning(f"⚠️ No image for post #{post_num}, posting text only")
        
        # Post to Facebook
        result = post_to_facebook(text, image_url, post_num)
        if result:
            mark_posted(text, post_num)
            successful_posts += 1
            logging.info(f"✅ Post #{post_num} completed successfully!")
            
            # Add delay between posts to avoid rate limiting
            if post_num < DAILY_POST_LIMIT:
                logging.info("⏳ Waiting 30 seconds before next post...")
                time.sleep(30)
        else:
            logging.error(f"❌ Failed to post #{post_num}")
    
    logging.info(f"\n🎉 Daily posting complete! Successfully posted {successful_posts} out of {remaining_posts} planned posts.")

# =============== STATUS CHECK =====================
def show_status():
    today = str(datetime.date.today())
    posts_today = count_posts_today()
    data = load_log()
    
    print(f"\n📊 DAILY STATUS FOR {today}")
    print(f"Posts made today: {posts_today}/{DAILY_POST_LIMIT}")
    
    if today in data:
        print("\n📝 Today's Posts:")
        for i, post in enumerate(data[today], 1):
            timestamp = post.get('timestamp', 'Unknown time')
            preview = post.get('preview', 'No preview available')
            print(f"  {i}. {timestamp[:19]} - {preview}")
    
    remaining = DAILY_POST_LIMIT - posts_today
    if remaining > 0:
        print(f"\n⏳ {remaining} more post(s) needed today")
    else:
        print(f"\n✅ All daily posts complete!")

# =============== MAIN =====================
if __name__ == "__main__":
    # Check if we have required environment variables
    required_vars = ["FB_PAGE_ACCESS_TOKEN", "FB_PAGE_ID", "GROQ_API_KEY", "REPLICATE_API_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logging.error(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        exit(1)
    
    # Show current status
    show_status()
    
    # Create daily posts
    create_daily_posts()
