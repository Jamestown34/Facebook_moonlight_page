import os
import requests
import random
import logging
import schedule
import time
from datetime import datetime

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === ENVIRONMENT VARIABLES (your naming) ===
HUGGINGFACE_API_KEY = os.getenv("HF_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")
PAGE_ID = os.getenv("FB_PAGE_ID")

# === CONSTANTS ===
WIKI_API = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events"
MISTRAL_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"
SD_MODEL = "runwayml/stable-diffusion-v1-5"


class HistoryFetcher:
    """Fetch and filter African historical events."""
    @staticmethod
    def get_events():
        today = datetime.utcnow()
        url = f"{WIKI_API}/{today.month}/{today.day}"
        logging.info(f"Fetching events from: {url}")
        resp = requests.get(url)
        if resp.status_code != 200:
            logging.error("Wikipedia API failed")
            return []

        events = resp.json().get("events", [])
        # Filter: only Africa / colonial / independence events
        keywords = ["Africa", "Nigerian", "Ghana", "Kenya", "colonial", "independence",
                    "Mandela", "Apartheid", "Pan-African", "Congo", "Ethiopia", "Sudan"]
        filtered = [
            e for e in events
            if any(kw.lower() in (e.get("text", "") + str(e.get("pages", ""))).lower() for kw in keywords)
        ]
        return filtered


class ContentGenerator:
    """Generate text and images with Hugging Face APIs."""
    @staticmethod
    def generate_text(event_text):
        headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
        payload = {"inputs": f"Write a short engaging Facebook post about this African history event:\n{event_text}"}
        resp = requests.post(f"https://api-inference.huggingface.co/models/{MISTRAL_MODEL}",
                             headers=headers, json=payload)
        if resp.status_code != 200:
            logging.error(f"HuggingFace text generation failed: {resp.text}")
            return event_text
        return resp.json()[0]["generated_text"]

    @staticmethod
    def generate_image(prompt):
        headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
        resp = requests.post(f"https://api-inference.huggingface.co/models/{SD_MODEL}",
                             headers=headers, json={"inputs": prompt})
        if resp.status_code != 200:
            logging.error(f"HuggingFace image generation failed: {resp.text}")
            return None
        return resp.content  # raw image bytes


class FacebookBot:
    """Handles posting content to Facebook Page."""
    @staticmethod
    def post_with_image(message, image_bytes):
        url = f"https://graph.facebook.com/v23.0/{PAGE_ID}/photos"
        files = {"source": ("image.jpg", image_bytes, "image/jpeg")}
        data = {"caption": message, "access_token": PAGE_ACCESS_TOKEN}
        resp = requests.post(url, files=files, data=data)
        if resp.status_code == 200:
            logging.info("✅ Successfully posted image + text to Facebook")
        else:
            logging.error(f"Facebook image post failed: {resp.text}")


def make_post():
    logging.info("📌 Starting new scheduled post...")

    events = HistoryFetcher.get_events()
    if not events:
        logging.warning("No African events found today.")
        return

    event = random.choice(events)  # Pick 1 random event
    event_text = event.get("text", "An African history event.")
    logging.info(f"Selected event: {event_text}")

    post_text = ContentGenerator.generate_text(event_text)

    # Always generate an image
    image_bytes = ContentGenerator.generate_image(event_text)
    if not image_bytes:
        logging.warning("Image generation failed, retrying once...")
        image_bytes = ContentGenerator.generate_image(event_text)

    if image_bytes:
        FacebookBot.post_with_image(post_text, image_bytes)
    else:
        logging.error("❌ Skipping post because image could not be generated.")


def main():
    # Schedule 3 posts daily
    schedule.every().day.at("09:00").do(make_post)
    schedule.every().day.at("13:00").do(make_post)
    schedule.every().day.at("18:00").do(make_post)

    logging.info("🚀 Facebook History Bot started...")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
