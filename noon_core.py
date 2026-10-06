import re
import html
import os
import json
import time
import zipfile
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
import pandas as pd

ILLEGAL_XML_CHARS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")

def sanitize_text(val: Any) -> Any:
    """Strips non-printable control characters that are illegal in Excel XML worksheets."""
    if isinstance(val, str):
        return ILLEGAL_XML_CHARS_RE.sub("", val)
    return val

class NoonScraper:
    def __init__(self, default_country: str = "eg", default_lang: str = "en"):
        self.default_country = default_country.lower()
        self.default_lang = default_lang.lower()
        self.base_url = "https://www.noon.com"
        
    def _get_locale(self, country: Optional[str] = None, lang: Optional[str] = None) -> str:
        c = (country or self.default_country).lower()
        l = (lang or self.default_lang).lower()
        
        country_aliases = {
            "egypt": "eg", "eg": "eg", "مصر": "eg",
            "uae": "ae", "ae": "ae", "emirates": "ae", "الامارات": "ae", "الإمارات": "ae",
            "saudi": "sa", "sa": "sa", "ksa": "sa", "السعودية": "sa",
            "kuwait": "kw", "kw": "kw", "الكويت": "kw",
            "qatar": "qa", "qa": "qa", "قطر": "qa",
            "bahrain": "bh", "bh": "bh", "البحرين": "bh",
        }
        c = country_aliases.get(c, "eg")
        if l not in ["en", "ar"]:
            l = "en"
        return f"{l}-{c}"

    def extract_sku_and_locale(self, input_str: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extracts (sku, country, lang) from a URL or raw SKU.
        """
        input_str = input_str.strip()
        
        sku_match = re.search(r'\b(N[0-9A-Z]{7,12}[A-Z]?)\b', input_str, re.IGNORECASE)
        sku = sku_match.group(1).upper() if sku_match else None
        
        country = None
        lang = None
        
        if "noon.com" in input_str:
            loc_match = re.search(r'noon\.com/([a-z]+)-([a-z]{2})', input_str, re.IGNORECASE)
            if loc_match:
                p1, p2 = loc_match.groups()
                p1, p2 = p1.lower(), p2.lower()
                c_map = {
                    "egypt": "eg", "eg": "eg", "مصر": "eg",
                    "saudi": "sa", "sa": "sa", "ksa": "sa", "السعودية": "sa",
                    "uae": "ae", "ae": "ae", "emirates": "ae", "الإمارات": "ae",
                    "kuwait": "kw", "kw": "kw", "الكويت": "kw",
                    "qatar": "qa", "qa": "qa", "قطر": "qa",
                    "bahrain": "bh", "bh": "bh", "البحرين": "bh",
                }
                if p1 in c_map:
                    country = c_map[p1]
                    lang = p2 if p2 in ["en", "ar"] else "en"
                elif p2 in c_map:
                    country = c_map[p2]
                    lang = p1 if p1 in ["en", "ar"] else "en"
        
        return sku, country, lang

    def clean_html(self, raw_html: str) -> str:
        """Strips HTML tags, cleans extra spaces, decodes entities and strips illegal Excel characters."""
        if not raw_html:
            return ""
        text = ILLEGAL_XML_CHARS_RE.sub("", raw_html)
        text = re.sub(r'<(p|br|div|li|h[1-6])[^>]*>', '\n', text, flags=re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html.unescape(text)
        lines = [re.sub(r'\s+', ' ', line).strip() for line in text.split('\n')]
        return '\n'.join([line for line in lines if line])

    def scrape_product(self, input_target: str, country: Optional[str] = None, lang: Optional[str] = None) -> Dict[str, Any]:
        """
        Scrapes a single product by URL or SKU.
        Extremely fast (typically 0.3s - 0.5s).
        """
        t0 = time.time()
        extracted_sku, url_country, url_lang = self.extract_sku_and_locale(input_target)
        sku = extracted_sku or input_target.strip()
        
        final_country = country or url_country or self.default_country
        final_lang = (lang or self.default_lang or "en").lower()
        locale = self._get_locale(final_country, final_lang)
        
        api_url = f"https://www.noon.com/_svc/catalog/api/v1/product/{sku}"
        headers = {
            "x-locale": locale,
            "x-platform": "web",
            "accept": "application/json"
        }
        
        product_res = None
        error_msg = None
        
        # Method 1: Internal API
        try:
            r = requests.get(api_url, headers=headers, impersonate="chrome124", timeout=7)
            if r.status_code == 200:
                data = r.json()
                product_res = self._parse_api_product(data, sku, final_country, final_lang)
            elif r.status_code == 404:
                error_msg = f"Product with SKU '{sku}' not found (404)."
        except Exception as e:
            error_msg = str(e)
            
        # Method 2: HTML Page Fallback if API returned non-200
        if not product_res and not (error_msg and "404" in error_msg):
            try:
                c_part = locale.split('-')[1]
                l_part = locale.split('-')[0]
                c_name = "egypt" if c_part == "eg" else ("saudi" if c_part == "sa" else "uae")
                page_url = input_target if input_target.startswith("http") else f"https://www.noon.com/{c_name}-{l_part}/p/{sku}"
                r_page = requests.get(page_url, impersonate="chrome124", timeout=10)
                if r_page.status_code == 200:
                    product_res = self._parse_html_product(r_page.text, sku, page_url, final_country)
            except Exception as e:
                pass
                
        elapsed = round(time.time() - t0, 3)
        if product_res:
            product_res["scrape_time_seconds"] = elapsed
            product_res["status"] = "success"
            return product_res
        else:
            return {
                "status": "error",
                "sku": sku,
                "input": input_target,
                "error": error_msg or f"Failed to retrieve product '{sku}'.",
                "scrape_time_seconds": elapsed
            }

    def _parse_api_product(self, data: dict, sku: str, country: str, lang: str) -> Dict[str, Any]:
        p = data.get("product", {})
        
        title = p.get("product_title") or ""
        brand = p.get("brand") or ""
        
        long_desc = p.get("long_description") or ""
        clean_desc = self.clean_html(long_desc)
        
        bullets = p.get("feature_bullets") or []
        bullets_text = "\n• " + "\n• ".join(bullets) if bullets else ""
        
        full_description = clean_desc
        if bullets_text:
            heading = "\n\nKey Features:" if lang == "en" else "\n\nالمميزات الأساسية / Key Features:"
            if full_description:
                full_description += heading + bullets_text
            else:
                full_description = ("Key Features:" if lang == "en" else "المميزات الأساسية / Key Features:") + bullets_text
                
        raw_images = p.get("image_urls") or []
        images = []
        for img in raw_images:
            if not img.startswith("http"):
                img = f"https://f.nooncdn.com/p/{img}.jpg"
            if "?" in img:
                base_img = img.split("?")[0]
                img = f"{base_img}?width=1200"
            else:
                img = f"{img}?width=1200"
            if img not in images:
                images.append(img)
                
        variants = p.get("variants") or []
        offers = variants[0].get("offers", []) if variants else []
        
        price = None
        original_price = None
        discount_percentage = None
        stock = None
        seller = ""
        is_buyable = False
        
        if offers:
            main_offer = offers[0]
            price = main_offer.get("sale_price") or main_offer.get("price")
            original_price = main_offer.get("price")
            if original_price and price and original_price > price:
                discount_percentage = round(((original_price - price) / original_price) * 100, 1)
            else:
                original_price = price
            stock = main_offer.get("stock")
            seller = main_offer.get("store_name") or ""
            is_buyable = main_offer.get("is_buyable", True)
            
        currency_map = {
            "eg": "EGP", "ae": "AED", "sa": "SAR", "kw": "KWD", "qa": "QAR", "bh": "BHD"
        }
        currency = currency_map.get(country, "EGP")
        
        specs_list = p.get("specifications") or []
        specifications = {}
        for sp in specs_list:
            n = sp.get("name")
            v = sp.get("value")
            if n and v:
                specifications[n] = str(v)
                
        breadcrumbs = [b.get("name") for b in p.get("breadcrumbs", []) if b.get("name") and b.get("name") != "Home"]
        category = " > ".join(breadcrumbs) if breadcrumbs else ""
        
        rating_obj = p.get("product_rating") or {}
        rating_value = rating_obj.get("value")
        rating_count = rating_obj.get("count")
        
        can_url = p.get("canonical_url") or f"/{sku}/p"
        if not can_url.startswith("http"):
            c_slug = "egypt" if country == "eg" else ("saudi" if country == "sa" else "uae")
            can_url = f"https://www.noon.com/{c_slug}-{lang}{can_url}"
            
        return {
            "sku": sku,
            "name": title,
            "brand": brand,
            "category": category,
            "price": price,
            "original_price": original_price,
            "discount_percentage": discount_percentage,
            "currency": currency,
            "in_stock": is_buyable and (stock is None or stock > 0),
            "stock_count": stock,
            "seller": seller,
            "rating": rating_value,
            "rating_count": rating_count,
            "description": full_description,
            "specifications": specifications,
            "images": images,
            "image_count": len(images),
            "url": can_url
        }

    def _parse_html_product(self, html_text: str, sku: str, url: str, country: str) -> Optional[Dict[str, Any]]:
        for j in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_text, re.DOTALL):
            try:
                data = json.loads(j)
                if data.get("@type") == "Product":
                    offers = data.get("offers", {})
                    images = data.get("image", [])
                    if isinstance(images, str):
                        images = [images]
                    high_res_images = [img.split("?")[0] + "?width=1200" if "?" in img else img + "?width=1200" for img in images]
                    specs = {}
                    for prop in data.get("additionalProperty", []):
                        specs[prop.get("name")] = prop.get("value")
                    
                    price = offers.get("price")
                    return {
                        "sku": data.get("sku") or sku,
                        "name": data.get("name"),
                        "brand": data.get("brand", {}).get("name", ""),
                        "category": "",
                        "price": price if price and price > 0 else None,
                        "original_price": price if price and price > 0 else None,
                        "discount_percentage": None,
                        "currency": offers.get("priceCurrency", "EGP"),
                        "in_stock": "InStock" in offers.get("availability", ""),
                        "stock_count": None,
                        "seller": offers.get("seller", {}).get("name", ""),
                        "rating": data.get("aggregateRating", {}).get("ratingValue"),
                        "rating_count": data.get("aggregateRating", {}).get("reviewCount"),
                        "description": self.clean_html(data.get("description", "")),
                        "specifications": specs,
                        "images": high_res_images,
                        "image_count": len(high_res_images),
                        "url": url
                    }
            except:
                pass
        return None

    def search_products(self, query: str, limit: int = 24, country: str = "eg", lang: str = "en") -> List[Dict[str, Any]]:
        """
        Searches Noon for a keyword and returns product items.
        """
        locale = self._get_locale(country, lang)
        url = f"https://www.noon.com/_svc/catalog/api/search?q={query}&limit={limit}"
        headers = {
            "x-locale": locale,
            "x-platform": "web",
            "accept": "application/json"
        }
        
        try:
            r = requests.get(url, headers=headers, impersonate="chrome124", timeout=8)
            if r.status_code == 200:
                data = r.json()
                hits = data.get("hits", [])
                results = []
                for h in hits:
                    sku = h.get("sku")
                    if not sku:
                        continue
                    results.append({
                        "sku": sku,
                        "name": h.get("name") or h.get("title", ""),
                        "price": h.get("sale_price") or h.get("price"),
                        "original_price": h.get("price"),
                        "brand": h.get("brand", ""),
                        "image": f"https://f.nooncdn.com/p/{h.get('image_key')}.jpg?width=600" if h.get("image_key") else h.get("image_url"),
                        "url": f"https://www.noon.com/{h.get('url')}" if h.get("url") else None
                    })
                return results
        except Exception as e:
            print("Search error:", e)
        return []

    def scrape_batch(self, targets: List[str], max_workers: int = 5, country: Optional[str] = None, lang: Optional[str] = None, progress_callback=None) -> List[Dict[str, Any]]:
        """
        Scrapes a list of URLs or SKUs concurrently using a thread pool.
        """
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

    def download_product_images(self, product: Dict[str, Any], output_folder: str = "downloads/images", max_workers: int = 4) -> List[str]:
        """
        Downloads all images of a product into output_folder/{sku}/
        Returns list of local file paths.
        """
        sku = product.get("sku") or "product"
        target_dir = os.path.join(output_folder, sku)
        os.makedirs(target_dir, exist_ok=True)
        
        images = product.get("images") or []
        downloaded = []
        
        def download_single(idx, img_url):
            try:
                ext = "jpg"
                if ".png" in img_url.lower(): ext = "png"
                elif ".webp" in img_url.lower(): ext = "webp"
                local_path = os.path.join(target_dir, f"{sku}_{idx + 1}.{ext}")
                
                resp = requests.get(img_url, impersonate="chrome124", timeout=10)
                if resp.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(resp.content)
                    return local_path
            except Exception as e:
                print(f"Error downloading image {img_url}: {e}")
            return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(download_single, i, url) for i, url in enumerate(images)]
            for fut in as_completed(futures):
                path = fut.result()
                if path:
                    downloaded.append(path)
                    
        return downloaded

    def create_images_zip(self, products: List[Dict[str, Any]], zip_path: str, progress_callback=None) -> str:
        """
        Downloads all images for the products and packs them into a single organized ZIP archive.
        """
        os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
        temp_img_dir = os.path.join(os.path.dirname(zip_path), "temp_img_dl")
        os.makedirs(temp_img_dir, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            total_images = sum(len(p.get("images", [])) for p in products if p.get("status") == "success")
            dl_count = 0
            
            for p in products:
                if p.get("status") != "success":
                    continue
                sku = p.get("sku")
                images = p.get("images", [])
                for idx, img_url in enumerate(images):
                    try:
                        ext = "jpg"
                        if ".png" in img_url.lower(): ext = "png"
                        elif ".webp" in img_url.lower(): ext = "webp"
                        filename = f"{sku}/{sku}_{idx+1}.{ext}"
                        
                        resp = requests.get(img_url, impersonate="chrome124", timeout=8)
                        if resp.status_code == 200:
                            zipf.writestr(filename, resp.content)
                    except Exception as e:
                        pass
                    dl_count += 1
                    if progress_callback:
                        progress_callback(dl_count, total_images)
                        
        return zip_path

    def export_to_excel(self, products: List[Dict[str, Any]], filepath: str):
        """
        Exports scraped products to a professionally formatted Excel spreadsheet.
        Puts each image link into its own dedicated column (صورة 1، صورة 2، صورة 3...).
        """
        valid_products = [p for p in products if p.get("status") == "success"]
        max_imgs = max([len(p.get("images", [])) for p in valid_products] or [1])

        rows = []
        for p in products:
            if p.get("status") == "error":
                row_err = {
                    "Store": "Amazon" if (p.get("store") == "amazon" or "amazon." in (p.get("url") or "")) else "Noon",
                    "SKU / ASIN": p.get("sku"),
                    "Title": p.get("input"),
                    "Stock Status": "Error",
                    "Description": p.get("error"),
                    "URL": p.get("input"),
                    "Scrape Time (s)": p.get("scrape_time_seconds")
                }
                rows.append(row_err)
                continue
                
            specs_str = " | ".join([f"{k}: {v}" for k, v in (p.get("specifications") or {}).items()])
            images_list = p.get("images") or []
            
            is_amazon = p.get("store") == "amazon" or "amazon." in (p.get("url") or "")
            store_label = "Amazon" if is_amazon else "Noon"
            
            row = {
                "Store": store_label,
                "SKU / ASIN": p.get("sku"),
                "Title": p.get("name"),
                "Brand": p.get("brand"),
                "Category": p.get("category"),
                "Price": p.get("price"),
                "Original Price": p.get("original_price"),
                "Discount %": f"{p.get('discount_percentage')}%" if p.get('discount_percentage') else "0%",
                "Currency": p.get("currency"),
                "Stock Status": "In Stock" if p.get("in_stock") else "Out of Stock",
                "Stock Count": p.get("stock_count") if p.get("stock_count") is not None else "N/A",
                "Seller": p.get("seller"),
                "Rating": p.get("rating"),
                "Reviews Count": p.get("rating_count"),
                "Images Count": p.get("image_count", len(images_list)),
            }
            
            # Dedicated column per image link
            for i in range(max_imgs):
                col_name = f"Image {i + 1} (Main)" if i == 0 else f"Image {i + 1}"
                row[col_name] = images_list[i] if i < len(images_list) else ""

            row["Description"] = p.get("description")
            row["Specifications"] = specs_str
            row["URL"] = p.get("url")
            row["Scrape Time (s)"] = p.get("scrape_time_seconds")
            
            # Sanitize every field against openpyxl IllegalCharacterError
            sanitized_row = {k: sanitize_text(v) for k, v in row.items()}
            rows.append(sanitized_row)
            
        df = pd.DataFrame(rows)
        df = df.map(sanitize_text)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Products Catalog")
            ws = writer.sheets["Products Catalog"]
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    val = str(cell.value or '')
                    if len(val) > max_len:
                        max_len = min(len(val), 50)
                ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

    def export_to_csv(self, products: List[Dict[str, Any]], filepath: str):
        """Exports to CSV with utf-8-sig BOM with a dedicated column per image link."""
        valid_products = [p for p in products if p.get("status") == "success"]
        max_imgs = max([len(p.get("images", [])) for p in valid_products] or [1])

        rows = []
        for p in products:
            if p.get("status") == "error":
                continue
            images_list = p.get("images") or []
            specs_str = " | ".join([f"{k}: {v}" for k, v in (p.get("specifications") or {}).items()])
            is_amazon = p.get("store") == "amazon" or "amazon." in (p.get("url") or "")
            store_label = "Amazon" if is_amazon else "Noon"
            
            row = {
                "Store": store_label,
                "SKU_or_ASIN": p.get("sku"),
                "Name": p.get("name"),
                "Brand": p.get("brand"),
                "Category": p.get("category"),
                "Price": p.get("price"),
                "Original_Price": p.get("original_price"),
                "Discount": p.get("discount_percentage"),
                "Currency": p.get("currency"),
                "In_Stock": p.get("in_stock"),
                "Stock_Count": p.get("stock_count"),
                "Seller": p.get("seller"),
                "Rating": p.get("rating"),
                "Image_Count": p.get("image_count", len(images_list)),
            }
            # Dedicated column per image link
            for i in range(max_imgs):
                row[f"Image_{i+1}"] = images_list[i] if i < len(images_list) else ""

            row["Description"] = p.get("description", "").replace("\n", " ")
            row["Specifications"] = specs_str
            row["URL"] = p.get("url")
            row["Scrape_Time"] = p.get("scrape_time_seconds")
            rows.append(row)

        df = pd.DataFrame(rows)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")

    def export_to_json(self, products: List[Dict[str, Any]], filepath: str):
        """Exports to formatted JSON."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
