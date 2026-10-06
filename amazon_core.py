import re
import html
import json
import time
import random
import urllib.parse
from typing import Dict, List, Optional, Any, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd

ILLEGAL_XML_CHARS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")
DIR_MARKS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\xa0]")

def sanitize_text(val: Any) -> Any:
    """Strips non-printable control characters and invalid XML characters."""
    if isinstance(val, str):
        val = ILLEGAL_XML_CHARS_RE.sub("", val)
        val = DIR_MARKS_RE.sub(" ", val)
        return val.strip()
    return val

def clean_inline(val: str) -> str:
    """Strips directional marks, illegal chars, and collapses multi-line whitespace into a clean single line."""
    if not val:
        return ""
    val = ILLEGAL_XML_CHARS_RE.sub("", str(val))
    val = DIR_MARKS_RE.sub(" ", val)
    val = re.sub(r"\s+", " ", val)
    return val.strip()

# Pool of modern browser fingerprints to rotate through when Amazon triggers bot detection
IMPERSONATION_POOL = ["chrome120", "safari17_0", "chrome110", "safari15_5", "chrome124"]

class AmazonScraper:
    def __init__(self, default_country: str = "eg", default_lang: str = "en"):
        self.default_country = default_country.lower()
        self.default_lang = default_lang.lower()
        
    def _get_domain(self, country: Optional[str] = None) -> str:
        c = (country or self.default_country).lower()
        domain_map = {
            "eg": "amazon.eg", "egypt": "amazon.eg", "مصر": "amazon.eg",
            "sa": "amazon.sa", "saudi": "amazon.sa", "ksa": "amazon.sa", "السعودية": "amazon.sa",
            "ae": "amazon.ae", "uae": "amazon.ae", "emirates": "amazon.ae", "الإمارات": "amazon.ae",
            "us": "amazon.com", "com": "amazon.com", "أمريكا": "amazon.com",
            "uk": "amazon.co.uk", "بريطانيا": "amazon.co.uk",
            "de": "amazon.de", "ألمانيا": "amazon.de"
        }
        return domain_map.get(c, "amazon.eg")

    def _resolve_short_url(self, url: str) -> str:
        """Resolves Amazon short URLs (amzn.to, amzn.eu, a.co) to full URLs."""
        if not any(domain in url.lower() for domain in ["amzn.to", "amzn.eu", "a.co"]):
            return url
        try:
            r = requests.head(url, impersonate="chrome120", timeout=6, allow_redirects=True)
            if r.url and r.url != url:
                return r.url
        except Exception:
            try:
                r = requests.get(url, impersonate="chrome120", timeout=8, allow_redirects=True)
                if r.url:
                    return r.url
            except Exception:
                pass
        return url

    def extract_asin_and_country(self, input_str: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extracts (ASIN, country_code) from a URL, short URL, or raw ASIN.
        """
        input_str = input_str.strip()
        
        # Check if it's a short URL and resolve it
        if any(d in input_str.lower() for d in ["amzn.to", "amzn.eu", "a.co"]):
            input_str = self._resolve_short_url(input_str)

        # Check URL domain for country
        country = None
        if "amazon.eg" in input_str: country = "eg"
        elif "amazon.sa" in input_str: country = "sa"
        elif "amazon.ae" in input_str: country = "ae"
        elif "amazon.com" in input_str: country = "us"
        elif "amazon.co.uk" in input_str: country = "uk"
        elif "amazon.de" in input_str: country = "de"

        # Regex for ASIN: handles /dp/, /gp/product/, /gp/aw/d/, /d/, /product/
        asin_match = re.search(r'/(?:dp|gp/product|gp/aw/d|d|product)/([A-Z0-9]{10})', input_str, re.IGNORECASE)
        if asin_match:
            return asin_match.group(1).upper(), country

        # Raw ASIN pattern (10 alphanumeric chars, typically starting with B)
        raw_match = re.search(r'\b([A-Z0-9]{10})\b', input_str, re.IGNORECASE)
        if raw_match:
            return raw_match.group(1).upper(), country

        return None, country

    def clean_html(self, raw_html: str) -> str:
        """Cleans raw HTML into nicely formatted plain text."""
        if not raw_html:
            return ""
        text = ILLEGAL_XML_CHARS_RE.sub("", raw_html)
        text = DIR_MARKS_RE.sub(" ", text)
        text = re.sub(r'<(p|br|div|li|h[1-6])[^>]*>', '\n', text, flags=re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html.unescape(text)
        lines = [re.sub(r'\s+', ' ', line).strip() for line in text.split('\n')]
        return '\n'.join([line for line in lines if line])

    def clean_image_url(self, url: str) -> str:
        """Removes Amazon resizing query/path fragments to obtain the full master image resolution."""
        # e.g., https://m.media-amazon.com/images/I/71ZNVWh1odL._AC_SL1500_.jpg -> https://m.media-amazon.com/images/I/71ZNVWh1odL.jpg
        return re.sub(r'\._[A-Za-z0-9_,-]+_\.', '.', url)

    def _is_bot_page(self, html_text: str, soup: BeautifulSoup) -> bool:
        """Detects if Amazon returned a bot check, CAPTCHA, or rate limit page."""
        if not html_text or len(html_text) < 4500:
            return True
        low = html_text.lower()
        if "validatecaptcha" in low or "api-services-support@amazon.com" in low or "enter the characters you see below" in low:
            return True
        if soup.title and "robot check" in soup.title.get_text().lower():
            return True
        # If title is not found and page is unusually small
        if not soup.find(id="productTitle") and not soup.find("h1", id="title"):
            if len(html_text) < 35000 or "something went wrong" in low:
                return True
        return False

    def scrape_product(self, input_target: str, country: Optional[str] = None, lang: Optional[str] = None) -> Dict[str, Any]:
        """
        Scrapes a single Amazon product by URL or ASIN.
        Automatically rotates browser impersonation fingerprints and retries on bot detection.
        """
        t0 = time.time()
        asin, url_country = self.extract_asin_and_country(input_target)
        if not asin:
            return {
                "status": "error",
                "input": input_target,
                "error": "لم يتم العثور على كود ASIN صالح في الرابط.",
                "scrape_time_seconds": round(time.time() - t0, 3)
            }

        final_country = country or url_country or self.default_country
        final_lang = (lang or self.default_lang or "en").lower()
        domain = self._get_domain(final_country)
        
        # Build canonical PDP URL (use /-/en for English)
        lang_prefix = "/-/en" if final_lang == "en" else ""
        product_url = f"https://www.{domain}{lang_prefix}/dp/{asin}"
        
        # Shuffle impersonation pool to vary initial profile
        profiles = list(IMPERSONATION_POOL)
        random.shuffle(profiles)
        
        last_error = None
        for attempt, imp in enumerate(profiles):
            try:
                # We use curl_cffi with impersonation. We do NOT pass conflicting headers or cookies
                # as that triggers Amazon's bot detection.
                r = requests.get(product_url, impersonate=imp, timeout=12)
                
                if r.status_code == 404:
                    return {
                        "status": "error",
                        "sku": asin,
                        "input": input_target,
                        "error": f"Product not found on Amazon ({domain}) ASIN: {asin} (HTTP 404)",
                        "scrape_time_seconds": round(time.time() - t0, 3)
                    }

                html_text = r.text
                soup = BeautifulSoup(html_text, "lxml")
                
                # Check for bot block / captcha
                if self._is_bot_page(html_text, soup):
                    last_error = f"Bot challenge detected with profile {imp}"
                    # Sleep slightly and retry with next browser profile
                    time.sleep(0.4 + random.random() * 0.4)
                    continue

                parsed = self._parse_amazon_page(soup, html_text, asin, product_url, final_country, lang=final_lang)
                
                # Verify that we extracted a valid product title
                if not parsed.get("name"):
                    last_error = "Could not extract product title from page"
                    time.sleep(0.4)
                    continue

                parsed["scrape_time_seconds"] = round(time.time() - t0, 3)
                parsed["status"] = "success"
                return parsed

            except Exception as e:
                last_error = str(e)
                time.sleep(0.3)
                continue

        # If all profiles failed/blocked
        return {
            "status": "error",
            "sku": asin,
            "input": input_target,
            "error": f"تعذر سحب تفاصيل المنتج من أمازون بعد عدة محاولات (حماية أمازون/رمز التحقق): {last_error}",
            "scrape_time_seconds": round(time.time() - t0, 3)
        }

    def _parse_amazon_page(self, soup: BeautifulSoup, html_text: str, asin: str, url: str, country: str, lang: str = "en") -> Dict[str, Any]:
        """
        Comprehensive Amazon PDP extractor extracting title, brand, price, discounts,
        full specifications (from all tables & bullets), rich descriptions, and Full HD images.
        """
        # 1. Product Title
        title = ""
        title_elem = soup.find(id="productTitle") or soup.find("h1", id="title") or soup.select_one(".product-title-word-break")
        if title_elem:
            title = clean_inline(title_elem.get_text())
        if not title:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.get("content"):
                title = clean_inline(meta_title["content"])

        # 2. Specifications Extraction (Comprehensive: prodDetTable, overview, tech specs, detail bullets)
        specifications = {}

        # 2a. prodDetTable (Standard Amazon Technical Details tables)
        for tbl in soup.find_all("table", class_="prodDetTable"):
            for tr in tbl.find_all("tr"):
                th = tr.find(["th", "td"])
                tds = tr.find_all("td")
                if th and tds:
                    k = clean_inline(th.get_text())
                    v = clean_inline(tds[-1].get_text())
                    if k and v and k not in specifications and k.lower() != "customer reviews":
                        specifications[k] = v

        # 2b. productOverview_feature_div
        overview_div = soup.find(id="productOverview_feature_div")
        if overview_div:
            # Table rows
            for tr in overview_div.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    k = clean_inline(tds[0].get_text())
                    v = clean_inline(tds[1].get_text())
                    if k and v and k not in specifications:
                        specifications[k] = v
            # Div grid rows
            for row in overview_div.find_all("div", class_=re.compile(r"po-row|a-row")):
                spans = row.find_all("span")
                if len(spans) >= 2:
                    k = clean_inline(spans[0].get_text())
                    v = clean_inline(spans[1].get_text())
                    if k and v and k not in specifications:
                        specifications[k] = v

        # 2c. Technical Details & Specification tables
        tech_spec_ids = [
            "productDetails_techSpec_section_1",
            "productDetails_techSpec_section_2",
            "technicalSpecifications_section_1",
            "technicalSpecifications_feature_div",
            "prodDetails"
        ]
        for tid in tech_spec_ids:
            sec = soup.find(id=tid)
            if sec:
                for tr in sec.find_all("tr"):
                    th = tr.find("th")
                    td = tr.find("td")
                    if th and td:
                        k = clean_inline(th.get_text())
                        v = clean_inline(td.get_text())
                        if k and v and k not in specifications and k.lower() != "customer reviews":
                            specifications[k] = v

        # 2d. detailBullets_feature_div
        detail_bullets = soup.find(id="detailBullets_feature_div")
        if detail_bullets:
            for li in detail_bullets.find_all("li"):
                raw_item = clean_inline(li.get_text())
                if ":" in raw_item:
                    parts = raw_item.split(":", 1)
                    k = clean_inline(parts[0])
                    v = clean_inline(parts[1])
                    if k and v and k not in specifications and "customer reviews" not in k.lower():
                        specifications[k] = v

        # 3. Brand
        brand = ""
        brand_elem = soup.find(id="bylineInfo") or soup.find(id="brand")
        if brand_elem:
            brand_text = clean_inline(brand_elem.get_text())
            brand = re.sub(r'^(Brand:|Visit the|Store|ماركة:|زيارة متجر)\s*', '', brand_text, flags=re.I).strip()
            brand = re.sub(r'\s*Store$', '', brand, flags=re.I).strip()
        if not brand:
            # Check specs for Brand Name / Brand / العلامة التجارية
            for b_key in ["Brand Name", "Brand", "العلامة التجارية", "الماركة"]:
                if b_key in specifications:
                    brand = specifications[b_key]
                    break

        # 4. Price & Currency
        price = None
        # Try primary modern Amazon price selectors
        price_selectors = [
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            "#price_inside_buybox",
            "#priceblock_ourprice",
            "#priceblock_dealprice"
        ]
        for sel in price_selectors:
            elem = soup.select_one(sel)
            if elem:
                txt = elem.get_text()
                val = re.sub(r'[^\d.]', '', txt.replace(',', ''))
                if val:
                    try:
                        price = float(val)
                        break
                    except ValueError:
                        pass

        # Fallback to whole + fraction
        if price is None:
            whole = soup.find("span", class_="a-price-whole")
            if whole:
                fraction = soup.find("span", class_="a-price-fraction")
                w = re.sub(r'[^\d]', '', whole.get_text())
                f = re.sub(r'[^\d]', '', fraction.get_text()) if fraction else ""
                try:
                    price = float(f"{w}.{f}") if f else float(w)
                except ValueError:
                    pass

        # Original / Strikethrough Price
        original_price = price
        old_price_elem = soup.select_one(".a-price.a-text-price .a-offscreen, #basisPrice .a-offscreen")
        if old_price_elem:
            val_old = re.sub(r'[^\d.]', '', old_price_elem.get_text().replace(',', ''))
            try:
                op = float(val_old)
                if op > 0:
                    original_price = op
            except ValueError:
                pass

        discount_percentage = None
        if original_price and price and original_price > price:
            discount_percentage = round(((original_price - price) / original_price) * 100, 1)

        # Currency
        curr_elem = soup.find("span", class_="a-price-symbol")
        currency = clean_inline(curr_elem.get_text()) if curr_elem else ""
        if not currency:
            curr_map = {"eg": "EGP", "sa": "SAR", "ae": "AED", "us": "USD", "uk": "GBP", "de": "EUR"}
            currency = curr_map.get(country, "EGP")

        # 5. Full HD Images Extraction
        images = []
        # Method A: colorImages JSON in scripts
        color_images_match = re.search(r"'colorImages':\s*\{\s*'initial':\s*(\[.*?\])\s*\},", html_text, re.DOTALL)
        if color_images_match:
            try:
                raw_json = color_images_match.group(1)
                data = json.loads(raw_json)
                for item in data:
                    img_url = item.get("hiRes") or item.get("large")
                    if img_url:
                        clean_u = self.clean_image_url(img_url)
                        if clean_u not in images:
                            images.append(clean_u)
            except Exception:
                pass

        # Method B: data-a-dynamic-image
        for img_tag in soup.find_all("img", attrs={"data-a-dynamic-image": True}):
            try:
                d = json.loads(img_tag["data-a-dynamic-image"])
                for u in d.keys():
                    clean_u = self.clean_image_url(u)
                    if clean_u not in images:
                        images.append(clean_u)
            except Exception:
                pass

        # Method C: landingImage
        landing = soup.find(id="landingImage")
        if landing:
            src = landing.get("data-old-hires") or landing.get("src")
            if src:
                clean_u = self.clean_image_url(src)
                if clean_u not in images:
                    images.append(clean_u)

        # Method D: Raw regex fallback for hiRes or large
        if not images:
            hires_matches = re.findall(r'"hiRes":\s*"([^"]+)"|"large":\s*"([^"]+)"', html_text)
            for h1, h2 in hires_matches:
                u = h1 or h2
                if u and "http" in u:
                    clean_u = self.clean_image_url(u)
                    if clean_u not in images:
                        images.append(clean_u)

        # 6. Description & Key Features Extraction
        # 6a. Feature Bullets
        bullets = []
        bullets_div = soup.find(id="feature-bullets") or soup.find(id="featurebullets_feature_div")
        if bullets_div:
            for li in bullets_div.find_all("li"):
                t = clean_inline(li.get_text())
                if t and not t.lower().startswith("make sure") and len(t) > 3:
                    bullets.append(sanitize_text(t))

        # 6b. Main Description text
        desc_elem = soup.find(id="productDescription") or soup.select_one("[data-feature-name='productDescription']") or soup.find(id="productDescription_feature_div")
        raw_desc = desc_elem.get_text(strip=True) if desc_elem else ""
        clean_desc = self.clean_html(raw_desc)

        # 6c. A+ Content text (rich manufacturer description)
        aplus_text = ""
        aplus_div = soup.find(id="aplus") or soup.find(id="aplus_feature_div") or soup.find(id="dpx-aplus-product-description_feature_div")
        if aplus_div:
            aplus_paras = []
            for p in aplus_div.find_all(["p", "h3", "h4"]):
                pt = clean_inline(p.get_text())
                if pt and len(pt) > 15 and pt not in aplus_paras:
                    aplus_paras.append(pt)
            if aplus_paras:
                aplus_text = "\n".join(aplus_paras[:8])

        # Combine descriptions and bullets
        bullets_text = ("\n• " + "\n• ".join(bullets)) if bullets else ""
        full_description = clean_desc
        if not full_description and aplus_text:
            full_description = aplus_text

        if bullets_text:
            heading = "\n\nKey Features:" if lang == "en" else "\n\nالمميزات الأساسية / Key Features:"
            if full_description:
                full_description += heading + bullets_text
            else:
                full_description = ("Key Features:" if lang == "en" else "المميزات الأساسية / Key Features:") + bullets_text

        # 7. Category / Breadcrumbs
        breadcrumbs = []
        bc_div = soup.find(id="wayfinding-breadcrumbs_feature_div")
        if bc_div:
            for a in bc_div.find_all("a"):
                t = clean_inline(a.get_text())
                if t:
                    breadcrumbs.append(t)
        category = " > ".join(breadcrumbs) if breadcrumbs else ""

        # 8. Rating & Review count
        rating_val = None
        rating_elem = soup.find("span", class_="a-icon-alt")
        if rating_elem:
            r_match = re.search(r'([\d.]+)', rating_elem.get_text(strip=True))
            if r_match:
                try:
                    rating_val = float(r_match.group(1))
                except ValueError:
                    pass

        reviews_count = None
        reviews_elem = soup.find(id="acrCustomerReviewText")
        if reviews_elem:
            rev_match = re.search(r'([\d,]+)', reviews_elem.get_text(strip=True))
            if rev_match:
                try:
                    reviews_count = int(rev_match.group(1).replace(",", ""))
                except ValueError:
                    pass

        # 9. Availability & Stock
        avail_elem = soup.find(id="availability")
        avail_text = clean_inline(avail_elem.get_text()) if avail_elem else "In Stock"
        in_stock = "unavailable" not in avail_text.lower() and "غير متوفر" not in avail_text
        
        stock_count = None
        stock_match = re.search(r'only\s*(\d+)\s*left|متبقي\s*(\d+)\s*فقط', avail_text, re.I)
        if stock_match:
            stock_count = int(stock_match.group(1) or stock_match.group(2))

        # 10. Seller
        seller = ""
        seller_elem = soup.find(id="sellerProfileTriggerId") or soup.find(id="merchant-info")
        if seller_elem:
            seller = clean_inline(seller_elem.get_text())

        return {
            "sku": asin,
            "name": sanitize_text(title),
            "brand": sanitize_text(brand),
            "category": sanitize_text(category),
            "price": price,
            "original_price": original_price,
            "discount_percentage": discount_percentage,
            "currency": currency,
            "in_stock": in_stock,
            "stock_count": stock_count,
            "seller": seller,
            "rating": rating_val,
            "rating_count": reviews_count,
            "description": sanitize_text(full_description),
            "specifications": specifications,
            "images": images,
            "image_count": len(images),
            "url": url,
            "store": "amazon"
        }

    def scrape_batch(self, targets: List[str], max_workers: int = 5, country: Optional[str] = None, lang: Optional[str] = None, progress_callback=None) -> List[Dict[str, Any]]:
        results = [None] * len(targets)
        def worker(index, target):
            res = self.scrape_product(target, country=country, lang=lang)
            return index, res

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, i, t) for i, t in enumerate(targets)]
            completed_count = 0
            for fut in as_completed(futures):
                idx, res = fut.result()
                results[idx] = res
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, len(targets), res)
        return results

    def harvest_bestseller_asins(self, category_path: str = "electronics", country: str = "eg", max_pages: int = 2) -> List[str]:
        """
        Harvests ASINs from Amazon Bestsellers page (across pages 1 and 2).
        """
        domain = self._get_domain(country)
        collected: Set[str] = set()
        for p in range(1, max_pages + 1):
            url = f"https://www.{domain}/gp/bestsellers/{category_path}?pg={p}"
            try:
                r = requests.get(url, impersonate="chrome124", timeout=8)
                if r.status_code == 200:
                    asins = re.findall(r'/(?:dp|product)/([A-Z0-9]{10})', r.text)
                    asins += re.findall(r'data-asin="([A-Z0-9]{10})"', r.text)
                    for a in asins:
                        if len(a) == 10:
                            collected.add(a)
            except Exception:
                pass
        return list(collected)

    def harvest_search_asins(self, keyword: str, country: str = "eg", page: int = 1) -> List[str]:
        """
        Harvests ASINs from an Amazon search page.
        """
        domain = self._get_domain(country)
        encoded_kw = urllib.parse.quote_plus(keyword)
        url = f"https://www.{domain}/s?k={encoded_kw}&page={page}"
        try:
            r = requests.get(url, impersonate="chrome124", timeout=8)
            if r.status_code == 200:
                asins = re.findall(r'data-asin="([A-Z0-9]{10})"', r.text)
                return [a for a in set(asins) if len(a) == 10]
        except Exception:
            pass
        return []

    def harvest_parallel(
        self,
        keywords: Optional[List[str]] = None,
        category: Optional[str] = "all",
        target_count: int = 3000,
        country: str = "eg"
    ) -> List[str]:
        """
        Rapidly harvests up to target_count ASINs using multi-threaded search and bestseller scrapers.
        """
        collected_asins: Set[str] = set()

        category_kw_map = {
            "electronics-and-mobiles": [
                "phone", "laptop", "samsung", "iphone", "headphones", "charger", "smartwatch",
                "tablet", "screen", "camera", "earbuds", "monitor", "cable", "mouse", "keyboard",
                "power bank", "soundbar", "speaker", "hard drive", "router"
            ],
            "beauty-and-health": [
                "perfume", "skincare", "cream", "makeup", "shampoo", "serum", "hair",
                "lipstick", "sunscreen", "lotion", "mascara", "foundation", "cleanser",
                "hair dryer", "shaver", "toothpaste", "soap", "deodorant"
            ],
            "home-and-kitchen": [
                "kitchen", "cookware", "blender", "coffee", "bedding", "storage", "vacuum",
                "air fryer", "pan", "pot", "knife", "towel", "pillow", "furniture",
                "microwave", "curtain", "lamp", "carpet", "desk"
            ],
            "fashion": [
                "shoes", "t-shirt", "dress", "watch", "sneakers", "bag", "jacket",
                "pants", "sunglasses", "wallet", "hoodie", "boots", "socks",
                "jeans", "swimwear", "sweater", "backpack"
            ],
            "supermarket": [
                "coffee", "tea", "detergent", "chocolate", "oil", "rice", "cleaner",
                "soap", "tissue", "shampoo", "olive oil", "biscuit", "pasta",
                "sugar", "cereal", "sauce", "chips"
            ],
            "sports-and-outdoors": [
                "gym", "fitness", "yoga", "football", "dumbbell", "shoes", "water bottle",
                "bicycle", "backpack", "running", "mat", "gloves", "treadmill",
                "resistance bands", "smartwatch", "camping"
            ],
            "baby-products": [
                "baby", "diapers", "stroller", "toys", "crib", "wipes", "bottle",
                "car seat", "pacifier", "baby clothing", "dollhouses", "doll", "playmat"
            ]
        }

        tasks = []

        if keywords and len(keywords) > 0:
            # User provided specific keywords (e.g., "Dollhouses", "iphone, samsung")
            pages_needed = max(5, min(25, (target_count // 35 // len(keywords)) + 4))
            for kw in keywords:
                for p in range(1, pages_needed + 1):
                    tasks.append(("search", kw.strip(), p))
        else:
            # Harvesting by category or "all"
            if category and category in category_kw_map:
                search_terms = category_kw_map[category]
                cat_slug = category.split("-")[0]
                tasks.append(("bestseller", cat_slug, 1))
                tasks.append(("bestseller", cat_slug, 2))
            else:
                # "all" - blend bestsellers across departments and popular search terms
                bestseller_cats = [
                    "electronics", "computers", "kitchen", "beauty", "fashion",
                    "grocery", "sports", "toys", "office-products", "baby", "home-improvement"
                ]
                for bc in bestseller_cats:
                    tasks.append(("bestseller", bc, 1))
                    tasks.append(("bestseller", bc, 2))

                search_terms = []
                for terms in category_kw_map.values():
                    search_terms.extend(terms[:4])

            pages_per_kw = max(3, (target_count // 45 // max(1, len(search_terms))) + 2)
            for st in search_terms:
                for p in range(1, min(pages_per_kw + 1, 15)):
                    tasks.append(("search", st, p))

        def execute_task(task_item):
            task_type, arg, p = task_item
            if task_type == "bestseller":
                domain = self._get_domain(country)
                url = f"https://www.{domain}/gp/bestsellers/{arg}?pg={p}"
                try:
                    r = requests.get(url, impersonate="chrome124", timeout=8)
                    if r.status_code == 200:
                        asins = re.findall(r'/(?:dp|product)/([A-Z0-9]{10})', r.text)
                        asins += re.findall(r'data-asin="([A-Z0-9]{10})"', r.text)
                        return [a for a in asins if len(a) == 10]
                except Exception:
                    pass
                return []
            else:
                return self.harvest_search_asins(arg, country=country, page=p)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(execute_task, t) for t in tasks]
            for fut in as_completed(futures):
                try:
                    found = fut.result()
                    for asin in found:
                        collected_asins.add(asin)
                        if len(collected_asins) >= target_count:
                            break
                    if len(collected_asins) >= target_count:
                        break
                except Exception:
                    pass

        return list(collected_asins)[:target_count]
