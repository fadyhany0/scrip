/**
 * Noon Turbo Scraper Pro - Client Logic
 */

let currentTab = 'mass';
let scrapedProducts = [];
let foundSearchHits = [];
let massPollInterval = null;
let batchPollInterval = null;

// DOM Loaded
document.addEventListener('DOMContentLoaded', () => {
  console.log("Turbo Scraper Pro Initialized.");
  checkExistingMassJob();
  checkExistingBatchJob();
  initBatchInputCounter();
});

// Tab Switching
function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('active'));

  if (tabName === 'mass') {
    document.getElementById('tabMassBtn').classList.add('active');
    document.getElementById('massTabSection').classList.add('active');
  } else if (tabName === 'single') {
    document.getElementById('tabSingleBtn').classList.add('active');
    document.getElementById('singleTabSection').classList.add('active');
  } else if (tabName === 'batch') {
    document.getElementById('tabBatchBtn').classList.add('active');
    document.getElementById('batchTabSection').classList.add('active');
  } else if (tabName === 'search') {
    document.getElementById('tabSearchBtn').classList.add('active');
    document.getElementById('searchTabSection').classList.add('active');
  }
}

// Check if mass scrape job is currently active
async function checkExistingMassJob() {
  try {
    const res = await fetch('/api/mass/status');
    const data = await res.json();
    if (data.status === 'harvesting' || data.status === 'scraping') {
      startMassPolling();
    }
  } catch (e) {}
}

// Check if batch scrape job is currently active
async function checkExistingBatchJob() {
  try {
    const res = await fetch('/api/scrape/batch/status');
    const data = await res.json();
    if (data.status === 'scraping' || data.status === 'starting') {
      startBatchPolling();
    }
  } catch (e) {}
}

function initBatchInputCounter() {
  const area = document.getElementById('batchInput');
  const stats = document.getElementById('batchInputStats');
  if (area && stats) {
    area.addEventListener('input', () => {
      const lines = area.value.split('\n').filter(l => l.trim() && !l.trim().startsWith('#'));
      if (lines.length > 0) {
        stats.textContent = `جاهز لسحب: ${lines.length.toLocaleString()} رابط`;
      } else {
        stats.textContent = '';
      }
    });
  }
}

// Handle Batch File Upload (TXT / CSV / XLSX)
async function handleBatchFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);
  showToast(`جاري قراءة ملف "${file.name}"...`);

  try {
    const res = await fetch('/api/scrape/batch/upload', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (data.status === 'success') {
      document.getElementById('batchInput').value = data.targets.join('\n');
      document.getElementById('batchInputStats').textContent = `✓ تم تحميل ${data.count.toLocaleString()} رابط من الملف بنجاح!`;
      showToast(`تم تحميل ${data.count.toLocaleString()} رابط من ملف "${file.name}" بنجاح! 🎉`);
    } else {
      showToast("فشل قراءة الملف", "error");
    }
  } catch (err) {
    showToast(`خطأ في قراءة الملف: ${err.message}`, "error");
  }
}

async function stopBatchScrape() {
  try {
    await fetch('/api/scrape/batch/stop', { method: 'POST' });
    showToast("تم إرسال أمر الإيقاف... جاري حفظ ما تم سحبه وتصديره.");
  } catch (err) {}
}

