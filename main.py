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

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""


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


def wait_for_cloudflare(page):
    for step in range(8):
        body = page.inner_text("body") or ""
        if (
            "보안 확인 수행 중" not in body
            and "잠시만 기다리십시오" not in body
            and "Checking your browser" not in body
            and "Just a moment" not in body
        ):
            return True
        page.mouse.move(200 + step * 35, 300 + (step % 3) * 20)
        page.wait_for_timeout(3000)
    return False


def extract_coupang_url(page, detail_url):
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=25000)
        wait_for_cloudflare(page)
        page.wait_for_timeout(2000)
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
    is_first_run = len(sent_urls) == 0
    new_sent = list(sent_urls)
    debug_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1366,768",
                "--lang=ko-KR",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1366, "height": 768},
        )
        context.add_init_script(STEALTH_SCRIPT)
        page = context.new_page()

        candidates = []

        for category, url in TARGETS:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            passed = wait_for_cloudflare(page)
            page.wait_for_timeout(3000)
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1500)

            anchors = page.locator("a").all()
            body_sample = re.sub(r"\s+", " ", page.inner_text("body") or "")[:120]
            debug_info.append(f"[{category}] 통과:{passed} / 링크수:{len(anchors)} / 화면:{body_sample}")

            for a in anchors:
                href = a.get_attribute("href") or ""
                text = (a.inner_text() or "").strip()
                html = (a.inner_html() or "").lower()

                if not href or not text:
                    continue

                clean_href = href.replace("https://hotdeal.zip", "")
                if clean_href in [
                    "", "/", "/식품", "/생활용품", "/인기", "/쿠팡최저가",
                    "/%EC%8B%9D%ED%92%88", "/%EC%83%9D%ED%99%9C%EC%9A%A9%ED%92%88",
                ]:
                    continue
                if any(skip in href for skip in ["/search", "/login", "/notice", "/terms", "/privacy"]):
                    continue
                if href.startswith("http") and "hotdeal.zip" not in href:
                    continue

                if ("쿠팡" not in text) and ("쿠팡" not in html) and ("coupang" not in html):
                    continue

                full_detail_url = (
                    href if href.startswith("http")
                    else f"https://hotdeal.zip{href if href.startswith('/') else '/' + href}"
                )
                if full_detail_url in new_sent:
                    continue

                lines = [line.strip() for line in text.splitlines() if line.strip()]
                price_match = re.search(r"(\d[\d,]*원~?|다양)", text)
                price = price_match.group(1) if price_match else "가격 정보 없음"
                title = lines[0] if lines else text[:60]

                candidates.append((category, title, price, full_detail_url))
                new_sent.append(full_detail_url)

        if is_first_run and len(candidates) > 5:
            candidates = candidates[:5]

        if candidates:
            for category, title, price, detail_url in reversed(candidates):
                origin_url = extract_coupang_url(page, detail_url)
                message = f"[{category}] {title}\n가격: {price}\n{origin_url}"
                send_telegram(message)
                time.sleep(1)
        elif is_first_run:
            diag_msg = (
                "⚠️ 일반 크롬 위장 모드로 접속했으나 아직 목록을 가져오지 못했습니다.\n\n"
                + "\n".join(debug_info)
            )
            send_telegram(diag_msg)

        browser.close()

    save_history(new_sent)


if __name__ == "__main__":
    main()
