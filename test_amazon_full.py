import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

from amazon_core import AmazonScraper
from noon_core import NoonScraper

scraper = AmazonScraper(default_country="eg", default_lang="en")

print("--- Testing Amazon Egypt Scrape ---")
p = scraper.scrape_product("https://www.amazon.eg/-/en/dp/B0BDHWDR12")
print("Status:", p.get("status"))
print("SKU / ASIN:", p.get("sku"))
print("Name:", p.get("name"))
print("Brand:", p.get("brand"))
print("Price:", p.get("price"), p.get("currency"), "(Original:", p.get("original_price"), ")")
print("Discount %:", p.get("discount_percentage"))
print("Images count:", p.get("image_count"))
print("Sample Master Images:")
for img in p.get("images", [])[:3]:
    print(" ", img)
print("Time taken:", p.get("scrape_time_seconds"), "seconds!")

# Test exporting using NoonScraper's export_to_excel (which works on ANY product dict!)
noon_scr = NoonScraper()
noon_scr.export_to_excel([p], "exports/test_amazon_excel.xlsx")
noon_scr.export_to_csv([p], "exports/test_amazon_csv.csv")
print("\nExported successfully to exports/test_amazon_excel.xlsx and exports/test_amazon_csv.csv!")