// -------------------------------------------------------------
// Mass Scraper (3,000 Products)
// -------------------------------------------------------------
async function startMassScrape() {
  const targetCount = parseInt(document.getElementById('massTargetCount').value) || 3000;
  const store = document.getElementById('massStore') ? document.getElementById('massStore').value : 'noon';
  const category = document.getElementById('massCategory').value;
  const keywords = document.getElementById('massKeywords').value.trim() || null;
  const country = document.getElementById('countrySelect').value;
  const lang = document.getElementById('langSelect').value;
  const workers = parseInt(document.getElementById('massWorkers').value) || 12;

  const btn = document.getElementById('startMassBtn');
  btn.disabled = true;

  const storeName = store === 'amazon' ? 'أمازون' : 'نون';
  document.getElementById('massStatusBox').style.display = 'block';
  document.getElementById('massStatusTitle').textContent = `جاري بدء سحب ${targetCount} منتج من ${storeName}...`;
  document.getElementById('massBarFill').style.width = '5%';
  document.getElementById('massDownloadActions').style.display = 'none';

  try {
    const res = await fetch('/api/mass/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_count: targetCount,
        store: store,
        category: category,
        keywords: keywords,
        country: country,
        lang: lang,
        workers: workers
      })
    });

    const data = await res.json();
    if (data.status === 'started' || data.status === 'already_running') {
      showToast(`🔥 انطلقت مهمة سحب ${targetCount} منتج بالتوازي!`);
      startMassPolling();
    } else {
      showToast(data.message || "تعذر بدء السحب", "error");
      btn.disabled = false;
    }
  } catch (err) {
    showToast(`خطأ في تشغيل السحب الضخم: ${err.message}`, "error");
    btn.disabled = false;
  }
}

function startMassPolling() {
  if (massPollInterval) clearInterval(massPollInterval);

  const statusBox = document.getElementById('massStatusBox');
  statusBox.style.display = 'block';

  massPollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/mass/status');
      const data = await res.json();

      document.getElementById('massStatusTitle').textContent = data.message || "جاري السحب...";
      document.getElementById('massSpeedBadge').textContent = data.speed || "0 منتج/ثانية";
      document.getElementById('massSavedCount').textContent = data.saved || 0;
      document.getElementById('massTotalCount').textContent = data.total || 3000;
      document.getElementById('massElapsedTime').textContent = `${data.elapsed || 0}s`;

      const total = data.total > 0 ? data.total : 3000;
      const progressPercent = Math.min(100, Math.round(((data.progress || 0) / total) * 100));
      document.getElementById('massBarFill').style.width = `${progressPercent}%`;

      if (data.status === 'completed') {
        clearInterval(massPollInterval);
        document.getElementById('startMassBtn').disabled = false;
        document.getElementById('massBarFill').style.width = '100%';
        document.getElementById('massStatusTitle').textContent = `🎉 اكتمل سحب ${data.saved} منتج بنجاح في ${data.elapsed}s!`;
        document.getElementById('massDownloadActions').style.display = 'flex';
        showToast(`🎉 تم الانتهاء بنجاح! تم حفظ وتجهيز ملفات Excel و CSV.`);
      } else if (data.status === 'error') {
        clearInterval(massPollInterval);
        document.getElementById('startMassBtn').disabled = false;
        showToast(data.message || "حدث خطأ أثناء السحب", "error");
      }
    } catch (e) {
      console.error("Polling error", e);
    }
  }, 1000);
}

// -------------------------------------------------------------
// Quick Sample Setters & Helpers
// -------------------------------------------------------------
function setSingleTarget(target) {
  document.getElementById('singleInput').value = target;
}

function loadBatchSamples() {
  const samples = [
    "https://www.amazon.eg/-/en/dp/B0BDHWDR12",
    "https://www.noon.com/egypt-en/apple-iphone-13-128gb-midnight-5g-with-facetime-middle-east-version/N50840187A/p/",
    "B0863TXGM3",
    "N20985583A",
    "N52600818A"
  ];
  document.getElementById('batchInput').value = samples.join('\n');
}

function setSearchQuery(q) {
  document.getElementById('searchInput').value = q;
  startSearch();
}

async function pasteToInput(inputId) {
  try {
    const text = await navigator.clipboard.readText();
    document.getElementById(inputId).value = text;
    showToast("تم اللصق من الحافظة!");
  } catch (err) {
    showToast("تعذر الوصول للحافظة، يرجى اللصق يدوياً (Ctrl+V)");
  }
}

// -------------------------------------------------------------
// Progress Bar Helpers for Single / Batch
// -------------------------------------------------------------
function showProgress(statusText, detailText, percent = 30) {
  const container = document.getElementById('progressContainer');
  container.style.display = 'block';
  document.getElementById('progressStatusText').textContent = statusText;
  document.getElementById('progressDetailText').textContent = detailText;
  document.getElementById('progressBarFill').style.width = `${percent}%`;
}

