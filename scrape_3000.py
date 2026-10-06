import argparse
import sys
import os
import time
from typing import List, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
from tqdm import tqdm

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from noon_core import NoonScraper
from amazon_core import AmazonScraper
from noon_storage import NoonStorage

POPULAR_CATEGORIES = [
    "electronics-and-mobiles",
    "beauty-and-health",
    "home-and-kitchen",
    "fashion",
    "supermarket",
    "sports-and-outdoors",
    "baby-products"
]

def harvest_skus_parallel(categories: List[str], target_count: int = 3000, country: str = "eg", lang: str = "en") -> List[str]:
    """
    Harvests up to target_count unique SKUs rapidly using parallel page requests.
    """
    collected_skus: Set[str] = set()
    locale = f"{lang}-{country}"
    
    # Calculate pages needed across selected categories
    # Each page returns 50 products
    pages_per_cat = max(10, (target_count // 50 // len(categories)) + 5)
    
    tasks = []
    for cat in categories:
        for p in range(1, min(pages_per_cat + 1, 51)): # Noon limits to page 50
            tasks.append((cat, p))
            
    print(f"🔍 Harvesting up to {target_count} product SKUs from {len(categories)} category(s)...")
    
    def fetch_page(cat, page_num):
        url = f"https://www.noon.com/_svc/catalog/api/search?category={cat}&limit=50&page={page_num}"
        headers = {"x-locale": locale, "x-platform": "web"}
        try:
            r = requests.get(url, headers=headers, impersonate="chrome124", timeout=7)
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                return [h["sku"] for h in hits if h.get("sku")]
        except Exception:
            pass
        return []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_page, c, p) for c, p in tasks]
        for fut in as_completed(futures):
            skus = fut.result()
            for s in skus:
                collected_skus.add(s)
                if len(collected_skus) >= target_count:
                    break
            if len(collected_skus) >= target_count:
                # Cancel remaining
                break

    return list(collected_skus)[:target_count]

def harvest_skus_by_keywords(keywords: List[str], target_count: int = 3000, country: str = "eg", lang: str = "en") -> List[str]:
    """
    Harvests SKUs matching a list of search keywords.
    """
    collected_skus: Set[str] = set()
    locale = f"{lang}-{country}"
    
    print(f"🔍 Harvesting up to {target_count} SKUs using {len(keywords)} search keyword(s)...")
    
    def fetch_search_page(kw, page_num):
        url = f"https://www.noon.com/_svc/catalog/api/search?q={kw}&limit=50&page={page_num}"
        headers = {"x-locale": locale, "x-platform": "web"}
        try:
            r = requests.get(url, headers=headers, impersonate="chrome124", timeout=7)
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                return [h["sku"] for h in hits if h.get("sku")]
        except Exception:
            pass
        return []

    tasks = []
    for kw in keywords:
        for p in range(1, 15):
            tasks.append((kw.strip(), p))

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_search_page, k, p) for k, p in tasks]
        for fut in as_completed(futures):
            skus = fut.result()
            for s in skus:
                collected_skus.add(s)
                if len(collected_skus) >= target_count:
                    break
            if len(collected_skus) >= target_count:
                break

    return list(collected_skus)[:target_count]

