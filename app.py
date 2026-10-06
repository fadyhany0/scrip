import os
import time
import uuid
import json
import re
import threading
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor, as_completed

from noon_core import NoonScraper
from amazon_core import AmazonScraper
from noon_storage import NoonStorage
import scrape_3000

app = FastAPI(title="Turbo E-commerce Scraper (Noon & Amazon)", description="High-Speed Scraper for Noon and Amazon")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

noon_scraper = NoonScraper()
amazon_scraper = AmazonScraper()
global_storage = NoonStorage(os.path.join(EXPORTS_DIR, "catalog_database.db"))

def detect_store(target: str, store_preference: str = "auto") -> str:
    target = target.strip()
    if store_preference == "amazon":
        return "amazon"
    elif store_preference == "noon":
        return "noon"
    
    # Auto-detection for Amazon (handles domains, short URLs amzn.to/amzn.eu/a.co, and ASINs)
    t_lower = target.lower()
    if "amazon." in t_lower or "amzn." in t_lower or "a.co/" in t_lower or re.search(r'\bB[0-9A-Z]{9}\b', target, re.I):
        return "amazon"
    return "noon"

def scrape_any(target: str, store: str = "auto", country: str = "eg", lang: str = "en") -> dict:
    detected = detect_store(target, store)
    if detected == "amazon":
        res = amazon_scraper.scrape_product(target, country=country, lang=lang)
    else:
        res = noon_scraper.scrape_product(target, country=country, lang=lang)
    
    if res.get("status") == "success" and (res.get("name") or "").strip():
        global_storage.save_product(res)
    return res

# Global Mass Job State
mass_job_lock = threading.Lock()
mass_job_state = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "speed": "0/s",
    "saved": 0,
    "elapsed": 0.0,
    "message": "",
    "excel_path": "",
    "csv_path": ""
}

# Global Large Batch Job State (Handles 100 to 50,000+ URLs safely)
batch_job_lock = threading.Lock()
batch_job_stop_flag = threading.Event()
batch_job_state = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "speed": "0/s",
    "saved": 0,
    "elapsed": 0.0,
    "eta": "",
    "message": "",
    "excel_path": "",
    "csv_path": "",
    "recent_products": []
}

class SingleScrapeRequest(BaseModel):
    target: str
    store: Optional[str] = "auto" # "auto", "noon", "amazon"
    country: Optional[str] = "eg"
    lang: Optional[str] = "en"

class BatchScrapeRequest(BaseModel):
    targets: List[str]
    store: Optional[str] = "auto"
    country: Optional[str] = "eg"
    lang: Optional[str] = "en"
    workers: Optional[int] = 12

class SearchRequest(BaseModel):
    query: str
    store: Optional[str] = "noon"
    country: Optional[str] = "eg"
    lang: Optional[str] = "en"
    limit: Optional[int] = 12

class ExportRequest(BaseModel):
    products: List[dict]
    format: str