function updateProgress(percent, statusText, detailText) {
  document.getElementById('progressBarFill').style.width = `${percent}%`;
  if (statusText) document.getElementById('progressStatusText').textContent = statusText;
  if (detailText) document.getElementById('progressDetailText').textContent = detailText;
}

function hideProgress() {
  document.getElementById('progressContainer').style.display = 'none';
}

// -------------------------------------------------------------
// Single Product Scrape
// -------------------------------------------------------------
async function startSingleScrape() {
  const input = document.getElementById('singleInput').value.trim();
  if (!input) {
    showToast("يرجى إدخال رابط أو كود SKU للمنتج أولاً", "warning");
    return;
  }

  const store = document.getElementById('storeSelect') ? document.getElementById('storeSelect').value : 'auto';
  const country = document.getElementById('countrySelect').value;
  const lang = document.getElementById('langSelect').value;

  showProgress("جاري سحب المنتج بسرعة فائقة...", `يتم جلب بيانات ${input}...`, 40);
  const startBtn = document.getElementById('startSingleBtn');
  startBtn.disabled = true;

  try {
    const res = await fetch('/api/scrape/single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: input, store, country, lang })
    });

    const data = await res.json();
    if (data.status === 'success') {
      const existingIdx = scrapedProducts.findIndex(p => p.sku === data.sku);
      if (existingIdx !== -1) {
        scrapedProducts[existingIdx] = data;
      } else {
        scrapedProducts.unshift(data);
      }
      renderProducts();
      showToast(`تم سحب "${data.name.substring(0, 30)}..." في ${data.scrape_time_seconds} ثانية فقط! ⚡`);
    } else {
      showToast(`خطأ: ${data.error || 'تعذر سحب المنتج'}`, "error");
    }
  } catch (err) {
    showToast(`حدث خطأ أثناء الاتصال بالخادم: ${err.message}`, "error");
  } finally {
    hideProgress();
    startBtn.disabled = false;
  }
}

// -------------------------------------------------------------
// Batch Products Scrape (Supports up to 50,000+ URLs safely)
// -------------------------------------------------------------
async function startBatchScrape() {
  const text = document.getElementById('batchInput').value.trim();
  if (!text) {
    showToast("يرجى إدخال روابط أو أكواد SKU / ASIN أولاً", "warning");
    return;
  }

  const targets = text.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  if (targets.length === 0) {
    showToast("لم يتم العثور على روابط صالحة", "warning");
    return;
  }

  const store = document.getElementById('storeSelect') ? document.getElementById('storeSelect').value : 'auto';
  const country = document.getElementById('countrySelect').value;
  const lang = document.getElementById('langSelect').value;
  const workers = parseInt(document.getElementById('workersInput').value) || 15;

  const startBtn = document.getElementById('startBatchBtn');
  startBtn.disabled = true;

  // If large batch (> 30 targets, e.g. 500, 3,000, 37,000), run in background with live polling!
  if (targets.length > 30) {
    const statusBox = document.getElementById('batchStatusBox');
    statusBox.style.display = 'block';
    document.getElementById('batchStatusTitle').textContent = `جاري بدء سحب ${targets.length.toLocaleString()} منتج بالتوازي في الخلفية...`;
    document.getElementById('batchBarFill').style.width = '2%';
    document.getElementById('batchTotalCount').textContent = targets.length.toLocaleString();
    document.getElementById('batchSavedCount').textContent = '0';
    document.getElementById('batchSpeedBadge').textContent = '0 /s';

    try {
      const res = await fetch('/api/scrape/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targets, store, country, lang, workers })
      });

      const data = await res.json();
      if (data.status === 'started_async' || data.status === 'already_running') {
        showToast(`🚀 بدأت مهمة سحب ${targets.length.toLocaleString()} منتج بالتوازي في الخلفية!`);
        startBatchPolling();
      } else {
        showToast(data.message || "تعذر بدء السحب", "error");
        startBtn.disabled = false;
      }
    } catch (err) {
      showToast(`فشل السحب الجماعي: ${err.message}`, "error");
      startBtn.disabled = false;
    }
    return;
  }

  // Quick mode (<= 30 items)
  showProgress(`جاري سحب ${targets.length} منتجات بالتوازي...`, `يعمل النظام على ${workers} مسارات متزامنة (Threads)`, 25);

  let curPercent = 25;
  const tickInterval = setInterval(() => {
    if (curPercent < 90) {
      curPercent += 15;
      updateProgress(curPercent);
    }
  }, 400);

  try {
    const res = await fetch('/api/scrape/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targets, store, country, lang, workers })
    });

    clearInterval(tickInterval);
    updateProgress(100, "اكتمل السحب الجماعي!", "تم الانتهاء بنجاح");

    const data = await res.json();
    if (data.status === 'success') {
      for (const p of data.products) {
        if (p.status === 'success') {
          const idx = scrapedProducts.findIndex(x => x.sku === p.sku);
          if (idx !== -1) scrapedProducts[idx] = p;
          else scrapedProducts.unshift(p);
        }
      }
      renderProducts();
      showToast(`🎉 تم سحب ${data.success_count} منتج في ${data.total_time_seconds} ثانية (متوسط ${data.average_speed_seconds}s للمنتج)!`);
    } else {
      showToast("حدث خطأ أثناء السحب الجماعي", "error");
    }
  } catch (err) {
    clearInterval(tickInterval);
    showToast(`فشل السحب الجماعي: ${err.message}`, "error");
  } finally {
    hideProgress();
    startBtn.disabled = false;
  }
}

