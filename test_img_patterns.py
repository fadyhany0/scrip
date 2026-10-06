from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import json

url = "https://www.amazon.eg/dp/B0DH575N5P"
r = requests.get(url, impersonate="chrome124", timeout=12)
html = r.text

print("1. Search for data-a-dynamic-image:")
matches = re.findall(r'data-a-dynamic-image="([^"]+)"', html)
print(f"Found {len(matches)} data-a-dynamic-image occurrences")
for m in matches:
    try:
        data = json.loads(m.replace("&quot;", '"'))
        for u in data.keys():
            print("  dynamic img:", re.sub(r'\._[A-Za-z0-9_]+_\.', '.', u))
    except Exception as e:
        print("err:", e)

print("\n2. Search for hiRes or large in scripts:")
hires_matches = re.findall(r'"hiRes":\s*"([^"]+)"|"large":\s*"([^"]+)"', html)
print(f"Found {len(hires_matches)} hiRes/large occurrences")
for h1, h2 in hires_matches[:5]:
    val = h1 or h2
    print("  hires:", re.sub(r'\._[A-Za-z0-9_]+_\.', '.', val))

print("\n3. Search for ImageBlockATF or colorImages:")
for s in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
    if "ImageBlockATF" in s or "colorImages" in s:
        print("Found script containing ImageBlockATF/colorImages! Length:", len(s))
        # Find JSON array
        m = re.search(r'var data = ({.*?});', s, re.DOTALL)
        if m:
            print("var data matched!")
        else:
            m2 = re.search(r"'colorImages':\s*({.*?});", s, re.DOTALL)
            if m2:
                print("colorImages matched!")