class MassScrapeRequest(BaseModel):
    target_count: Optional[int] = 3000
    store: Optional[str] = "noon"
    category: Optional[str] = "all"
    keywords: Optional[str] = None
    country: Optional[str] = "eg"
    lang: Optional[str] = "en"
    workers: Optional[int] = 12

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(BASE_DIR, "templates", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Scraper UI is loading...</h1>"

@app.post("/api/scrape/single")
async def scrape_single_product(req: SingleScrapeRequest):
    if not req.target or not req.target.strip():
        raise HTTPException(status_code=400, detail="الرجاء إدخال رابط أو كود المنتج (SKU / ASIN).")
    
    result = scrape_any(req.target.strip(), store=req.store, country=req.country, lang=req.lang)
    return result

def _run_batch_job(cleaned: List[str], store: str, country: str, lang: str, workers: int):
    global batch_job_state
    batch_job_stop_flag.clear()
    total = len(cleaned)
    t0 = time.time()
    completed = 0
    saved = 0
    recent = []

    with batch_job_lock:
        batch_job_state["status"] = "scraping"
        batch_job_state["total"] = total
        batch_job_state["progress"] = 0
        batch_job_state["saved"] = 0
        batch_job_state["speed"] = "0/s"
        batch_job_state["elapsed"] = 0.0
        batch_job_state["eta"] = ""
        batch_job_state["message"] = f"Scraping {total:,} products..."
        batch_job_state["recent_products"] = []
        batch_job_state["excel_path"] = ""
        batch_job_state["csv_path"] = ""

    def worker(target):
        if batch_job_stop_flag.is_set():
            return None
        return scrape_any(target, store=store, country=country, lang=lang)

    with ThreadPoolExecutor(max_workers=min(workers or 15, 25)) as executor:
        futures = {executor.submit(worker, tgt): tgt for tgt in cleaned}
        for fut in as_completed(futures):
            if batch_job_stop_flag.is_set():
                break
            try:
                res = fut.result()
                if res and res.get("status") == "success":
                    saved += 1
                    if len(recent) < 15:
                        recent.insert(0, res)
                    else:
                        recent.pop()
                        recent.insert(0, res)
            except Exception:
                pass
            completed += 1
            now = time.time()
            elapsed = now - t0
            speed_val = (completed / elapsed) if elapsed > 0 else 0
            rem_items = max(0, total - completed)
            eta_secs = int(rem_items / speed_val) if speed_val > 0 else 0
            m, s = divmod(eta_secs, 60)
            h, m = divmod(m, 60)
            eta_str = f"{h:d}h {m:02d}m {s:02d}s" if h > 0 else (f"{m:d}m {s:02d}s" if m > 0 else f"{s:d}s")

            if completed % 5 == 0 or completed == total:
                with batch_job_lock:
                    batch_job_state["progress"] = completed
                    batch_job_state["saved"] = saved
                    batch_job_state["elapsed"] = round(elapsed, 1)
                    batch_job_state["speed"] = f"{speed_val:.1f} /s"
                    batch_job_state["eta"] = eta_str
                    batch_job_state["recent_products"] = list(recent)
                    batch_job_state["message"] = f"Scraped {completed:,} of {total:,} products ({speed_val:.1f}/s)"

    # Automatically export to Excel and CSV when finished
    excel_path = os.path.join(EXPORTS_DIR, f"batch_{total}_products.xlsx")
    csv_path = os.path.join(EXPORTS_DIR, f"batch_{total}_products.csv")
    global_storage.export_to_excel(excel_path)
    global_storage.export_to_csv(csv_path)

    with batch_job_lock:
        batch_job_state["status"] = "completed" if not batch_job_stop_flag.is_set() else "stopped"
        batch_job_state["progress"] = completed
        batch_job_state["saved"] = saved
        batch_job_state["excel_path"] = excel_path
        batch_job_state["csv_path"] = csv_path
        batch_job_state["message"] = f"Finished scraping {saved:,} of {total:,} products in {int(time.time() - t0)}s!"

@app.post("/api/scrape/batch")
async def scrape_batch_products(req: BatchScrapeRequest, background_tasks: BackgroundTasks):
    cleaned = [t.strip() for t in req.targets if t.strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="الرجاء تقديم قائمة روابط أو أكواد SKU / ASIN.")
    
    # If 30 or fewer targets, run synchronously
    if len(cleaned) <= 30:
        t0 = time.time()
        workers = min(req.workers or 10, 15)
        results = [None] * len(cleaned)

        def worker(idx, target):
            res = scrape_any(target, store=req.store, country=req.country, lang=req.lang)
            return idx, res

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker, i, t) for i, t in enumerate(cleaned)]
            for fut in as_completed(futures):
                i, res = fut.result()
                results[i] = res

        total_time = round(time.time() - t0, 3)
        success_count = sum(1 for r in results if r.get("status") == "success")
        avg_speed = round(total_time / len(cleaned), 3) if cleaned else 0
        
        return {
            "status": "success",
            "mode": "sync",
            "total": len(results),
            "success_count": success_count,
            "total_time_seconds": total_time,
            "average_speed_seconds": avg_speed,
            "products": results
        }
    
    # For large batches (31 to 50,000+ items, such as 37,000 URLs), run asynchronously!
    with batch_job_lock:
        if batch_job_state["status"] == "scraping":
            return {"status": "already_running", "message": "يوجد سحب جماعي جاري بالفعل حالياً."}
        batch_job_state["status"] = "starting"
        batch_job_state["total"] = len(cleaned)
        batch_job_state["progress"] = 0
        batch_job_state["saved"] = 0
        batch_job_state["message"] = f"بدء سحب {len(cleaned):,} منتج بالتوازي..."

    workers = min(req.workers or 15, 25)
    background_tasks.add_task(_run_batch_job, cleaned, req.store, req.country, req.lang, workers)
    
    return {
        "status": "started_async",
        "mode": "async",
        "total": len(cleaned),
        "message": f"تم إطلاق مهمة سحب {len(cleaned):,} منتج بالتوازي على {workers} مساراً في الخلفية مع الحفظ التلقائي في SQLite."
    }

@app.get("/api/scrape/batch/status")
async def get_batch_status():
    with batch_job_lock:
        return dict(batch_job_state)

@app.post("/api/scrape/batch/stop")
async def stop_batch_scrape():
    batch_job_stop_flag.set()
    return {"status": "stopping", "message": "تم إرسال أمر إيقاف السحب الجماعي. سيتم تصدير كل ما تم سحبه حتى الآن."}