function startBatchPolling() {
  if (batchPollInterval) clearInterval(batchPollInterval);

  const statusBox = document.getElementById('batchStatusBox');
  statusBox.style.display = 'block';

  batchPollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/scrape/batch/status');
      const data = await res.json();

      document.getElementById('batchStatusTitle').textContent = data.message || "جاري السحب الجماعي...";
      document.getElementById('batchSpeedBadge').textContent = data.speed || "0 /s";
      document.getElementById('batchSpeedText').textContent = data.speed || "0 /s";
      document.getElementById('batchSavedCount').textContent = (data.saved || 0).toLocaleString();
      document.getElementById('batchTotalCount').textContent = (data.total || 0).toLocaleString();
      document.getElementById('batchEtaText').textContent = data.eta || "حساب...";
      document.getElementById('batchElapsedTime').textContent = `${data.elapsed || 0}s`;

      const total = data.total > 0 ? data.total : 1;
      const progressPercent = Math.min(100, Math.round(((data.progress || 0) / total) * 100));
      document.getElementById('batchBarFill').style.width = `${progressPercent}%`;

      // Live update of cards preview
      if (data.recent_products && data.recent_products.length > 0) {
        for (const p of data.recent_products) {
          if (p && p.status === 'success') {
            const idx = scrapedProducts.findIndex(x => x.sku === p.sku);
            if (idx !== -1) scrapedProducts[idx] = p;
            else scrapedProducts.unshift(p);
          }
        }
        renderProducts();
      }

      if (data.status === 'completed' || data.status === 'stopped') {
        clearInterval(batchPollInterval);
        document.getElementById('startBatchBtn').disabled = false;
        document.getElementById('batchBarFill').style.width = '100%';
        const actionWord = data.status === 'completed' ? 'اكتمل السحب بالكامل' : 'تم إيقاف السحب وحفظ البيانات';
        document.getElementById('batchStatusTitle').textContent = `🎉 ${actionWord}! تم حفظ ${data.saved.toLocaleString()} منتج بنجاح في ${data.elapsed}s!`;
        showToast(`🎉 تم الانتهاء بنجاح! تم حفظ وتجهيز ملفات Excel و CSV.`);
      }
    } catch (e) {
      console.error("Batch polling error", e);
    }
  }, 1000);
}