def main():
    parser = argparse.ArgumentParser(
        description="⚡ Noon Mass Scraper Pro - Scrapes 3,000+ products in minutes with auto-resume",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Scrape 3,000 products from Electronics & Mobiles into Excel:
  python scrape_3000.py --target 3000 --category electronics-and-mobiles --output noon_3000.xlsx

  # 2. Scrape 3,000 products across ALL main categories with 12 workers:
  python scrape_3000.py --target 3000 --category all --workers 12

  # 3. Scrape 3,000 products using search keywords:
  python scrape_3000.py --target 3000 --keywords "iphone,samsung,laptop,nike,perfume,watch"

  # 4. Scrape from a file of 3,000 URLs:
  python scrape_3000.py --file my_3000_urls.txt --workers 15
        """
    )

    parser.add_argument("--store", "-s", default="noon", choices=["noon", "amazon"], help="Store to scrape (default: noon)")
    parser.add_argument("--target", "-t", type=int, default=3000, help="Target number of products to scrape (default: 3000)")
    parser.add_argument("--category", "-c", default="all", help="Category code or 'all' for multi-department (default: all)")
    parser.add_argument("--keywords", "-k", help="Comma-separated search keywords (e.g. 'iphone,laptop,perfume')")
    parser.add_argument("--file", "-f", help="Text file containing 3,000 URLs or SKUs")
    parser.add_argument("--country", default="eg", choices=["eg", "sa", "ae", "kw", "qa", "bh"], help="Country code (default: eg - Egypt)")
    parser.add_argument("--lang", default="en", choices=["ar", "en"], help="Language (default: en - English)")
    parser.add_argument("--workers", "-w", type=int, default=12, help="Number of concurrent scraper threads (default: 12)")
    parser.add_argument("--output", "-o", default="exports/products_3000.xlsx", help="Output Excel file path")
    parser.add_argument("--db", default="exports/products_3000.db", help="SQLite checkpoint database path")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh instead of resuming from SQLite database")

    args = parser.parse_args()

    # 1. Initialize Storage & Scrapers
    storage = NoonStorage(db_path=args.db)
    noon_scraper = NoonScraper(default_country=args.country, default_lang=args.lang)
    amazon_scraper = AmazonScraper(default_country=args.country, default_lang=args.lang)

    already_scraped = set()
    if not args.no_resume:
        already_scraped = storage.get_scraped_skus()
        if already_scraped:
            print(f"📦 Found existing database '{args.db}' with {len(already_scraped):,} already scraped products!")

    # 2. Collect Target SKUs / URLs
    target_skus: List[str] = []
    t_start_harvest = time.time()

    if args.file:
        if not os.path.exists(args.file):
            print(f"❌ Error: File '{args.file}' not found.")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            raw_lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        for line in raw_lines:
            target_skus.append(line)
        print(f"📄 Loaded {len(target_skus):,} targets from {args.file}")

    elif args.store == "amazon":
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else None
        target_skus = amazon_scraper.harvest_parallel(
            keywords=kw_list,
            category=args.category,
            target_count=args.target,
            country=args.country
        )

    elif args.keywords:
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()]
        target_skus = harvest_skus_by_keywords(kw_list, target_count=args.target, country=args.country, lang=args.lang)

    else:
        # Noon Category mode
        cat_list = POPULAR_CATEGORIES if args.category == "all" else [args.category]
        target_skus = harvest_skus_parallel(cat_list, target_count=args.target, country=args.country, lang=args.lang)

    harvest_dur = time.time() - t_start_harvest
    print(f"✅ Loaded {len(target_skus):,} product targets in {harvest_dur:.2f} seconds!")

    # Filter out already scraped SKUs
    import re
    def get_key(t):
        asin_m = re.search(r'/(?:dp|gp/product|gp/aw/d|d|product)/([A-Z0-9]{10})', t, re.I)
        if asin_m: return asin_m.group(1).upper()
        raw_asin = re.search(r'\b(B[0-9A-Z]{9})\b', t, re.I)
        if raw_asin: return raw_asin.group(1).upper()
        sku_m = re.search(r'\b(N[0-9A-Z]{7,12}[A-Z]?)\b', t, re.I)
        if sku_m: return sku_m.group(1).upper()
        return t

    remaining_skus = [s for s in target_skus if get_key(s) not in already_scraped]
    print(f"🚀 Total to scrape: {len(remaining_skus):,} new products (Already completed: {len(already_scraped):,}).")

    if not remaining_skus:
        print("🎉 All requested products are already scraped in the database!")
        print(f"📊 Exporting current database ({storage.get_count()} products) to: {args.output}...")
        storage.export_to_excel(args.output)
        csv_path = args.output.replace(".xlsx", ".csv")
        storage.export_to_csv(csv_path)
        print(f"💾 Files ready:\n  - Excel: {os.path.abspath(args.output)}\n  - CSV:   {os.path.abspath(csv_path)}")
        sys.exit(0)

    # 3. High-Speed Multi-Threaded Scraping with Progress Bar & Instant Commit
    print(f"\n⚡ Starting turbo scraping with {args.workers} concurrent workers...")
    t_start_scrape = time.time()
    success_count = 0
    fail_count = 0

    def scrape_and_save(target):
        t = target.strip()
        t_lower = t.lower()
        if "amazon." in t_lower or "amzn." in t_lower or "a.co/" in t_lower or re.search(r'\bB[0-9A-Z]{9}\b', t, re.I):
            res = amazon_scraper.scrape_product(t, country=args.country, lang=args.lang)
        else:
            res = noon_scraper.scrape_product(t, country=args.country, lang=args.lang)
        if res.get("status") == "success" and (res.get("name") or "").strip():
            storage.save_product(res)
            return True, target, res
        return False, target, res

    with tqdm(total=len(remaining_skus), desc="Scraping Catalog", unit="product", dynamic_ncols=True) as pbar:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(scrape_and_save, item): item for item in remaining_skus}
            
            for future in as_completed(futures):
                is_success, sku, data = future.result()
                if is_success:
                    success_count += 1
                else:
                    fail_count += 1
                
                # Update progress bar description with speed
                elapsed = time.time() - t_start_scrape
                speed = (success_count + fail_count) / elapsed if elapsed > 0 else 0
                pbar.set_postfix({
                    "Success": success_count,
                    "Speed": f"{speed:.1f}/s",
                    "Saved to DB": storage.get_count()
                })
                pbar.update(1)

    total_scrape_time = time.time() - t_start_scrape
    total_in_db = storage.get_count()
    avg_speed = (success_count / total_scrape_time) if total_scrape_time > 0 else 0

    print("\n" + "=" * 60)
    print(f"🎉 Scraping Finished in {total_scrape_time:.2f} seconds ({total_scrape_time / 60:.2f} minutes)!")
    print(f"📈 Total in Database: {total_in_db} products")
    print(f"⚡ Average Speed:     {avg_speed:.2f} products / second")
    print("=" * 60)

    # 4. Automatic Export to Excel and CSV
    print(f"\n📊 Exporting {total_in_db} products to Excel ({args.output})...")
    storage.export_to_excel(args.output)
    
    csv_path = args.output.replace(".xlsx", ".csv")
    print(f"📄 Exporting to CSV ({csv_path})...")
    storage.export_to_csv(csv_path)

    json_path = args.output.replace(".xlsx", ".json")
    print(f"🗄️ Exporting to JSON ({json_path})...")
    storage.export_to_json(json_path)

    print("\n" + "✨" * 30)
    print(f"✅ تم الانتهاء بنجاح! تم حفظ وسحب البيانات بالكامل:")
    print(f"  📊 ملف Excel: {os.path.abspath(args.output)}")
    print(f"  📄 ملف CSV:   {os.path.abspath(csv_path)}")
    print(f"  🗄️ ملف JSON:  {os.path.abspath(json_path)}")
    print(f"  💾 قاعدة البيانات (SQLite): {os.path.abspath(args.db)}")
    print("✨" * 30)

if __name__ == "__main__":
    main()
