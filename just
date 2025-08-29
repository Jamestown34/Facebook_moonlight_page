import requests
import os

# Load values from environment (GitHub Secrets)
PAGE_ID = os.getenv("FB_PAGE_ID")
ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")

def post_to_facebook(message):
    url = f"https://graph.facebook.com/v23.0/{PAGE_ID}/feed"
    payload = {
        "message": message,
        "access_token": ACCESS_TOKEN
    }
    response = requests.post(url, data=payload)
    print(response.json())

if __name__ == "__main__":
    post_to_facebook("🚀 Automated post from GitHub Actions!")
