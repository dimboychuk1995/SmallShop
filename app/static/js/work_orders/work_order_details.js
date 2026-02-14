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

  // ---------------- pricing ----------------
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

    if (mode === "markup") return round2(cost * (1 + vp));

    const denom = 1 - vp; // margin
    if (denom <= 0) return round2(cost);
    return round2(cost / denom);
  }

  // ---------------- labor ----------------
  function getHourlyRate(rates, code) {
    if (!Array.isArray(rates) || !code) return null;
    const found = rates.find(x => String(x.code) === String(code));
    if (!found) return null;
    return toNum(found.hourly_rate);
  }

  function calcLaborTotal(blockEl, laborRates) {
    const hours = toNum(blockEl.querySelector(".labor-hours")?.value);
    const code = String(blockEl.querySelector(".labor-rate")?.value || "").trim();
    if (hours === null || !code) return null;

    const hr = getHourlyRate(laborRates, code);
    if (hr === null) return null;

    return round2(hours * hr);
  }

  // ---------------- parts rows ----------------
  function makePartsRow(blockIndex, rowIndex) {
    const tr = document.createElement("tr");
    tr.className = "parts-row";
    tr.dataset.index = String(rowIndex);

    tr.innerHTML = `
      <td><input class="form-control form-control-sm part-number" name="blocks[${blockIndex}][parts][${rowIndex}][part_number]" maxlength="64" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-description" name="blocks[${blockIndex}][parts][${rowIndex}][description]" maxlength="200" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-qty" name="blocks[${blockIndex}][parts][${rowIndex}][qty]" inputmode="numeric"></td>
      <td><input class="form-control form-control-sm part-cost" name="blocks[${blockIndex}][parts][${rowIndex}][cost]" inputmode="decimal"></td>
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

  function calcRowLineTotal(tr, pricing) {
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

    const lt = round2(price * qty);
    if (priceInput) priceInput.value = money(price);
    if (lineCell) lineCell.innerHTML = `<strong>$${money(lt)}</strong>`;
    return lt;
  }

  function ensureTrailingEmptyRow(blockEl) {
    const tbody = blockEl.querySelector(".partsTbody");
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));
    if (rows.length === 0) {
      tbody.appendChild(makePartsRow(Number(blockEl.dataset.blockIndex), 0));
      return;
    }

    const last = rows[rows.length - 1];
    if (rowHasAnyInput(last)) {
      tbody.appendChild(makePartsRow(Number(blockEl.dataset.blockIndex), rows.length));
    }
  }

  function calcPartsTotal(blockEl, pricing) {
    const tbody = blockEl.querySelector(".partsTbody");
    if (!tbody) return null;

    let total = 0;
    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));

    for (const tr of rows) {
      if (!rowHasAnyInput(tr)) {
        clearRowCalc(tr);
        continue;
      }
      const lt = calcRowLineTotal(tr, pricing);
      if (lt !== null && Number.isFinite(lt)) total += lt;
    }

    total = round2(total);
    return total > 0 ? total : null;
  }

  // ---------------- totals per block + grand ----------------
  function setBlockTotalsUI(blockEl, laborTotal, partsTotal) {
    const laborEl = blockEl.querySelector(".laborTotalDisplay");
    const partsEl = blockEl.querySelector(".partsTotalDisplay");
    const blockElTotal = blockEl.querySelector(".blockTotalDisplay");

    if (laborEl) laborEl.textContent = Number.isFinite(laborTotal) ? `$${money(laborTotal)}` : "—";
    if (partsEl) partsEl.textContent = Number.isFinite(partsTotal) ? `$${money(partsTotal)}` : "—";

    const sum = (Number.isFinite(laborTotal) ? laborTotal : 0) + (Number.isFinite(partsTotal) ? partsTotal : 0);
    if (blockElTotal) {
      blockElTotal.textContent = (Number.isFinite(laborTotal) || Number.isFinite(partsTotal)) ? `$${money(round2(sum))}` : "—";
    }
  }

  function recalcBlock(blockEl, pricing, laborRates) {
    ensureTrailingEmptyRow(blockEl);
    const laborTotal = calcLaborTotal(blockEl, laborRates);
    const partsTotal = calcPartsTotal(blockEl, pricing);
    setBlockTotalsUI(blockEl, laborTotal, partsTotal);
    return (Number.isFinite(laborTotal) ? laborTotal : 0) + (Number.isFinite(partsTotal) ? partsTotal : 0);
  }

  function recalcAll(blocksContainer, pricing, laborRates) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-block"));
    let grand = 0;
    for (const b of blocks) grand += recalcBlock(b, pricing, laborRates);
    grand = round2(grand);

    const grandEl = $("grandTotalDisplay");
    if (grandEl) grandEl.textContent = blocks.length ? `$${money(grand)}` : "—";

    const cnt = $("blockCount");
    if (cnt) cnt.textContent = String(blocks.length);

    // enable/disable remove buttons
    blocks.forEach((b, idx) => {
      const btn = b.querySelector(".removeBlockBtn");
      if (!btn) return;
      btn.disabled = blocks.length <= 1;
    });
  }

  // ---------------- backend search dropdown ----------------
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
    dd._targetInput = null;
    dd._targetRow = null;
    dd._targetBlock = null;
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderDropdown(dd, items) {
    dd._items = items || [];
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

  async function fetchParts(q) {
    const url = `/work_orders/api/parts/search?q=${encodeURIComponent(q)}&limit=20`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.items) ? data.items : [];
  }

  function fillRowFromPart(tr, part) {
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

  const debouncedSearch = debounce(async function (dd, inputEl, tr, blockEl) {
    const q = String(inputEl.value || "").trim();
    if (q.length < 3) { hideDropdown(dd); return; }

    placeDropdownNearInput(dd, inputEl);
    dd.style.display = "block";
    dd.innerHTML = `<div style="padding:10px; color:#6c757d;">Searching…</div>`;

    const items = await fetchParts(q);
    dd._targetInput = inputEl;
    dd._targetRow = tr;
    dd._targetBlock = blockEl;
    renderDropdown(dd, items);
  }, 150);

  // ---------------- blocks add/remove ----------------
  function renumberBlock(blockEl, idx, laborRates) {
    blockEl.dataset.blockIndex = String(idx);
    blockEl.querySelector(".block-number").textContent = String(idx + 1);

    // labor names
    blockEl.querySelector(".labor-description").name = `blocks[${idx}][labor_description]`;
    blockEl.querySelector(".labor-hours").name = `blocks[${idx}][labor_hours]`;
    blockEl.querySelector(".labor-rate").name = `blocks[${idx}][labor_rate_code]`;

    // parts names
    const tbody = blockEl.querySelector(".partsTbody");
    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));
    rows.forEach((tr, rIdx) => {
      tr.dataset.index = String(rIdx);
      tr.querySelector(".part-number").name = `blocks[${idx}][parts][${rIdx}][part_number]`;
      tr.querySelector(".part-description").name = `blocks[${idx}][parts][${rIdx}][description]`;
      tr.querySelector(".part-qty").name = `blocks[${idx}][parts][${rIdx}][qty]`;
      tr.querySelector(".part-cost").name = `blocks[${idx}][parts][${rIdx}][cost]`;
    });
  }

  function cloneBlock(blocksContainer, laborRates) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-block"));
    const last = blocks[blocks.length - 1];
    const clone = last.cloneNode(true);

    // wipe values
    clone.querySelectorAll("input").forEach(i => {
      if (i.classList.contains("part-price")) return;
      i.value = "";
    });
    clone.querySelectorAll(".part-line-total").forEach(td => td.innerHTML = `<span class="text-muted">—</span>`);
    clone.querySelectorAll(".laborTotalDisplay, .partsTotalDisplay, .blockTotalDisplay").forEach(el => el.textContent = "—");

    // reset parts table to single row
    const tbody = clone.querySelector(".partsTbody");
    tbody.innerHTML = "";
    tbody.appendChild(makePartsRow(blocks.length, 0));

    blocksContainer.appendChild(clone);
    return clone;
  }

  function wireBlockEvents(blocksContainer, pricing, laborRates) {
    // One handler for all inputs
    blocksContainer.addEventListener("input", function (e) {
      const t = e.target;
      if (!t) return;
      const blockEl = t.closest(".wo-block");
      if (!blockEl) return;
      recalcAll(blocksContainer, pricing, laborRates);
    });

    // remove block
    blocksContainer.addEventListener("click", function (e) {
      const btn = e.target.closest(".removeBlockBtn");
      if (!btn) return;

      const blocks = Array.from(blocksContainer.querySelectorAll(".wo-block"));
      if (blocks.length <= 1) return;

      const blockEl = btn.closest(".wo-block");
      if (!blockEl) return;

      blockEl.remove();

      // renumber blocks and parts names
      Array.from(blocksContainer.querySelectorAll(".wo-block")).forEach((b, idx) => renumberBlock(b, idx, laborRates));

      recalcAll(blocksContainer, pricing, laborRates);
    });
  }

  // ---------------- init ----------------
  document.addEventListener("DOMContentLoaded", function () {
    const laborRates = readJsonScript("laborRatesData", []);
    const pricing = readJsonScript("partsPricingRulesData", null);

    const blocksContainer = $("blocksContainer");
    if (!blocksContainer) return;

    // dropdown
    const dd = ensureDropdown();

    dd.addEventListener("mousedown", function (e) {
      const itemEl = e.target.closest(".parts-dd-item");
      if (!itemEl) return;
      e.preventDefault();

      const idx = Number(itemEl.dataset.idx);
      const it = dd._items?.[idx];
      const tr = dd._targetRow;
      const blockEl = dd._targetBlock;
      if (!it || !tr || !blockEl) return;

      fillRowFromPart(tr, it);
      hideDropdown(dd);
      recalcAll(blocksContainer, pricing, laborRates);
    });

    document.addEventListener("click", function (e) {
      if (dd.style.display === "none") return;
      if (e.target.closest("#partsSearchDropdown")) return;
      if (e.target.closest(".part-number") || e.target.closest(".part-description")) return;
      hideDropdown(dd);
    });

    window.addEventListener("scroll", () => { if (dd.style.display !== "none") hideDropdown(dd); }, true);
    window.addEventListener("resize", () => { if (dd.style.display !== "none") hideDropdown(dd); });

    // wire search on focusin (event delegation, works for new rows/blocks)
    blocksContainer.addEventListener("focusin", function (e) {
      const inputEl = e.target;
      if (!(inputEl instanceof HTMLInputElement)) return;

      if (!(inputEl.classList.contains("part-number") || inputEl.classList.contains("part-description"))) return;

      const tr = inputEl.closest("tr.parts-row");
      const blockEl = inputEl.closest(".wo-block");
      if (!tr || !blockEl) return;

      inputEl.addEventListener("input", () => debouncedSearch(dd, inputEl, tr, blockEl));
      inputEl.addEventListener("focus", () => debouncedSearch(dd, inputEl, tr, blockEl));

      debouncedSearch(dd, inputEl, tr, blockEl);
    }, { passive: true });

    // add block button
    const addBtn = $("addBlockBtn");
    addBtn?.addEventListener("click", function () {
      cloneBlock(blocksContainer, laborRates);

      // renumber all blocks and their input names
      Array.from(blocksContainer.querySelectorAll(".wo-block")).forEach((b, idx) => renumberBlock(b, idx, laborRates));

      recalcAll(blocksContainer, pricing, laborRates);
    });

    wireBlockEvents(blocksContainer, pricing, laborRates);

    // initial ensure rows/totals
    Array.from(blocksContainer.querySelectorAll(".wo-block")).forEach((b, idx) => renumberBlock(b, idx, laborRates));
    recalcAll(blocksContainer, pricing, laborRates);
  });
})();