// -------------------------------------------------------------
// Search & Discover
// -------------------------------------------------------------
async function startSearch() {
  const query = document.getElementById('searchInput').value.trim();
  if (!query) {
    showToast("يرجى إدخال كلمة البحث أولاً", "warning");
    return;
  }

  const store = document.getElementById('searchStore') ? document.getElementById('searchStore').value : 'noon';
  const country = document.getElementById('countrySelect').value;
  const lang = document.getElementById('langSelect').value;
  const limit = parseInt(document.getElementById('searchLimitSelect').value) || 24;

  const searchBtn = document.getElementById('startSearchBtn');
  searchBtn.disabled = true;

  const storeLabel = store === 'amazon' ? 'أمازون' : 'نون';
  showProgress(`جاري البحث في ${storeLabel} عن "${query}"...`, "استخراج نتائج الكتالوج والأكواد", 50);

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, store, country, lang, limit })
    });

    const data = await res.json();
    if (data.status === 'success') {
      foundSearchHits = data.results;
      renderSearchHits(foundSearchHits);
      showToast(`تم العثور على ${data.count} منتج! يمكنك سحب تفاصيلها بالكامل.`);
    } else {
      showToast("تعذر البحث في نون", "error");
    }
  } catch (err) {
    showToast(`خطأ في البحث: ${err.message}`, "error");
  } finally {
    hideProgress();
    searchBtn.disabled = false;
  }
}

function renderSearchHits(hits) {
  const container = document.getElementById('searchHitsContainer');
  const countSpan = document.getElementById('searchHitsCount');
  const grid = document.getElementById('searchHitsGrid');

  if (!hits || hits.length === 0) {
    container.style.display = 'none';
    showToast("لم يتم العثور على نتائج لهذه الكلمة", "warning");
    return;
  }

  countSpan.textContent = hits.length;
  grid.innerHTML = '';

  hits.forEach(h => {
    const card = document.createElement('div');
    card.className = 'search-hit-card';
    card.innerHTML = `
      <img src="${h.image || '/static/placeholder.png'}" class="search-hit-img" alt="${h.name}">
      <div class="search-hit-info">
        <div class="search-hit-title" title="${h.name}">${h.name}</div>
        <div class="search-hit-price">${h.price ? h.price + ' EGP' : 'غير محدد'}</div>
        <button class="sample-pill" style="margin-top:6px;" onclick="scrapeSingleSku('${h.sku}')">⚡ سحب التفاصيل</button>
      </div>
    `;
    grid.appendChild(card);
  });

  container.style.display = 'block';
}

function scrapeSingleSku(sku) {
  document.getElementById('singleInput').value = sku;
  switchTab('single');
  startSingleScrape();
}

async function scrapeAllFoundHits() {
  if (!foundSearchHits || foundSearchHits.length === 0) return;
  const skus = foundSearchHits.map(h => h.sku);
  document.getElementById('batchInput').value = skus.join('\n');
  switchTab('batch');
  startBatchScrape();
}

// -------------------------------------------------------------
// Render Products Grid & Stats
// -------------------------------------------------------------
function renderProducts() {
  const grid = document.getElementById('productsGrid');
  const statsBar = document.getElementById('statsBar');
  const exportBar = document.getElementById('exportBar');

  if (scrapedProducts.length === 0) {
    grid.innerHTML = '';
    statsBar.style.display = 'none';
    exportBar.style.display = 'none';
    return;
  }

  statsBar.style.display = 'grid';
  exportBar.style.display = 'flex';

  const validProducts = scrapedProducts.filter(p => p.status === 'success');
  const totalImgs = validProducts.reduce((acc, p) => acc + (p.image_count || 0), 0);
  const totalSpeeds = validProducts.reduce((acc, p) => acc + (p.scrape_time_seconds || 0), 0);
  const avgSpeed = validProducts.length ? (totalSpeeds / validProducts.length).toFixed(2) : '0';
  const totalVal = validProducts.reduce((acc, p) => acc + (parseFloat(p.price) || 0), 0);
  const currency = validProducts.length > 0 ? (validProducts[0].currency || 'EGP') : 'EGP';

  document.getElementById('statTotalProducts').textContent = validProducts.length;
  document.getElementById('statTotalImages').textContent = totalImgs;
  document.getElementById('statAvgSpeed').textContent = `${avgSpeed}s ⚡`;
  document.getElementById('statTotalValue').textContent = `${Math.round(totalVal).toLocaleString()} ${currency}`;

  grid.innerHTML = '';
  validProducts.forEach((p, idx) => {
    const card = createProductCard(p, idx);
    grid.appendChild(card);
  });
}

