import os
import re
import sys
import json
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Configure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

ILLEGAL_XML_CHARS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")
DIR_MARKS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\xa0]")

def sanitize_text(val):
    if isinstance(val, str):
        val = ILLEGAL_XML_CHARS_RE.sub("", val)
        val = DIR_MARKS_RE.sub(" ", val)
        return val.strip()
    return val

def clean_html_script(raw_html: str) -> str:
    if not raw_html:
        return ""
    # Parse HTML with BeautifulSoup
    soup = BeautifulSoup(raw_html, "lxml")
    
    # Replace breaks and paragraphs with newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all(["p", "div", "li"]):
        p.insert_after("\n")
        
    text = soup.get_text()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    exports_dir = os.path.join(base_dir, "exports")
    images_dir = os.path.join(exports_dir, "maskd_images")
    os.makedirs(exports_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    print("🚀 جاري الاتصال بمتجر MASKD وسحب جميع المنتجات...")
    url = "https://maskd-eg.com/products.json?limit=250&page=1"
    
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,ar;q=0.8",
    }
    
    res = requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
    if res.status_code != 200:
        print(f"❌ خطأ في الاتصال بالمتجر: رمز الاستجابة {res.status_code}")
        sys.exit(1)

    data = res.json()
    products = data.get("products", [])
    print(f"✅ تم العثور على {len(products)} منتج بنجاح!")

    parsed_products = []
    download_tasks = []

    for idx, p in enumerate(products, 1):
        title = sanitize_text(p.get("title", ""))
        handle = p.get("handle", "")
        product_url = f"https://maskd-eg.com/products/{handle}"
        body_html = p.get("body_html") or ""
        clean_script = clean_html_script(body_html)
        
        # Variants, pricing, sizes
        variants = p.get("variants") or []
        price_val = None
        compare_val = None
        available_status = False
        sizes_list = []
        
        if variants:
            v0 = variants[0]
            try:
                price_val = float(v0.get("price")) if v0.get("price") else None
            except:
                price_val = v0.get("price")
            try:
                compare_val = float(v0.get("compare_at_price")) if v0.get("compare_at_price") else None
            except:
                compare_val = None
                
            available_status = any(v.get("available", False) for v in variants)
            
            for v in variants:
                t = v.get("title")
                if t and t != "Default Title":
                    sizes_list.append(t)
        
        discount_pct = 0
        if compare_val and price_val and compare_val > price_val:
            discount_pct = round(((compare_val - price_val) / compare_val) * 100, 1)

        # Images
        raw_images = p.get("images") or []
        img_urls = [img.get("src") for img in raw_images if img.get("src")]

        # Prepare folder for product images
        prod_folder_name = f"{idx:02d}_{sanitize_filename(title)}"
        prod_img_dir = os.path.join(images_dir, prod_folder_name)
        os.makedirs(prod_img_dir, exist_ok=True)

        local_img_paths = []
        for img_idx, img_url in enumerate(img_urls, 1):
            clean_url = img_url.split("?")[0]
            ext = os.path.splitext(clean_url)[1] or ".jpg"
            img_filename = f"image_{img_idx:02d}{ext}"
            img_filepath = os.path.join(prod_img_dir, img_filename)
            rel_path = os.path.join("maskd_images", prod_folder_name, img_filename)
            local_img_paths.append(rel_path)
            download_tasks.append((img_url, img_filepath))

        parsed_products.append({
            "id": p.get("id"),
            "handle": handle,
            "title": title,
            "price": price_val,
            "original_price": compare_val,
            "discount_percentage": discount_pct,
            "currency": "EGP",
            "stock_status": "متوفر (In Stock)" if available_status else "نفذت الكمية (Out of Stock)",
            "product_type": sanitize_text(p.get("product_type") or "Wearable"),
            "tags": ", ".join(p.get("tags") or []),
            "sizes": ", ".join(sizes_list) if sizes_list else "مقاس موحد / قياسي",
            "clean_script": clean_script,
            "raw_html_script": sanitize_text(body_html),
            "product_url": product_url,
            "images_count": len(img_urls),
            "image_urls": img_urls,
            "local_images": local_img_paths
        })

    print(f"\n📥 جاري تحميل {len(download_tasks)} صورة بجودتها الأصلية الكاملة بالتوازي...")
    
    def download_image(task):
        img_url, filepath = task
        if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
            return True
        try:
            r = requests.get(img_url, impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            pass
        return False

    downloaded_count = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(download_image, t) for t in download_tasks]
        for fut in as_completed(futures):
            if fut.result():
                downloaded_count += 1
                if downloaded_count % 15 == 0 or downloaded_count == len(download_tasks):
                    print(f"  🖼️ تم تحميل {downloaded_count} من {len(download_tasks)} صورة...")

    print(f"✅ اكتمل تحميل {downloaded_count} صورة في مجلد: {images_dir}")

    # Build Excel and CSV Export Data
    max_images = max(p["images_count"] for p in parsed_products) if parsed_products else 1
    
    excel_rows = []
    for p in parsed_products:
        row = {
            "م": len(excel_rows) + 1,
            "اسم المنتج": p["title"],
            "السعر الحالي (EGP)": p["price"],
            "السعر قبل الخصم (EGP)": p["original_price"] if p["original_price"] else "",
            "نسبة الخصم %": f"{p['discount_percentage']}%" if p["discount_percentage"] > 0 else "0%",
            "العملة": p["currency"],
            "حالة التوفر": p["stock_status"],
            "المقاسات / المتغيرات": p["sizes"],
            "التصنيف": p["product_type"],
            "الكلمات الدلالية (Tags)": p["tags"],
            "الاسكربت / الوصف المنسق": p["clean_script"],
            "عدد الصور": p["images_count"],
        }

        # Dedicated column for each image URL
        for i in range(max_images):
            col_name = f"صورة {i+1} (الرئيسية)" if i == 0 else f"صورة {i+1}"
            row[col_name] = p["image_urls"][i] if i < len(p["image_urls"]) else ""

        # Local image path columns
        for i in range(max_images):
            col_name = f"مسار الصورة المحلية {i+1}"
            row[col_name] = p["local_images"][i] if i < len(p["local_images"]) else ""

        row["رابط المنتج المباشر"] = p["product_url"]
        row["كود الاسكربت الخام (HTML)"] = p["raw_html_script"]
        
        excel_rows.append(row)

    df = pd.DataFrame(excel_rows)
    
    # 1. Export Excel (.xlsx) with Professional Styling
    excel_file = os.path.join(exports_dir, "maskd_products.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MASKD Products"
    ws.views.sheetView[0].rightToLeft = True  # Arabic Right-to-Left orientation

    headers = list(excel_rows[0].keys())
    ws.append(headers)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    border_thin = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB")
    )

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border_thin

    ws.row_dimensions[1].height = 28

    zebra_fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
    regular_font = Font(name="Calibri", size=10)

    for row_idx, r in enumerate(excel_rows, 2):
        for col_idx, col_name in enumerate(headers, 1):
            val = r[col_name]
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = border_thin
            
            # Alignments
            if col_name in ["م", "السعر الحالي (EGP)", "السعر قبل الخصم (EGP)", "نسبة الخصم %", "العملة", "حالة التوفر", "عدد الصور"]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif "صورة" in col_name or "مسار" in col_name or "رابط" in col_name:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            elif "الاسكربت" in col_name:
                cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")

            if row_idx % 2 == 0:
                cell.fill = zebra_fill
        ws.row_dimensions[row_idx].height = 45

    # Auto-fit column widths
    for col in ws.columns:
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        col_name = str(col[0].value or "")
        if "الاسكربت" in col_name:
            ws.column_dimensions[col_letter].width = 45
        elif "اسم المنتج" in col_name:
            ws.column_dimensions[col_letter].width = 30
        elif "صورة" in col_name or "رابط" in col_name or "مسار" in col_name:
            ws.column_dimensions[col_letter].width = 32
        elif "م" == col_name:
            ws.column_dimensions[col_letter].width = 6
        else:
            ws.column_dimensions[col_letter].width = 18

    wb.save(excel_file)
    print(f"📊 تم تصدير ملف الإكسيل بنجاح: {excel_file}")

    # 2. Export CSV (.csv)
    csv_file = os.path.join(exports_dir, "maskd_products.csv")
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"📄 تم تصدير ملف CSV بنجاح: {csv_file}")

    # 3. Export JSON (.json)
    json_file = os.path.join(exports_dir, "maskd_products.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(parsed_products, f, ensure_ascii=False, indent=2)
    print(f"💾 تم تصدير ملف JSON بنجاح: {json_file}")

    print("\n🎉 تم الانتهاء بنجاح تام من استخراج كافة البيانات والصور!")

if __name__ == "__main__":
    main()
