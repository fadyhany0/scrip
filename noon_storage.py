import sqlite3
import json
import os
import re
import time
from typing import Dict, List, Set, Any, Optional
import pandas as pd

ILLEGAL_XML_CHARS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")

def sanitize_text(val: Any) -> Any:
    """Strips non-printable control characters that are illegal in Excel XML worksheets."""
    if isinstance(val, str):
        return ILLEGAL_XML_CHARS_RE.sub("", val)
    return val

class NoonStorage:
    """
    High-performance SQLite storage for Noon Turbo Scraper.
    Supports checkpoints, resuming, thread-safe WAL mode, and export to Excel/CSV/JSON.
    """
    def __init__(self, db_path: str = "noon_products.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    sku TEXT PRIMARY KEY,
                    store TEXT,
                    name TEXT,
                    brand TEXT,
                    category TEXT,
                    price REAL,
                    original_price REAL,
                    discount_percentage REAL,
                    currency TEXT,
                    in_stock INTEGER,
                    stock_count INTEGER,
                    seller TEXT,
                    rating REAL,
                    rating_count INTEGER,
                    description TEXT,
                    specifications_json TEXT,
                    images_json TEXT,
                    image_count INTEGER,
                    url TEXT,
                    scrape_time_seconds REAL,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            try:
                conn.execute("ALTER TABLE products ADD COLUMN store TEXT;")
            except Exception:
                pass
            conn.commit()

    def save_product(self, p: Dict[str, Any]):
        """Saves or updates a single product record."""
        if not p or p.get("status") != "success" or not p.get("sku"):
            return
        # Do not save or overwrite with empty product names
        name = (p.get("name") or "").strip()
        if not name:
            return

        specs_json = json.dumps(p.get("specifications") or {}, ensure_ascii=False)
        images_json = json.dumps(p.get("images") or [], ensure_ascii=False)

        store_name = p.get("store") or ("amazon" if "amazon." in (p.get("url") or "") else "noon")
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO products (
                    sku, store, name, brand, category, price, original_price, discount_percentage,
                    currency, in_stock, stock_count, seller, rating, rating_count,
                    description, specifications_json, images_json, image_count, url, scrape_time_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    store = excluded.store,
                    name = excluded.name,
                    brand = excluded.brand,
                    category = excluded.category,
                    price = excluded.price,
                    original_price = excluded.original_price,
                    discount_percentage = excluded.discount_percentage,
                    currency = excluded.currency,
                    in_stock = excluded.in_stock,
                    stock_count = excluded.stock_count,
                    seller = excluded.seller,
                    rating = excluded.rating,
                    rating_count = excluded.rating_count,
                    description = excluded.description,
                    specifications_json = excluded.specifications_json,
                    images_json = excluded.images_json,
                    image_count = excluded.image_count,
                    url = excluded.url,
                    scrape_time_seconds = excluded.scrape_time_seconds;
            """, (
                p.get("sku"),
                store_name,
                p.get("name"),
                p.get("brand"),
                p.get("category"),
                p.get("price"),
                p.get("original_price"),
                p.get("discount_percentage"),
                p.get("currency"),
                1 if p.get("in_stock") else 0,
                p.get("stock_count"),
                p.get("seller"),
                p.get("rating"),
                p.get("rating_count"),
                p.get("description"),
                specs_json,
                images_json,
                p.get("image_count", 0),
                p.get("url"),
                p.get("scrape_time_seconds", 0.0)
            ))
            conn.commit()

    def get_scraped_skus(self) -> Set[str]:
        """Returns set of all SKUs already present in database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sku FROM products")
            return {row[0] for row in cursor.fetchall()}

    def get_count(self) -> int:
        """Returns total products count in database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            return cursor.fetchone()[0]

    def get_all_products(self) -> List[Dict[str, Any]]:
        """Retrieves all products as dictionary objects."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products ORDER BY scraped_at DESC")
            rows = cursor.fetchall()
            
            results = []
            for r in rows:
                p = dict(r)
                p["status"] = "success"
                p["in_stock"] = bool(p.get("in_stock"))
                try:
                    p["specifications"] = json.loads(p.get("specifications_json") or "{}")
                except:
                    p["specifications"] = {}
                try:
                    p["images"] = json.loads(p.get("images_json") or "[]")
                except:
                    p["images"] = []
                results.append(p)
            return results

    def export_to_excel(self, filepath: str):
        """Exports all database records to an Excel (.xlsx) file with a dedicated column per image."""
        products = self.get_all_products()
        if not products:
            return None

        max_imgs = max([len(p.get("images", [])) for p in products] or [1])

        rows = []
        for p in products:
            images_list = p.get("images") or []
            specs_str = " | ".join([f"{k}: {v}" for k, v in (p.get("specifications") or {}).items()])
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
        return filepath

    def export_to_csv(self, filepath: str):
        """Exports all database records to CSV (UTF-8 BOM) with dedicated image columns."""
        products = self.get_all_products()
        if not products:
            return None

        max_imgs = max([len(p.get("images", [])) for p in products] or [1])

        rows = []
        for p in products:
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
        return filepath

    def export_to_json(self, filepath: str):
        """Exports all database records to JSON."""
        products = self.get_all_products()
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
        return filepath
