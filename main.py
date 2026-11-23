import json
import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
HISTORY_FILE = "sent_deals.json"

TARGETS = [
    ("식품", "https://hotdeal.zip/%EC%8B%9D%ED%92%88"),
    ("생활용품", "https://hotdeal.zip/%EC%83%9D%ED%99%9C%EC%9A%A9%ED%92%88"),
]


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-500:], f, ensure_ascii=False, indent=2)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    res = requests.post(url, json=payload, timeout=10)
    res.raise_for_status()


def extract_coupang_url(page, detail_url):
    try:
        page.goto(detail_url, wait_until="networkidle", timeout=15000)
        links = page.locator("a[href*='coupang.com']").all()
        for link in links:
            href = link.get_attribute("href")
            if href and "coupang.com" in href:
                return href.split("?")[0]
    except Exception:
        pass
    return detail_url


def main():
    sent_urls = load_history()
    new_sent = list(sent_urls)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        candidates = []

        for category, url in TARGETS:
            page.goto(url, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            anchors = page.locator("a[href^='/']").all()
            for a in anchors:
                href = a.get_attribute("href") or ""
                text = (a.inner_text() or "").strip()

                if not text or "쿠팡" not in text:
                    continue
                if any(skip in href for skip in ["/search", "/login", "/notice", "/terms", "/privacy"]):
                    continue

                full_detail_url = f"https://hotdeal.zip{href}"
                if full_detail_url in new_sent:
                    continue

                lines = [line.strip() for line in text.splitlines() if line.strip()]
                price_match = re.search(r"(\d[\d,]*원~?|다양)", text)
                price = price_match.group(1) if price_match else "가격 정보 없음"
                title = lines[0] if lines else text[:60]

                candidates.append((category, title, price, full_detail_url))
                new_sent.append(full_detail_url)

        for category, title, price, detail_url in reversed(candidates):
            origin_url = extract_coupang_url(page, detail_url)
            message = f"[{category}] {title}\n가격: {price}\n{origin_url}"
            send_telegram(message)
            time.sleep(1)

        browser.close()

    save_history(new_sent)


if __name__ == "__main__":
    main()
