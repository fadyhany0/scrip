from curl_cffi import requests
from bs4 import BeautifulSoup
import json

headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
}
cookies = {"lc-main": "en_EG", "i18n-prefs": "EGP"}
url = "https://www.amazon.eg/-/en/dp/B0GVGGB81B"

r = requests.get(url, headers=headers, cookies=cookies, impersonate="chrome124", timeout=12)
print("status:", r.status_code)
print("len:", len(r.text))
with open("debug_fail.html", "w", encoding="utf-8") as f:
    f.write(r.text)

soup = BeautifulSoup(r.text, "lxml")
print("Title in soup:", soup.title.string if soup.title else None)
print("Has captcha?", "captcha" in r.text.lower())
print("Has robot?", "robot" in r.text.lower())
print("Has productTitle?", bool(soup.find(id="productTitle")))