function createProductCard(p, index) {
  const card = document.createElement('div');
  card.className = 'product-card';

  const images = p.images || [];
  const mainImg = images.length > 0 ? images[0] : '';
  const priceDisplay = p.price ? `${p.price} ${p.currency}` : 'غير متوفر / Out of stock';
  const oldPriceDisplay = (p.original_price && p.original_price > p.price) ? `${p.original_price} ${p.currency}` : '';
  const discountDisplay = p.discount_percentage ? `خصم ${p.discount_percentage}%` : '';

  const specs = p.specifications || {};
  const specsRows = Object.entries(specs).slice(0, 10).map(([k, v]) => `
    <tr>
      <td class="spec-name">${k}</td>
      <td class="spec-val">${v}</td>
    </tr>
  `).join('');

  const thumbsHtml = images.map((img, i) => `
    <img src="${img}" class="thumb-item ${i === 0 ? 'active' : ''}" 
         onclick="switchCardImage(this, 'card-img-${index}', '${img}')" 
         alt="thumbnail ${i+1}">
  `).join('');

  const isAmazon = (p.store === 'amazon') || (p.url && p.url.includes('amazon.'));
  const storeBadge = isAmazon 
    ? '<span style="background: rgba(255, 153, 0, 0.18); color: #ff9900; border: 1px solid rgba(255, 153, 0, 0.5); padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700;">🟠 أمازون</span>'
    : '<span style="background: rgba(254, 230, 0, 0.18); color: #fee600; border: 1px solid rgba(254, 230, 0, 0.5); padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700;">🟡 نون</span>';

  card.innerHTML = `
    <div class="card-top-bar">
      <div style="display:flex; gap:6px; align-items:center;">
        ${storeBadge}
        <span class="sku-pill">${isAmazon ? 'ASIN' : 'كود'}: ${p.sku}</span>
      </div>
      <span class="stock-pill ${p.in_stock ? 'in-stock' : 'out-of-stock'}">
        ${p.in_stock ? '● متوفر بالمخزون' : '✕ غير متوفر'}
      </span>
    </div>

    <div class="product-image-container">
      <span class="image-counter-pill">📸 ${images.length} صور Full HD</span>
      <img id="card-img-${index}" src="${mainImg}" class="main-product-img" 
           onclick="openLightbox('${mainImg}')" 
           title="انقر لتكبير الصورة بدقة 1200px" alt="${p.name}">
    </div>

    <div class="thumbnails-strip">
      ${thumbsHtml}
    </div>

    <div>
      <div class="product-brand">${p.brand || (isAmazon ? 'Amazon' : 'Noon')}</div>
      <h3 class="product-name" title="${p.name}">${p.name}</h3>
    </div>

    <div class="product-pricing">
      <div class="current-price">${priceDisplay}</div>
      ${oldPriceDisplay ? `<div class="original-price">${oldPriceDisplay}</div>` : ''}
      ${discountDisplay ? `<div class="discount-tag">${discountDisplay}</div>` : ''}
    </div>

    <div class="product-meta-row">
      <div class="rating-badge">
        <span>★</span> 
        <span>${p.rating || '4.0'}</span> 
        <span style="color:var(--text-dim);font-size:11px;">(${p.rating_count || 'مراجعات'})</span>
      </div>
      <div class="seller-name">البائع: <strong>${p.seller || (isAmazon ? 'Amazon' : 'Noon')}</strong></div>
      <div style="font-family:var(--font-english);font-size:11px;color:var(--primary-accent);">⚡ ${p.scrape_time_seconds}s</div>
    </div>

    <div class="collapsible-section">
      <button class="toggle-details-btn" onclick="toggleDetails(this)">
        <span>المواصفات والوصف الكامل ▾</span>
      </button>
      <div class="details-content">
        ${specsRows ? `
          <h5 style="color:#fff;margin-bottom:6px;">المواصفات الفنية:</h5>
          <table class="specs-table">${specsRows}</table>
        ` : ''}
        <h5 style="color:#fff;margin:12px 0 6px;">الوصف الكامل:</h5>
        <div style="white-space:pre-line;color:var(--text-muted);font-size:12px;">${p.description || 'لا يوجد وصف إضافي.'}</div>
      </div>
    </div>

    <div class="card-actions">
      <a href="${p.url}" target="_blank" class="noon-link-btn" style="${isAmazon ? 'background: linear-gradient(135deg, #ff9900 0%, #e67e22 100%); color: #111;' : ''}">
        <span>${isAmazon ? '🛒 فتح في أمازون' : '🛒 فتح في نون'}</span>
      </a>
      <button class="copy-json-btn" onclick='copyProductJson(${JSON.stringify(p).replace(/'/g, "&apos;")})' title="نسخ JSON">
        📋 نسخ JSON
      </button>
    </div>
  `;

  return card;
}