@app.get("/api/scrape/batch/download/{fmt}")
async def download_batch_file(fmt: str):
    with batch_job_lock:
        if fmt == "excel" and batch_job_state.get("excel_path") and os.path.exists(batch_job_state["excel_path"]):
            return FileResponse(batch_job_state["excel_path"], filename=os.path.basename(batch_job_state["excel_path"]))
        elif fmt == "csv" and batch_job_state.get("csv_path") and os.path.exists(batch_job_state["csv_path"]):
            return FileResponse(batch_job_state["csv_path"], filename=os.path.basename(batch_job_state["csv_path"]))
        else:
            # Fallback to current database
            if fmt == "excel":
                path = os.path.join(EXPORTS_DIR, "catalog_current_database.xlsx")
                global_storage.export_to_excel(path)
                return FileResponse(path, filename="products_export.xlsx")
            elif fmt == "csv":
                path = os.path.join(EXPORTS_DIR, "catalog_current_database.csv")
                global_storage.export_to_csv(path)
                return FileResponse(path, filename="products_export.csv")
    raise HTTPException(status_code=404, detail="الملف غير متوفر بعد.")

@app.post("/api/scrape/batch/upload")
async def upload_batch_file(file: UploadFile = File(...)):
    filename = file.filename or ""
    content = await file.read()
    targets = []
    
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        import io
        import pandas as pd
        df = pd.read_excel(io.BytesIO(content))
        # Look for URL or SKU column
        for col in df.columns:
            col_lower = str(col).lower()
            if "url" in col_lower or "link" in col_lower or "sku" in col_lower or "asin" in col_lower or "رابط" in col_lower:
                targets = [str(x).strip() for x in df[col].dropna() if str(x).strip()]
                break
        if not targets and len(df.columns) > 0:
            targets = [str(x).strip() for x in df.iloc[:, 0].dropna() if str(x).strip()]
    else:
        text = content.decode("utf-8", errors="ignore")
        targets = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        
    return {
        "status": "success",
        "filename": filename,
        "count": len(targets),
        "targets": targets
    }

@app.post("/api/search")
async def search_store(req: SearchRequest):
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="الرجاء إدخال كلمة البحث أو القسم.")
    
    q = req.query.strip().lower()
    
    if req.store == "amazon":
        # Amazon bestsellers harvest
        asins = amazon_scraper.harvest_bestseller_asins(q if q in ["electronics", "computers", "kitchen", "beauty", "fashion", "grocery", "sports"] else "electronics", country=req.country)
        results = [{"sku": a, "name": f"Amazon ASIN: {a}", "price": "", "brand": "Amazon", "image": "", "url": f"https://www.{amazon_scraper._get_domain(req.country)}/dp/{a}"} for a in asins[:req.limit or 24]]
        return {
            "status": "success",
            "count": len(results),
            "results": results
        }
    else:
        hits = noon_scraper.search_products(
            req.query.strip(), 
            limit=min(req.limit or 12, 50), 
            country=req.country, 
            lang=req.lang
        )
        return {
            "status": "success",
            "count": len(hits),
            "results": hits
        }

