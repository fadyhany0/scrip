from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import json

url = "https://www.amazon.eg/dp/B0DH575N5P"
r = requests.get(url, impersonate="chrome124", timeout=12)
soup = BeautifulSoup(r.text, "lxml")

print("Status:", r.status_code)
title = soup.find(id="productTitle")
print("Title:", title.get_text(strip=True)[:60] if title else "No title")

# Price
price = None
whole = soup.find("span", class_="a-price-whole")
if whole:
    fraction = soup.find("span", class_="a-price-fraction")
    w = re.sub(r'[^\d]', '', whole.get_text())
    f = re.sub(r'[^\d]', '', fraction.get_text()) if fraction else ""
    price = float(f"{w}.{f}") if f else float(w)
print("Price:", price)

# Images
images = []
match = re.search(r"'colorImages':\s*\{\s*'initial':\s*(\[.*?\])\s*\},", r.text, re.DOTALL)
if match:
    try:
        arr = json.loads(match.group(1))
        for item in arr:
            u = item.get("hiRes") or item.get("large")
            if u:
                # clean to master full-res URL
                clean_u = re.sub(r'\._[A-Za-z0-9_]+_\.', '.', u)
                if clean_u not in images:
                    images.append(clean_u)
    except Exception as e:
        print("JSON err:", e)

print(f"Extracted {len(images)} master HD images:")
for img in images[:4]:
    print(" ", img)
