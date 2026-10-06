from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import re

url = "https://www.amazon.eg/-/en/dp/B0BDHWDR12"
headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9,ar;q=0.8",
}
r = requests.get(url, headers=headers, impersonate="chrome124", timeout=12)
soup = BeautifulSoup(r.text, "lxml")

print("Page Title:", soup.title.string if soup.title else "None")

# 1. Product Title
title_elem = soup.find(id="productTitle")
title = title_elem.get_text(strip=True) if title_elem else "Not Found"
print("Title:", title[:80])

# 2. Brand
brand_elem = soup.find(id="bylineInfo")
brand = brand_elem.get_text(strip=True) if brand_elem else ""
print("Brand:", brand)

# 3. Price
price = None
price_elem = soup.find("span", class_="a-price-whole")
if price_elem:
    fraction = soup.find("span", class_="a-price-fraction")
    frac_str = ("." + fraction.get_text(strip=True)) if fraction else ""
    price = price_elem.get_text(strip=True).replace(",", "") + frac_str

curr_elem = soup.find("span", class_="a-price-symbol")
currency = curr_elem.get_text(strip=True) if curr_elem else "EGP"

old_price_elem = soup.find("span", class_="a-price a-text-price")
old_price = None
if old_price_elem:
    offscreen = old_price_elem.find("span", class_="a-offscreen")
    if offscreen:
        old_price = re.sub(r'[^\d.]', '', offscreen.get_text(strip=True))

print("Price:", price, currency, "(Old:", old_price, ")")

# 4. Images
images = []
# Look for colorImages JSON in scripts
color_images_match = re.search(r"'colorImages':\s*\{\s*'initial':\s*(\[.*?\])\s*\},", r.text, re.DOTALL)
if color_images_match:
    try:
        raw_json = color_images_match.group(1)
        data = json.loads(raw_json)
        for item in data:
            img_url = item.get("hiRes") or item.get("large") or item.get("main", {}).get(list(item.get("main", {}).keys())[-1] if item.get("main") else None)
            if img_url and img_url not in images:
                images.append(img_url)
    except Exception as e:
        print("JSON parse error for colorImages:", e)

# Fallback images: data-a-dynamic-image
if not images:
    for img_tag in soup.find_all("img", attrs={"data-a-dynamic-image": True}):
        try:
            d = json.loads(img_tag["data-a-dynamic-image"])
            for u in d.keys():
                if u not in images:
                    images.append(u)
        except:
            pass

print(f"Extracted {len(images)} images!")
for i, img in enumerate(images[:5], 1):
    print(f"  Img {i}: {img}")

# 5. Features / Bullets
bullets = []
bullets_div = soup.find(id="feature-bullets")
if bullets_div:
    for li in bullets_div.find_all("li"):
        t = li.get_text(strip=True)
        if t and not t.lower().startswith("make sure") and len(t) > 3:
            bullets.append(t)
print(f"Bullets ({len(bullets)} items):")
for b in bullets[:3]:
    print(f"  • {b[:70]}...")

# 6. Description
desc_elem = soup.find(id="productDescription")
desc = desc_elem.get_text(strip=True) if desc_elem else ""
print("Description length:", len(desc))

# 7. Specifications (Product Overview & Technical Details)
specs = {}
overview_div = soup.find(id="productOverview_feature_div")
if overview_div:
    for tr in overview_div.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 2:
            k = tds[0].get_text(strip=True)
            v = tds[1].get_text(strip=True)
            if k and v:
                specs[k] = v

print(f"Specs extracted ({len(specs)} fields):", list(specs.keys())[:5])

# 8. Rating & Reviews
rating_elem = soup.find("span", class_="a-icon-alt")
rating = rating_elem.get_text(strip=True) if rating_elem else ""
reviews_count_elem = soup.find(id="acrCustomerReviewText")
reviews_count = reviews_count_elem.get_text(strip=True) if reviews_count_elem else ""
print("Rating:", rating, "| Reviews:", reviews_count)

# 9. Stock / Availability
avail_elem = soup.find(id="availability")
avail = avail_elem.get_text(strip=True) if avail_elem else "In Stock"
print("Availability:", avail)