function switchCardImage(thumbElem, imgId, newSrc) {
  const mainImg = document.getElementById(imgId);
  if (mainImg) {
    mainImg.src = newSrc;
    mainImg.setAttribute('onclick', `openLightbox('${newSrc}')`);
  }
  const parent = thumbElem.parentElement;
  parent.querySelectorAll('.thumb-item').forEach(el => el.classList.remove('active'));
  thumbElem.classList.add('active');
}

function toggleDetails(btn) {
  const content = btn.nextElementSibling;
  content.classList.toggle('open');
  if (content.classList.contains('open')) {
    btn.querySelector('span').textContent = 'إخفاء المواصفات والوصف ▴';
  } else {
    btn.querySelector('span').textContent = 'المواصفات والوصف الكامل ▾';
  }
}

function copyProductJson(prodObj) {
  navigator.clipboard.writeText(JSON.stringify(prodObj, null, 2));
  showToast("تم نسخ بيانات المنتج بصيغة JSON!");
}

function openLightbox(imgSrc) {
  const modal = document.getElementById('imageLightboxModal');
  const img = document.getElementById('lightboxImg');
  const dlBtn = document.getElementById('lightboxDownloadBtn');

  img.src = imgSrc;
  dlBtn.href = imgSrc;
  modal.classList.add('active');
}

function closeLightbox(e) {
  if (e.target.id === 'imageLightboxModal' || e.target.classList.contains('lightbox-close')) {
    document.getElementById('imageLightboxModal').classList.remove('active');
  }
}

function clearResults() {
  if (confirm("هل أنت متأكد من مسح جميع المنتجات المسحوبة؟")) {
    scrapedProducts = [];
    renderProducts();
    showToast("تم مسح النتائج");
  }
}

async function triggerExport(format) {
  if (scrapedProducts.length === 0) {
    showToast("لا توجد منتجات لتصديرها", "warning");
    return;
  }

  showToast(`جاري تجهيز ملف ${format.toUpperCase()}...`);

  try {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        products: scrapedProducts,
        format: format
      })
    });

    if (!res.ok) throw new Error("فشل توليد ملف التصدير");

    const disposition = res.headers.get('Content-Disposition');
    let filename = `noon_scraped_${Date.now()}.${format === 'excel' ? 'xlsx' : (format === 'images_zip' ? 'zip' : format)}`;
    if (disposition && disposition.indexOf('filename=') !== -1) {
      const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
      if (matches != null && matches[1]) {
        filename = matches[1].replace(/['"]/g, '');
      }
    }

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    showToast(`✓ تم تحميل ${filename} بنجاح!`);
  } catch (err) {
    showToast(`خطأ في التصدير: ${err.message}`, "error");
  }
}

function showToast(msg, type = "success") {
  const toast = document.getElementById('toastNotification');
  const msgElem = document.getElementById('toastMessage');
  const iconElem = document.getElementById('toastIcon');

  msgElem.textContent = msg;
  if (type === 'error') {
    iconElem.textContent = '✕';
    toast.style.borderColor = 'var(--rose-accent)';
  } else if (type === 'warning') {
    iconElem.textContent = '⚠';
    toast.style.borderColor = 'var(--amber-accent)';
  } else {
    iconElem.textContent = '✓';
    toast.style.borderColor = 'var(--primary-accent)';
  }

  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 3500);
}
