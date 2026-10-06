import argparse
import sys
import os
import json
import re
import time

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from noon_core import NoonScraper
from amazon_core import AmazonScraper

def main():
    parser = argparse.ArgumentParser(
        description="Turbo E-commerce Scraper - Fast product scraper for Noon & Amazon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape a single Noon URL:
  python noon_cli.py --url "https://www.noon.com/egypt-en/106-dual-sim-dark-grey-4mb-2g/N20985583A/p/"

  # Scrape a single Amazon URL:
  python noon_cli.py --url "https://www.amazon.eg/-/en/dp/B0BDHWDR12"

  # Scrape an Amazon ASIN directly:
  python noon_cli.py --sku B0BDHWDR12 --store amazon --country eg

  # Scrape multiple URLs (mixed Noon + Amazon) from a file:
  python noon_cli.py --file urls.txt --export excel --output products.xlsx

  # Search Noon and export:
  python noon_cli.py --search "airpods" --limit 10 --country eg --export excel
        """
    )

    parser.add_argument("--url", "-u", help="Product URL to scrape (Noon or Amazon)")
    parser.add_argument("--sku", "-s", help="Product SKU (Noon) or ASIN (Amazon)")
    parser.add_argument("--store", choices=["auto", "noon", "amazon"], default="auto", help="Target store (default: auto-detect)")
    parser.add_argument("--file", "-f", help="File containing list of URLs/SKUs (one per line)")
    parser.add_argument("--search", "-q", help="Search keyword on Noon / Bestsellers category on Amazon")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Search limit (default: 10)")
    parser.add_argument("--country", "-c", default="eg", choices=["eg", "ae", "sa", "kw", "qa", "bh", "us"], help="Country code (default: eg - Egypt)")
    parser.add_argument("--lang", default="en", choices=["en", "ar"], help="Language (default: en - English)")
    parser.add_argument("--workers", "-w", type=int, default=5, help="Number of concurrent workers for batch (default: 5)")
    parser.add_argument("--export", choices=["excel", "csv", "json"], default="excel", help="Export format (default: excel)")
    parser.add_argument("--output", "-o", help="Output file path (e.g. products.xlsx)")
    parser.add_argument("--download-images", action="store_true", help="Download all images to disk")
    parser.add_argument("--output-dir", default="downloads", help="Directory for downloaded images and exports")

    args = parser.parse_args()

    noon_scraper = NoonScraper(default_country=args.country, default_lang=args.lang)
    amazon_scraper = AmazonScraper(default_country=args.country, default_lang=args.lang)

    def scrape_single(target, store_choice):
        t = target.strip()
        is_amazon = False
        if store_choice == "amazon":
            is_amazon = True
        elif store_choice == "noon":
            is_amazon = False
        else:
            t_lower = t.lower()
            if "amazon." in t_lower or "amzn." in t_lower or "a.co/" in t_lower or re.search(r'\bB[0-9A-Z]{9}\b', t, re.I):
                is_amazon = True
            else:
                is_amazon = False

        if is_amazon:
            return amazon_scraper.scrape_product(t, country=args.country, lang=args.lang)
        else:
            return noon_scraper.scrape_product(t, country=args.country, lang=args.lang)

    targets = []
    if args.url:
        targets.append(args.url)
    elif args.sku:
        targets.append(args.sku)
    elif args.file:
        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found.")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            targets = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"Loaded {len(targets)} targets from {args.file}")
    elif args.search:
        if args.store == "amazon":
            print(f"Harvesting Amazon bestsellers for '{args.search}' in country '{args.country.upper()}'...")
            targets = amazon_scraper.harvest_bestseller_asins(args.search, country=args.country)[:args.limit]
        else:
            print(f"Searching Noon for '{args.search}' in country '{args.country.upper()}' (limit: {args.limit})...")
            t0 = time.time()
            search_hits = noon_scraper.search_products(args.search, limit=args.limit, country=args.country, lang=args.lang)
            print(f"Found {len(search_hits)} items in {time.time() - t0:.2f}s!")
            targets = [h["sku"] for h in search_hits]
    else:
        parser.print_help()
        sys.exit(0)

    if not targets:
        print("No targets to scrape.")
        sys.exit(1)

    print(f"\n⚡ Starting Turbo Scraper for {len(targets)} item(s)...")
    t0 = time.time()

    if len(targets) == 1:
        product = scrape_single(targets[0], args.store)
        results = [product]
    else:
        results = [None] * len(targets)
        def worker(idx, tgt):
            res = scrape_single(tgt, args.store)
            status = "✓" if res.get("status") == "success" else "✗"
            print(f"[{idx+1}/{len(targets)}] {status} {res.get('sku')} | {res.get('scrape_time_seconds')}s | {res.get('name', '')[:35]}...")
            return idx, res

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(worker, i, t) for i, t in enumerate(targets)]
            for fut in as_completed(futures):
                i, res = fut.result()
                results[i] = res

    total_time = time.time() - t0
    success_count = sum(1 for r in results if r and r.get("status") == "success")
    avg_speed = round(total_time / len(targets), 3) if targets else 0

    print("\n" + "="*50)
    print(f"🎉 Scraping Finished in {total_time:.2f} seconds!")
    print(f"📊 Total Scraped: {len(results)} | Success: {success_count} | Average Speed: {avg_speed}s / product")
    print("="*50)

    if results and results[0] and results[0].get("status") == "success":
        p = results[0]
        print(f"\nSample Product Details:")
        print(f"  • Name:        {p.get('name')}")
        print(f"  • Store:       {p.get('store', 'noon').upper()}")
        print(f"  • SKU / ASIN:  {p.get('sku')}")
        print(f"  • Brand:       {p.get('brand')}")
        print(f"  • Price:       {p.get('price')} {p.get('currency')} (Original: {p.get('original_price')})")
        print(f"  • Stock:       {'In Stock' if p.get('in_stock') else 'Out of Stock'}")
        print(f"  • Images:      {p.get('image_count')} HD images")
        print(f"  • Description: {len(p.get('description', ''))} characters")

    # Image download if requested
    if args.download_images:
        print(f"\n🖼️ Downloading images for {success_count} products...")
        img_folder = os.path.join(args.output_dir, "images")
        for p in results:
            if p and p.get("status") == "success":
                dls = noon_scraper.download_product_images(p, output_folder=img_folder)
                print(f"  • Downloaded {len(dls)} images for {p.get('sku')}")

    # Export
    out_path = args.output
    if not out_path:
        out_ext = ".xlsx" if args.export == "excel" else (f".{args.export}")
        out_path = os.path.join(args.output_dir, f"scraped_products_{int(time.time())}{out_ext}")

    valid_results = [r for r in results if r]
    if args.export == "excel":
        noon_scraper.export_to_excel(valid_results, out_path)
    elif args.export == "csv":
        noon_scraper.export_to_csv(valid_results, out_path)
    elif args.export == "json":
        noon_scraper.export_to_json(valid_results, out_path)

    print(f"\n💾 Data saved successfully to: {os.path.abspath(out_path)}")

if __name__ == "__main__":
    main()