@app.post("/api/export")
async def export_data(req: ExportRequest):
    if not req.products:
        raise HTTPException(status_code=400, detail="لا توجد بيانات لتصديرها.")
    
    export_id = uuid.uuid4().hex[:8]
    fmt = req.format.lower()
    
    if fmt == "excel":
        filename = f"products_export_{export_id}.xlsx"
        filepath = os.path.join(EXPORTS_DIR, filename)
        noon_scraper.export_to_excel(req.products, filepath)
        return FileResponse(filepath, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
    elif fmt == "csv":
        filename = f"products_export_{export_id}.csv"
        filepath = os.path.join(EXPORTS_DIR, filename)
        noon_scraper.export_to_csv(req.products, filepath)
        return FileResponse(filepath, filename=filename, media_type="text/csv")
        
    elif fmt == "json":
        filename = f"products_export_{export_id}.json"
        filepath = os.path.join(EXPORTS_DIR, filename)
        noon_scraper.export_to_json(req.products, filepath)
        return FileResponse(filepath, filename=filename, media_type="application/json")
        
    elif fmt == "images_zip":
        filename = f"products_images_{export_id}.zip"
        filepath = os.path.join(EXPORTS_DIR, filename)
        noon_scraper.create_images_zip(req.products, filepath)
        return FileResponse(filepath, filename=filename, media_type="application/zip")
        
    else:
        raise HTTPException(status_code=400, detail="صيغة التصدير غير مدعومة.")

# Background thread runner for Mass Scraping
def _run_mass_job(req: MassScrapeRequest):
    global mass_job_state
    try:
        store_label = "أمازون" if req.store == "amazon" else "نون"
        with mass_job_lock:
            mass_job_state["status"] = "harvesting"
            mass_job_state["message"] = f"جاري جمع أكواد {req.target_count} منتج من {store_label}..."
            mass_job_state["progress"] = 0
            mass_job_state["total"] = req.target_count
            mass_job_state["saved"] = 0

        target_skus = []
        kw_list = [k.strip() for k in req.keywords.split(",") if k.strip()] if req.keywords else None

        if req.store == "amazon":
            target_skus = amazon_scraper.harvest_parallel(
                keywords=kw_list,
                category=req.category,
                target_count=req.target_count,
                country=req.country
            )
        else:
            if kw_list:
                target_skus = scrape_3000.harvest_skus_by_keywords(kw_list, target_count=req.target_count, country=req.country, lang=req.lang)
            else:
                cat_list = scrape_3000.POPULAR_CATEGORIES if req.category == "all" else [req.category]
                target_skus = scrape_3000.harvest_skus_parallel(cat_list, target_count=req.target_count, country=req.country, lang=req.lang)

        if not target_skus:
            with mass_job_lock:
                mass_job_state["status"] = "error"
                mass_job_state["message"] = "لم يتم العثور على أي منتجات مطابقة لخيارات البحث المحددة."
            return

        with mass_job_lock:
            mass_job_state["status"] = "scraping"
            mass_job_state["total"] = len(target_skus)
            if len(target_skus) < req.target_count and kw_list:
                mass_job_state["message"] = f"تم تجميع كافة المنتجات المتاحة لكلمات البحث ({len(target_skus)} منتج). بدء سحب التفاصيل بالتوازي..."
            else:
                mass_job_state["message"] = f"بدء سحب تفاصيل {len(target_skus)} منتج بالتوازي..."

        t0 = time.time()
        completed = 0
        workers = min(req.workers or 12, 16)

        def worker_task(sku):
            res = scrape_any(sku, store=req.store, country=req.country, lang=req.lang)
            return res

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker_task, s) for s in target_skus]
            for fut in as_completed(futures):
                fut.result()
                completed += 1
                elapsed = time.time() - t0
                speed_val = (completed / elapsed) if elapsed > 0 else 0
                with mass_job_lock:
                    mass_job_state["progress"] = completed
                    mass_job_state["saved"] = completed
                    mass_job_state["elapsed"] = round(elapsed, 1)
                    mass_job_state["speed"] = f"{speed_val:.1f} منتج/ثانية"

        excel_path = os.path.join(EXPORTS_DIR, f"{req.store}_mass_{req.target_count}_products.xlsx")
        csv_path = os.path.join(EXPORTS_DIR, f"{req.store}_mass_{req.target_count}_products.csv")
        global_storage.export_to_excel(excel_path)
        global_storage.export_to_csv(csv_path)

        with mass_job_lock:
            mass_job_state["status"] = "completed"
            mass_job_state["excel_path"] = excel_path
            mass_job_state["csv_path"] = csv_path
            mass_job_state["message"] = f"تم سحب وحفظ {completed} منتج من {store_label} بنجاح!"

    except Exception as e:
        with mass_job_lock:
            mass_job_state["status"] = "error"
            mass_job_state["message"] = f"خطأ: {str(e)}"

@app.post("/api/mass/start")
async def start_mass_scrape(req: MassScrapeRequest, background_tasks: BackgroundTasks):
    global mass_job_state
    with mass_job_lock:
        if mass_job_state["status"] in ["harvesting", "scraping"]:
            return {"status": "already_running", "message": "يوجد سحب جاري بالفعل حالياً."}
        mass_job_state["status"] = "starting"
        mass_job_state["message"] = "جاري بدء مهمة السحب..."
    
    background_tasks.add_task(_run_mass_job, req)
    return {"status": "started", "target": req.target_count}

@app.get("/api/mass/status")
async def get_mass_status():
    with mass_job_lock:
        return dict(mass_job_state)

@app.get("/api/mass/download/{fmt}")
async def download_mass_file(fmt: str):
    with mass_job_lock:
        if fmt == "excel" and mass_job_state.get("excel_path"):
            return FileResponse(mass_job_state["excel_path"], filename=os.path.basename(mass_job_state["excel_path"]))
        elif fmt == "csv" and mass_job_state.get("csv_path"):
            return FileResponse(mass_job_state["csv_path"], filename=os.path.basename(mass_job_state["csv_path"]))
        else:
            if fmt == "excel":
                path = os.path.join(EXPORTS_DIR, "catalog_current_database.xlsx")
                global_storage.export_to_excel(path)
                return FileResponse(path, filename="products_export.xlsx")
            elif fmt == "csv":
                path = os.path.join(EXPORTS_DIR, "catalog_current_database.csv")
                global_storage.export_to_csv(path)
                return FileResponse(path, filename="products_export.csv")
    raise HTTPException(status_code=404, detail="الملف غير متوفر بعد.")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)

