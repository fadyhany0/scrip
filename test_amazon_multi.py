from curl_cffi import requests
from bs4 import BeautifulSoup
import re

test_products = [
    ("Egypt iPhone", "https://www.amazon.eg/-/en/dp/B0CHWXZ8Q2"),
    ("Egypt Anker Charger", "https://www.amazon.eg/-/en/dp/B07PWC32BW"),
    ("Saudi Samsung", "https://www.amazon.sa/-/en/dp/B0CRDBZCR1"),
    ("UAE Sony", "https://www.amazon.ae/-/en/dp/B0863TXGM3"),
]

for label, url in test_products:
    try:
        r = requests.get(url, impersonate="chrome124", timeout=10)
        print(f"[{label}] Status: {r.status_code}, Length: {len(r.text)}")
        soup = BeautifulSoup(r.text, "lxml")
        title = soup.find(id="productTitle")
        t_text = title.get_text(strip=True)[:50] if title else "NO TITLE"
        print(f"  Title: {t_text}")
    except Exception as e:
        print(f"[{label}] Error: {e}")
