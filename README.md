# ⚡ Turbo E-Commerce Scraper Pro | ساحب منتجات نون وأمازون الفائق

أقوى وأسرع أداة متخصصة لسحب بيانات ومنتجات متجري **نون (Noon)** و **أمازون (Amazon)** بالكامل، ومصممة لسحب آلاف المنتجات مع استخراج كافة الصور بجودة Full HD ووضع **كل رابط صورة في خانة/عمود منفصل** في ملفات Excel و CSV.

---

## 🌟 المزايا والقدرات الرئيسية

- **⚡ سرعة فائقة**: سحب المنتج الواحد في أقل من ثانية إلى ثانيتين مع تجاوز حمايات أمازون ونون التلقائي (Chrome 124 TLS Impersonation).
- **🛒 دعم شامل لمتجري نون وأمازون**:
  - **نون (Noon)**: مصر، السعودية، الإمارات، الكويت، قطر.
  - **أمازون (Amazon)**: مصر (`amazon.eg`)، السعودية (`amazon.sa`)، الإمارات (`amazon.ae`)، أمريكا (`amazon.com`) وغيرها.
- **🖼️ خانة منفصلة لكل صورة في Excel**:
  - يتم استخراج كل الصور الأصلية بدون ضغط وتوزيعها في أعمدة مستقلة: `صورة 1 (الرئيسية)`، `صورة 2`، `صورة 3`...
- **🛡️ أمان تام وتجاوز أخطاء الإكسيل**: فحص وتنقية تلقائية لكافة النصوص والأوصاف من أي رموز تحكم XML غير صالحة لمنع خطأ `cannot be used in worksheets`.
- **📊 بيانات شاملة ومفصلة**:
  - اسم المنتج، المتجر، كود SKU / ASIN، الماركة، القسم.
  - السعر الحالي، السعر الأصلي، نسبة الخصم %، العملة.
  - حالة التوفر بالمخزون والكمية المتبقية.
  - البائع، التقييم، وعدد التقييمات والمراجعات.
  - الوصف الكامل والمميزات الأساسية (Key Features).
  - جدول المواصفات الفنية والتقنية.
  - رابط المنتج المباشر وسرعة السحب.

---

## 🚀 طرق الاستخدام

### 1. من واجهة الويب الاحترافية (Web UI Dashboard)

1. افتح المتصفح على:
   👉 **`http://127.0.0.1:8000`**
2. **سحب مفرد (Single)**: الصق أي رابط منتج من نون أو أمازون أو كود SKU / ASIN (مثل `B0BDHWDR12`).
3. **سحب جماعي (Batch)**: الصق قائمة روابط أو أكواد (يمكن دمج روابط نون وأمازون معاً في نفس القائمة).
4. **سحب ضخم (Mass Scraper)**: اختر المتجر (نون أو أمازون) وحدد عدد المنتجات المطلوب (حتى 3000 منتج) واضغط بدء السحب.
5. بمجرد الانتهاء، اضغط على زر **📊 تصدير Excel** أو **📄 تصدير CSV**.

---

### 2. من سطر الأوامر (CLI)

أداة [`noon_cli.py`](file:///g:/ziadscraber/noon_cli.py) تدعم الآن نون وأمازون بشكل مباشر مع الكشف التلقائي:

```bash
# سحب منتج من أمازون بالرابط:
python noon_cli.py --url "https://www.amazon.eg/-/en/dp/B0BDHWDR12" --export excel --output exports/airpods_amazon.xlsx

# سحب منتج من أمازون بكود ASIN مباشرة:
python noon_cli.py --sku B0BDHWDR12 --store amazon --country eg --export excel

# سحب منتج من نون:
python noon_cli.py --sku N20985583A --store noon --country eg --export excel

# سحب قائمة روابط مختلطة (نون + أمازون) من ملف:
python noon_cli.py --file my_urls.txt --workers 10 --export excel --output exports/all_products.xlsx

# سحب منتجات من الأكثر مبيعاً في أمازون (Bestsellers):
python noon_cli.py --search electronics --store amazon --limit 20 --export excel
```

---

### 📂 هيكل ملفات المشروع

- [amazon_core.py](file:///g:/ziadscraber/amazon_core.py): محرك سحب منتجات أمازون واستخراج الصور Master HD والأوصاف والمواصفات.
- [noon_core.py](file:///g:/ziadscraber/noon_core.py): محرك سحب منتجات نون عبر API الكتالوج الداخلي السريع.
- [noon_storage.py](file:///g:/ziadscraber/noon_storage.py): قاعدة بيانات SQLite وتصدير الإكسيل مع فصل أعمدة الصور وتطهير النصوص.
- [noon_cli.py](file:///g:/ziadscraber/noon_cli.py): واجهة سطر الأوامر الموحدة لنون وأمازون.
- [scrape_3000.py](file:///g:/ziadscraber/scrape_3000.py): محرك السحب الضخم لـ 3,000 منتج.
- [app.py](file:///g:/ziadscraber/app.py): خادم الويب (FastAPI) الموحد.
- [templates/index.html](file:///g:/ziadscraber/templates/index.html): واجهة لوحة التحكم التفاعلية مع دعم نون وأمازون.
- [static/app.js](file:///g:/ziadscraber/static/app.js): منطق الواجهة ومعالجة العرض المباشر والشارات.
