(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function readJsonScript(id, fallback) {
    const el = $(id);
    if (!el) return fallback;
    try { return JSON.parse(el.textContent || "null") ?? fallback; }
    catch { return fallback; }
  }

  function toNum(v) {
    if (v === null || v === undefined) return null;
    const s = String(v).trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  function money(n) { return Number.isFinite(n) ? n.toFixed(2) : ""; }
  function round2(n) { return Math.round(n * 100) / 100; }

  // ---------- totals ----------
  function updateTotalsUI(laborTotal, partsTotal) {
    const laborEl = $("laborTotalDisplay");
    const partsEl = $("partsTotalDisplay");
    const grandEl = $("grandTotalDisplay");

    if (laborEl) laborEl.textContent = Number.isFinite(laborTotal) ? `$${money(laborTotal)}` : "—";
    if (partsEl) partsEl.textContent = Number.isFinite(partsTotal) ? `$${money(partsTotal)}` : "—";

    const grand = (Number.isFinite(laborTotal) ? laborTotal : 0) + (Number.isFinite(partsTotal) ? partsTotal : 0);
    if (grandEl) grandEl.textContent =
      (Number.isFinite(laborTotal) || Number.isFinite(partsTotal)) ? `$${money(round2(grand))}` : "—";
  }

  // ---------- labor ----------
  function getHourlyRate(rates, code) {
    if (!Array.isArray(rates) || !code) return null;
    const found = rates.find(x => String(x.code) === String(code));
    if (!found) return null;
    return toNum(found.hourly_rate);
  }

  function recalcLabor(laborRates) {
    const hoursInput = $("labor_hours");
    const rateSelect = $("labor_rate_code");
    if (!hoursInput || !rateSelect) return null;

    const hours = toNum(hoursInput.value);
    const code = String(rateSelect.value || "").trim();
    if (hours === null || !code) return null;

    const hr = getHourlyRate(laborRates, code);
    if (hr === null) return null;

    return round2(hours * hr);
  }

  // ---------- pricing ----------
  function matchRule(cost, rules) {
    if (!Number.isFinite(cost) || !Array.isArray(rules)) return null;

    for (const r of rules) {
      const from = toNum(r.from);
      const to = (r.to === null || r.to === undefined) ? null : toNum(r.to);
      const vp = toNum(r.value_percent);
      if (from === null || vp === null) continue;

      if (cost < from) continue;
      if (to === null) return { value_percent: vp };
      if (cost <= to) return { value_percent: vp };
    }
    return null;
  }

  function calcPriceFromRule(cost, mode, valuePercent) {
    if (!Number.isFinite(cost) || cost <= 0) return null;
    if (!Number.isFinite(valuePercent)) return null;

    const vp = valuePercent / 100;

    if (mode === "markup") {
      return round2(cost * (1 + vp));
    }

    const denom = 1 - vp;
    if (denom <= 0) return round2(cost);
    return round2(cost / denom);
  }

  // ---------- parts table ----------
  function makePartsRow(index) {
    const tr = document.createElement("tr");
    tr.className = "parts-row";
    tr.dataset.index = String(index);

    tr.innerHTML = `
      <td><input class="form-control form-control-sm part-number" name="part_number_${index}" maxlength="64" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-description" name="part_description_${index}" maxlength="200" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-qty" name="part_qty_${index}" inputmode="numeric"></td>
      <td><input class="form-control form-control-sm part-cost" name="part_cost_${index}" inputmode="decimal"></td>
      <td><input class="form-control form-control-sm part-price" value="" readonly tabindex="-1"></td>
      <td class="part-line-total"><span class="text-muted">—</span></td>
    `;
    return tr;
  }

  function rowHasAnyInput(tr) {
    const pn = tr.querySelector(".part-number")?.value || "";
    const ds = tr.querySelector(".part-description")?.value || "";
    const q = tr.querySelector(".part-qty")?.value || "";
    const c = tr.querySelector(".part-cost")?.value || "";
    return !!(String(pn).trim() || String(ds).trim() || String(q).trim() || String(c).trim());
  }

  function clearRowCalc(tr) {
    const priceInput = tr.querySelector(".part-price");
    const lineCell = tr.querySelector(".part-line-total");
    if (priceInput) priceInput.value = "";
    if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
  }

  function recalcRow(tr, pricing) {
    const qty = toNum(tr.querySelector(".part-qty")?.value);
    const cost = toNum(tr.querySelector(".part-cost")?.value);

    const priceInput = tr.querySelector(".part-price");
    const lineCell = tr.querySelector(".part-line-total");

    if (!pricing || !Array.isArray(pricing.rules) || pricing.rules.length === 0) {
      clearRowCalc(tr);
      return null;
    }

    if (qty === null || qty <= 0 || cost === null || cost < 0) {
      clearRowCalc(tr);
      return null;
    }

    const rule = matchRule(cost, pricing.rules);
    if (!rule) {
      clearRowCalc(tr);
      return null;
    }

    const price = calcPriceFromRule(cost, pricing.mode, rule.value_percent);
    if (price === null) {
      clearRowCalc(tr);
      return null;
    }

    const lineTotal = round2(price * qty);
    if (priceInput) priceInput.value = money(price);
    if (lineCell) lineCell.innerHTML = `<strong>$${money(lineTotal)}</strong>`;
    return lineTotal;
  }

  function ensureTrailingEmptyRow(tbody) {
    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));
    if (rows.length === 0) {
      tbody.appendChild(makePartsRow(0));
      return;
    }
    const last = rows[rows.length - 1];
    if (rowHasAnyInput(last)) {
      tbody.appendChild(makePartsRow(rows.length));
    }
  }

  function recalcAllParts(tbody, pricing) {
    let total = 0;
    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));

    for (const tr of rows) {
      if (!rowHasAnyInput(tr)) {
        clearRowCalc(tr);
        continue;
      }
      const lt = recalcRow(tr, pricing);
      if (lt !== null && Number.isFinite(lt)) total += lt;
    }

    total = round2(total);
    return total > 0 ? total : null;
  }

  function recalcAll(tbody, pricing, laborRates) {
    ensureTrailingEmptyRow(tbody);
    const laborTotal = recalcLabor(laborRates);
    const partsTotal = recalcAllParts(tbody, pricing);
    updateTotalsUI(
      laborTotal !== null ? laborTotal : null,
      partsTotal !== null ? partsTotal : null
    );
  }

  // ---------- backend search (debounced) ----------
  function debounce(fn, ms) {
    let t = null;
    return function (...args) {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function ensureDropdown() {
    let dd = document.getElementById("partsSearchDropdown");
    if (dd) return dd;

    dd = document.createElement("div");
    dd.id = "partsSearchDropdown";
    dd.style.position = "absolute";
    dd.style.zIndex = "2000";
    dd.style.background = "#fff";
    dd.style.border = "1px solid rgba(0,0,0,.15)";
    dd.style.borderRadius = "8px";
    dd.style.boxShadow = "0 6px 18px rgba(0,0,0,.1)";
    dd.style.maxHeight = "280px";
    dd.style.overflow = "auto";
    dd.style.display = "none";
    dd.style.minWidth = "320px";
    document.body.appendChild(dd);
    return dd;
  }

  function placeDropdownNearInput(dd, inputEl) {
    const r = inputEl.getBoundingClientRect();
    dd.style.left = `${window.scrollX + r.left}px`;
    dd.style.top = `${window.scrollY + r.bottom + 4}px`;
    dd.style.minWidth = `${Math.max(320, r.width)}px`;
  }

  function hideDropdown(dd) {
    dd.style.display = "none";
    dd.innerHTML = "";
    dd._items = [];
    dd._activeIndex = -1;
    dd._targetInput = null;
    dd._targetRow = null;
  }

  function renderDropdown(dd, items) {
    dd._items = items || [];
    dd._activeIndex = -1;

    if (!items || items.length === 0) {
      dd.innerHTML = `<div style="padding:10px; color:#6c757d;">No results</div>`;
      return;
    }

    dd.innerHTML = items.map((it, idx) => {
      const title = `${it.part_number || ""} — ${it.description || ""}`.trim();
      const meta = `Stock: ${it.in_stock ?? 0} • Avg cost: $${money(toNum(it.average_cost) ?? 0)}`;
      return `
        <div class="parts-dd-item" data-idx="${idx}"
             style="padding:10px 12px; cursor:pointer; border-bottom:1px solid rgba(0,0,0,.06);">
          <div style="font-weight:600; line-height:1.2;">${escapeHtml(title)}</div>
          <div style="font-size:12px; color:#6c757d; margin-top:2px;">${escapeHtml(meta)}</div>
        </div>
      `;
    }).join("");
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function fillRowFromPart(tr, part) {
    if (!tr || !part) return;

    const pn = tr.querySelector(".part-number");
    const ds = tr.querySelector(".part-description");
    const cost = tr.querySelector(".part-cost");

    if (pn) pn.value = part.part_number || "";
    if (ds) {
      const d = (part.description || "").trim();
      const ref = (part.reference || "").trim();
      ds.value = ref && ref !== d ? `${d} (${ref})` : d;
    }
    if (cost) cost.value = (part.average_cost != null) ? String(part.average_cost) : "";
  }

  async function fetchParts(q) {
    const url = `/work_orders/api/parts/search?q=${encodeURIComponent(q)}&limit=20`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.items) ? data.items : [];
  }

  const debouncedSearch = debounce(async function (dd, inputEl, tr) {
    const q = String(inputEl.value || "").trim();
    if (q.length < 3) {
      hideDropdown(dd);
      return;
    }

    placeDropdownNearInput(dd, inputEl);
    dd.style.display = "block";
    dd.innerHTML = `<div style="padding:10px; color:#6c757d;">Searching…</div>`;

    const items = await fetchParts(q);
    dd._targetInput = inputEl;
    dd._targetRow = tr;
    renderDropdown(dd, items);
  }, 150);

  function wireSearchForInput(dd, inputEl, tr) {
    inputEl.addEventListener("input", () => debouncedSearch(dd, inputEl, tr));
    inputEl.addEventListener("focus", () => debouncedSearch(dd, inputEl, tr));
  }

  function wireDropdownClick(dd, tbody, pricing, laborRates) {
    dd.addEventListener("mousedown", function (e) {
      const itemEl = e.target.closest(".parts-dd-item");
      if (!itemEl) return;
      e.preventDefault();

      const idx = Number(itemEl.dataset.idx);
      const it = dd._items?.[idx];
      const tr = dd._targetRow;
      if (!it || !tr) return;

      fillRowFromPart(tr, it);
      hideDropdown(dd);
      recalcAll(tbody, pricing, laborRates);
    });
  }

  function wireDismiss(dd) {
    document.addEventListener("click", function (e) {
      if (!dd || dd.style.display === "none") return;
      if (e.target.closest("#partsSearchDropdown")) return;
      // if click on an input, keep
      if (e.target.closest(".part-number") || e.target.closest(".part-description")) return;
      hideDropdown(dd);
    });

    window.addEventListener("scroll", () => { if (dd.style.display !== "none") hideDropdown(dd); }, true);
    window.addEventListener("resize", () => { if (dd.style.display !== "none") hideDropdown(dd); });
  }

  // ---------- init ----------
  document.addEventListener("DOMContentLoaded", function () {
    const laborRates = readJsonScript("laborRatesData", []);
    const pricing = readJsonScript("partsPricingRulesData", null);

    const tbody = $("partsTbody");
    if (!tbody) return;

    // ensure at least one row exists (template already has row 0)
    if (tbody.querySelectorAll("tr.parts-row").length === 0) {
      tbody.appendChild(makePartsRow(0));
    }

    // wire labor
    const hoursInput = $("labor_hours");
    const rateSelect = $("labor_rate_code");
    if (hoursInput) hoursInput.addEventListener("input", () => recalcAll(tbody, pricing, laborRates));
    if (rateSelect) rateSelect.addEventListener("change", () => recalcAll(tbody, pricing, laborRates));

    // parts calc & auto-add rows
    tbody.addEventListener("input", function (e) {
      const t = e.target;
      if (!t) return;
      if (!t.closest("tr.parts-row")) return;
      recalcAll(tbody, pricing, laborRates);
    });

    recalcAll(tbody, pricing, laborRates);

    // backend search dropdown
    const dd = ensureDropdown();
    wireDropdownClick(dd, tbody, pricing, laborRates);
    wireDismiss(dd);

    // wire search for existing rows, and for new rows via event delegation:
    tbody.addEventListener("focusin", function (e) {
      const inputEl = e.target;
      if (!(inputEl instanceof HTMLInputElement)) return;

      const tr = inputEl.closest("tr.parts-row");
      if (!tr) return;

      if (inputEl.classList.contains("part-number") || inputEl.classList.contains("part-description")) {
        wireSearchForInput(dd, inputEl, tr);
        // immediately try open if already has 3 chars
        debouncedSearch(dd, inputEl, tr);
      }
    }, { passive: true });
  });
})();
