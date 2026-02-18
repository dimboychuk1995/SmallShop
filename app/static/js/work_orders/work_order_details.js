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

  function parseMoneyText(v) {
    if (v === null || v === undefined) return 0;
    const s = String(v).replace(/[^0-9.-]/g, "").trim();
    const n = Number(s);
    return Number.isFinite(n) ? n : 0;
  }

  function money(n) { return Number.isFinite(n) ? n.toFixed(2) : ""; }
  function round2(n) { return Math.round(n * 100) / 100; }

  function toast(msg) {
    // если у тебя есть SweetAlert — можно заменить на Swal.fire(...)
    alert(msg);
  }

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

  function getCustomerDefaultLaborRate(customers, customerId) {
    if (!Array.isArray(customers) || !customerId) return "";
    const found = customers.find(x => String(x.id || "") === String(customerId));
    if (!found) return "";
    return String(found.default_labor_rate || "").trim();
  }

  function normalizeRateKey(v) {
    const key = String(v || "")
      .trim()
      .toLowerCase()
      .replace(/[_\-\s]+/g, "");
    if (key === "standart") return "standard";
    return key;
  }

  function selectRateIfExists(selectEl, rateCode) {
    if (!selectEl || !rateCode) return false;
    const targetKey = normalizeRateKey(rateCode);
    const options = Array.from(selectEl.options || []);

    for (const opt of options) {
      if (!String(opt.value || "").trim()) continue;

      const optionCodeKey = normalizeRateKey(opt.value);
      const optionName = String(opt.textContent || "").split("(")[0].trim();
      const optionNameKey = normalizeRateKey(optionName);

      if (optionCodeKey === targetKey || optionNameKey === targetKey) {
        selectEl.value = String(opt.value);
        return true;
      }
    }

    return false;
  }

  function applyDefaultLaborRateToAll(blocksContainer, rateCode, onlyIfEmpty) {
    if (!blocksContainer || !rateCode) return;
    const selects = Array.from(blocksContainer.querySelectorAll(".wo-labor .labor-rate"));
    selects.forEach((sel) => {
      const current = String(sel.value || "").trim();
      if (onlyIfEmpty && current) return;
      selectRateIfExists(sel, rateCode);
    });
  }

  function applyDefaultLaborRateToBlock(blockEl, rateCode, onlyIfEmpty) {
    if (!blockEl || !rateCode) return;
    const sel = blockEl.querySelector(".labor-rate");
    if (!sel) return;
    const current = String(sel.value || "").trim();
    if (onlyIfEmpty && current) return;
    selectRateIfExists(sel, rateCode);
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
  function makePartsRow(laborIndex, rowIndex) {
    const tr = document.createElement("tr");
    tr.className = "parts-row";
    tr.dataset.index = String(rowIndex);

    tr.innerHTML = `
      <td><input class="form-control form-control-sm part-number" name="labors[${laborIndex}][parts][${rowIndex}][part_number]" maxlength="64" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-description" name="labors[${laborIndex}][parts][${rowIndex}][description]" maxlength="200" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-qty" name="labors[${laborIndex}][parts][${rowIndex}][qty]" inputmode="numeric"></td>
      <td><input class="form-control form-control-sm part-cost" name="labors[${laborIndex}][parts][${rowIndex}][cost]" inputmode="decimal" readonly tabindex="-1"></td>
      <td><input class="form-control form-control-sm part-price" name="labors[${laborIndex}][parts][${rowIndex}][price]" value="" inputmode="decimal"></td>
      <td class="part-line-total"><span class="text-muted">—</span></td>
    `;
    return tr;
  }

  function rowHasAnyInput(tr) {
    const pn = tr.querySelector(".part-number")?.value || "";
    const ds = tr.querySelector(".part-description")?.value || "";
    const q = tr.querySelector(".part-qty")?.value || "";
    const c = tr.querySelector(".part-cost")?.value || "";
    const p = tr.querySelector(".part-price")?.value || "";
    return !!(String(pn).trim() || String(ds).trim() || String(q).trim() || String(c).trim() || String(p).trim());
  }

  function clearRowCalc(tr) {
    const lineCell = tr.querySelector(".part-line-total");
    if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
  }

  function calcRowLineTotal(tr, pricing) {
    const qty = toNum(tr.querySelector(".part-qty")?.value);
    const cost = toNum(tr.querySelector(".part-cost")?.value);
    const priceInput = tr.querySelector(".part-price");
    const lineCell = tr.querySelector(".part-line-total");

    let price = toNum(priceInput?.value);

    if (price === null && Number.isFinite(cost) && cost >= 0 && !tr.dataset.priceAutofilled) {
      if (pricing && Array.isArray(pricing.rules) && pricing.rules.length > 0) {
        const rule = matchRule(cost, pricing.rules);
        if (rule) {
          const autoPrice = calcPriceFromRule(cost, pricing.mode, rule.value_percent);
          if (autoPrice !== null && priceInput) {
            priceInput.value = money(autoPrice);
            tr.dataset.priceAutofilled = "1";
            price = autoPrice;
          }
        }
      }
    }

    if (qty === null || qty <= 0 || price === null || price < 0) {
      clearRowCalc(tr);
      return null;
    }

    const lt = round2(price * qty);
    if (lineCell) lineCell.innerHTML = `<strong>$${money(lt)}</strong>`;
    return lt;
  }

  function ensureTrailingEmptyRow(blockEl) {
    const tbody = blockEl.querySelector(".partsTbody");
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));
    if (rows.length === 0) {
      tbody.appendChild(makePartsRow(Number(blockEl.dataset.laborIndex), 0));
      return;
    }

    const last = rows[rows.length - 1];
    if (rowHasAnyInput(last)) {
      tbody.appendChild(makePartsRow(Number(blockEl.dataset.laborIndex), rows.length));
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
    const blockElTotal = blockEl.querySelector(".laborFullTotalDisplay");

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
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
    let grand = 0;
    for (const b of blocks) grand += recalcBlock(b, pricing, laborRates);
    grand = round2(grand);

    const grandEl = $("grandTotalDisplay");
    if (grandEl) grandEl.textContent = blocks.length ? `$${money(grand)}` : "—";

    const cnt = $("laborCount");
    if (cnt) cnt.textContent = String(blocks.length);

    blocks.forEach((b) => {
      const btn = b.querySelector(".removeLaborBtn");
      if (!btn) return;
      btn.disabled = blocks.length <= 1;
    });
  }

  // ---------------- totals serialization (FRONT -> BACK) ----------------
  function serializeTotals(blocksContainer) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
    const outBlocks = [];

    let laborSum = 0;
    let partsSum = 0;
    let grandSum = 0;

    blocks.forEach((bEl) => {
      const laborText = bEl.querySelector(".laborTotalDisplay")?.textContent || "0";
      const partsText = bEl.querySelector(".partsTotalDisplay")?.textContent || "0";
      const blockText = bEl.querySelector(".laborFullTotalDisplay")?.textContent || "0";

      const laborTotal = round2(parseMoneyText(laborText));
      const partsTotal = round2(parseMoneyText(partsText));
      const blockTotal = round2(parseMoneyText(blockText));

      laborSum += laborTotal;
      partsSum += partsTotal;
      grandSum += blockTotal;

      outBlocks.push({
        labor_total: laborTotal,
        parts_total: partsTotal,
        labor_full_total: blockTotal,
      });
    });

    // grand_total берём из UI, но если там "—" / пусто — пересчитаем из блоков
    const grandText = $("grandTotalDisplay")?.textContent || "";
    const grandUi = round2(parseMoneyText(grandText));
    const grandFinal = grandUi > 0 ? grandUi : round2(grandSum);

    return {
      labor_total: round2(laborSum),
      parts_total: round2(partsSum),
      grand_total: grandFinal,
      labors: outBlocks,
    };
  }

  function upsertHiddenJsonInput(formEl, name, obj) {
    if (!formEl) return;
    let input = formEl.querySelector(`input[name="${CSS.escape(name)}"]`);
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      formEl.appendChild(input);
    }
    input.value = JSON.stringify(obj || {});
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

    const price = tr.querySelector(".part-price");
    if (price) price.value = "";
    delete tr.dataset.priceAutofilled;
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
  function renumberBlock(blockEl, idx) {
    blockEl.dataset.laborIndex = String(idx);
    blockEl.querySelector(".labor-number").textContent = String(idx + 1);

    blockEl.querySelector(".labor-description").name = `labors[${idx}][labor_description]`;
    blockEl.querySelector(".labor-hours").name = `labors[${idx}][labor_hours]`;
    blockEl.querySelector(".labor-rate").name = `labors[${idx}][labor_rate_code]`;

    const tbody = blockEl.querySelector(".partsTbody");
    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));
    rows.forEach((tr, rIdx) => {
      tr.dataset.index = String(rIdx);
      tr.querySelector(".part-number").name = `labors[${idx}][parts][${rIdx}][part_number]`;
      tr.querySelector(".part-description").name = `labors[${idx}][parts][${rIdx}][description]`;
      tr.querySelector(".part-qty").name = `labors[${idx}][parts][${rIdx}][qty]`;
      tr.querySelector(".part-cost").name = `labors[${idx}][parts][${rIdx}][cost]`;
      tr.querySelector(".part-price").name = `labors[${idx}][parts][${rIdx}][price]`;
    });
  }

  function cloneBlock(blocksContainer) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
    const last = blocks[blocks.length - 1];
    const clone = last.cloneNode(true);

    clone.querySelectorAll("input").forEach(i => {
      i.value = "";
    });
    clone.querySelectorAll(".part-line-total").forEach(td => td.innerHTML = `<span class="text-muted">—</span>`);
    clone.querySelectorAll(".laborTotalDisplay, .partsTotalDisplay, .laborFullTotalDisplay").forEach(el => el.textContent = "—");

    const tbody = clone.querySelector(".partsTbody");
    tbody.innerHTML = "";
    tbody.appendChild(makePartsRow(blocks.length, 0));

    blocksContainer.appendChild(clone);
    return clone;
  }

  function wireBlockEvents(blocksContainer, pricing, laborRates) {
    blocksContainer.addEventListener("input", function (e) {
      const t = e.target;
      if (!t) return;
      const blockEl = t.closest(".wo-labor");
      if (!blockEl) return;
      recalcAll(blocksContainer, pricing, laborRates);
    });

    blocksContainer.addEventListener("click", function (e) {
      const btn = e.target.closest(".removeLaborBtn");
      if (!btn) return;

      const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
      if (blocks.length <= 1) return;

      const blockEl = btn.closest(".wo-labor");
      if (!blockEl) return;

      blockEl.remove();
      Array.from(blocksContainer.querySelectorAll(".wo-labor")).forEach((b, idx) => renumberBlock(b, idx));
      recalcAll(blocksContainer, pricing, laborRates);
    });
  }

  // ---------------- customer/unit ----------------
  function setSelectOptions(selectEl, items, placeholder) {
    if (!selectEl) return;
    selectEl.innerHTML = "";

    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = placeholder || "-- Select --";
    selectEl.appendChild(ph);

    (items || []).forEach(it => {
      const opt = document.createElement("option");
      opt.value = String(it.id || "");
      opt.textContent = String(it.label || "");
      selectEl.appendChild(opt);
    });
  }

  async function fetchUnits(customerId) {
    const url = `/work_orders/api/units?customer_id=${encodeURIComponent(customerId)}`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.items) ? data.items : [];
  }

  // ---------------- restore draft ----------------
  function ensureBlocksCount(blocksContainer, desiredCount) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
    while (blocks.length < desiredCount) {
      cloneBlock(blocksContainer);
      blocks.push(blocksContainer.querySelectorAll(".wo-labor")[blocks.length]);
    }
    Array.from(blocksContainer.querySelectorAll(".wo-labor")).forEach((b, idx) => renumberBlock(b, idx));
  }

  function applyDraftToUi(blocksContainer, draftBlocks) {
    if (!Array.isArray(draftBlocks) || draftBlocks.length === 0) return;

    ensureBlocksCount(blocksContainer, draftBlocks.length);
    const blockEls = Array.from(blocksContainer.querySelectorAll(".wo-labor"));

    draftBlocks.forEach((b, bIdx) => {
      const el = blockEls[bIdx];
      if (!el) return;

      const ld = el.querySelector(".labor-description");
      const lh = el.querySelector(".labor-hours");
      const lr = el.querySelector(".labor-rate");

      const laborDesc = (b?.labor?.description ?? b?.labor_description ?? "");
      const laborHours = (b?.labor?.hours ?? b?.labor_hours ?? "");
      const laborRate = (b?.labor?.rate_code ?? b?.labor_rate_code ?? "");

      if (ld) ld.value = String(laborDesc ?? "");
      if (lh) lh.value = String(laborHours ?? "");
      if (lr) lr.value = String(laborRate ?? "");

      const tbody = el.querySelector(".partsTbody");
      if (!tbody) return;

      tbody.innerHTML = "";

      const parts = Array.isArray(b?.parts) ? b.parts : [];
      if (parts.length === 0) {
        tbody.appendChild(makePartsRow(bIdx, 0));
        return;
      }

      parts.forEach((p, rIdx) => {
        const tr = makePartsRow(bIdx, rIdx);
        tr.querySelector(".part-number").value = String(p?.part_number ?? "");
        tr.querySelector(".part-description").value = String(p?.description ?? "");
        tr.querySelector(".part-qty").value = String(p?.qty ?? "");
        tr.querySelector(".part-cost").value = String(p?.cost ?? "");
        tr.querySelector(".part-price").value = String(p?.price ?? "");
        if (String(p?.price ?? "").trim()) tr.dataset.priceAutofilled = "1";
        tbody.appendChild(tr);
      });

      tbody.appendChild(makePartsRow(bIdx, parts.length));
    });

    Array.from(blocksContainer.querySelectorAll(".wo-labor")).forEach((b, idx) => renumberBlock(b, idx));
  }

  // ---------------- serialize current UI -> blocks[] ----------------
  function serializeBlocks(blocksContainer) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
    const out = [];

    blocks.forEach((bEl) => {
      const labor_description = String(bEl.querySelector(".labor-description")?.value || "").trim();
      const labor_hours = String(bEl.querySelector(".labor-hours")?.value || "").trim();
      const labor_rate_code = String(bEl.querySelector(".labor-rate")?.value || "").trim();

      const parts = [];
      const rows = Array.from(bEl.querySelectorAll("tbody.partsTbody tr.parts-row"));
      rows.forEach((tr) => {
        const part_number = String(tr.querySelector(".part-number")?.value || "").trim();
        const description = String(tr.querySelector(".part-description")?.value || "").trim();
        const qty = String(tr.querySelector(".part-qty")?.value || "").trim();
        const cost = String(tr.querySelector(".part-cost")?.value || "").trim();
        const price = String(tr.querySelector(".part-price")?.value || "").trim();
        if (!(part_number || description || qty || cost || price)) return;
        parts.push({
          part_number,
          description,
          qty: qty === "" ? 0 : Number(qty),
          cost: cost === "" ? 0 : Number(cost),
          price: price === "" ? 0 : Number(price),
        });
      });

      out.push({
        labor_description,
        labor_hours: labor_hours === "" ? 0 : Number(labor_hours),
        labor_rate_code,
        parts,
      });
    });

    return out;
  }

  // ---------------- API ----------------
  async function apiPostJson(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body || {}),
    });

    let data = null;
    try { data = await res.json(); } catch { data = null; }

    if (!res.ok) {
      const msg = (data && (data.error || data.message)) ? (data.error || data.message) : `Request failed (${res.status})`;
      throw new Error(msg);
    }

    return data;
  }

  // ---------------- UI state ----------------
  function setEditingMode(isEditing, els) {
    const { editor, customerSel, unitSel, addUnitBtn, addLaborBtn } = els;

    if (!editor) return;

    if (isEditing) {
      editor.style.pointerEvents = "";
      editor.style.opacity = "";
      // При редактировании разрешаем менять customer/unit
      if (customerSel) customerSel.disabled = false;
      if (unitSel) unitSel.disabled = false;
      if (addUnitBtn) addUnitBtn.disabled = false;
      if (addLaborBtn) addLaborBtn.disabled = false;
      document.querySelectorAll(".removeLaborBtn").forEach(b => { b.disabled = false; });
    } else {
      editor.style.pointerEvents = "none";
      editor.style.opacity = "0.75";
      if (customerSel) customerSel.disabled = true;
      if (unitSel) unitSel.disabled = true;
      if (addUnitBtn) addUnitBtn.disabled = true;
      if (addLaborBtn) addLaborBtn.disabled = true;
      document.querySelectorAll(".removeLaborBtn").forEach(b => { b.disabled = true; });
    }
  }

  function setButtonsState(mode, els) {
    // mode: "creating" | "created_locked_open" | "editing_open" | "paid"
    const { createBtn, editBtn, saveBtn, paidBtn, unpaidBtn } = els;

    const show = (el, v) => { if (el) el.style.display = v ? "" : "none"; };
    const enable = (el, v) => { if (el) el.disabled = !v; };

    if (mode === "creating") {
      show(createBtn, true); enable(createBtn, false);
      if (createBtn) createBtn.textContent = "Creating…";
      show(editBtn, false);
      show(saveBtn, false);
      show(paidBtn, false);
      show(unpaidBtn, false);
      return;
    }

    if (mode === "created_locked_open") {
      show(createBtn, false);
      show(editBtn, true); enable(editBtn, true);
      show(saveBtn, false);
      show(paidBtn, true); enable(paidBtn, true);
      show(unpaidBtn, false);
      return;
    }

    if (mode === "editing_open") {
      show(createBtn, false);
      show(editBtn, false);
      show(saveBtn, true); enable(saveBtn, true);
      show(paidBtn, true); enable(paidBtn, false); // пока редактируем — paid запрещаем
      show(unpaidBtn, false);
      return;
    }

    if (mode === "paid") {
      show(createBtn, false);
      show(editBtn, false);
      show(saveBtn, false);
      show(paidBtn, false);
      show(unpaidBtn, true); enable(unpaidBtn, true);
      return;
    }
  }

  // ---------------- init ----------------
  document.addEventListener("DOMContentLoaded", function () {
    const customersData = readJsonScript("customersData", []);
    const laborRates = readJsonScript("laborRatesData", []);
    const pricing = readJsonScript("partsPricingRulesData", null);

    const blocksContainer = $("laborsContainer");
    if (!blocksContainer) return;

    const customerSel = $("customerSelect");
    const unitSel = $("unitSelect");
    const editor = $("workOrderEditor");
    const hint = $("selectHint");

    const customerHidden = $("selectedCustomerHidden");
    const unitHidden = $("selectedUnitHidden");
    const createUnitCustomerHidden = $("createUnitCustomerHidden");

    const woForm = $("workOrderForm");
    const actionHidden = $("actionHidden");

    const createBtn = $("createWorkOrderBtn");
    const editBtn = $("editWorkOrderBtn");
    const saveBtn = $("saveWorkOrderBtn");
    const paidBtn = $("paidWorkOrderBtn");
    const unpaidBtn = $("unpaidWorkOrderBtn");

    const addLaborBtn = $("addLaborBtn");
    const addUnitBtn = $("addUnitBtn");

    const els = {
      editor, customerSel, unitSel, addUnitBtn, addLaborBtn,
      createBtn, editBtn, saveBtn, paidBtn, unpaidBtn
    };

    function setEditorEnabled(enabled) {
      if (editor) editor.disabled = !enabled;
      if (hint) hint.style.display = enabled ? "none" : "";
    }

    function submitWithAction(action) {
      if (!woForm) return;
      if (actionHidden) actionHidden.value = action;

      // ✅ перед отправкой формы на create/recalc кладём totals_json
      const totals = serializeTotals(blocksContainer);
      upsertHiddenJsonInput(woForm, "totals_json", totals);

      if (typeof woForm.requestSubmit === "function") woForm.requestSubmit();
      else woForm.submit();

      if (action === "create") {
        setButtonsState("creating", els);
      }
    }

    // create still uses normal form POST
    createBtn?.addEventListener("click", () => submitWithAction("create"));

    // ---------- restore draft FIRST ----------
    const draftBlocks = readJsonScript("workOrderDraftData", []);
    applyDraftToUi(blocksContainer, draftBlocks);

    // wire + totals
    wireBlockEvents(blocksContainer, pricing, laborRates);
    Array.from(blocksContainer.querySelectorAll(".wo-labor")).forEach((b, idx) => renumberBlock(b, idx));
    recalcAll(blocksContainer, pricing, laborRates);

    // initial enable state (before create)
    setEditorEnabled(!!(unitSel && String(unitSel.value || "").trim()));

    // customer/unit change (только пока НЕ создано)
    customerSel?.addEventListener("change", async function () {
      const customerId = String(customerSel.value || "").trim();
      if (customerHidden) customerHidden.value = customerId;
      if (createUnitCustomerHidden) createUnitCustomerHidden.value = customerId;
      if (addUnitBtn) addUnitBtn.disabled = !customerId;

      const defaultRateCode = getCustomerDefaultLaborRate(customersData, customerId);
      applyDefaultLaborRateToAll(blocksContainer, defaultRateCode, false);
      recalcAll(blocksContainer, pricing, laborRates);

      if (unitHidden) unitHidden.value = "";
      if (unitSel) {
        unitSel.disabled = !customerId;
        setSelectOptions(unitSel, [], customerId ? "Loading…" : "-- Select unit --");
        unitSel.value = "";
      }

      setEditorEnabled(false);

      if (!customerId || !unitSel) return;
      const units = await fetchUnits(customerId);
      setSelectOptions(unitSel, units, "-- Select unit --");
      unitSel.disabled = false;

      if (Array.isArray(units) && units.length === 0) {
        const createUnitModalEl = $("createUnitModal");
        if (createUnitModalEl && window.bootstrap && window.bootstrap.Modal) {
          const modal = window.bootstrap.Modal.getOrCreateInstance(createUnitModalEl);
          modal.show();
        }
      }
    });

    unitSel?.addEventListener("change", function () {
      const unitId = String(unitSel.value || "").trim();
      if (unitHidden) unitHidden.value = unitId;
      setEditorEnabled(!!unitId);
    });

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
      hideDropdown(dd);
    });

    document.addEventListener("scroll", function () {
      if (dd.style.display !== "none") hideDropdown(dd);
    }, { passive: true });

    // bind search on inputs (part-number / part-description)
    blocksContainer.addEventListener("focusin", function (e) {
      const target = e.target;
      if (!(target instanceof HTMLInputElement)) return;

      if (!(target.classList.contains("part-number") || target.classList.contains("part-description"))) return;

      const tr = target.closest("tr.parts-row");
      const blockEl = target.closest(".wo-labor");
      if (!tr || !blockEl) return;

      target.addEventListener("input", () => debouncedSearch(dd, target, tr, blockEl));
      target.addEventListener("focus", () => debouncedSearch(dd, target, tr, blockEl));
      debouncedSearch(dd, target, tr, blockEl);
    }, { passive: true });

    addLaborBtn?.addEventListener("click", function () {
      const cloned = cloneBlock(blocksContainer);
      Array.from(blocksContainer.querySelectorAll(".wo-labor")).forEach((b, idx) => renumberBlock(b, idx));

      const customerId = String(customerSel?.value || "").trim();
      const defaultRateCode = getCustomerDefaultLaborRate(customersData, customerId);
      applyDefaultLaborRateToBlock(cloned, defaultRateCode, true);

      recalcAll(blocksContainer, pricing, laborRates);
    });

    // ---------- created/paid state ----------
    let workOrderId = "";
    let workOrderStatus = "open"; // "open" | "paid"
    let isCreated = false;

    const createdInfo = readJsonScript("workOrderCreatedData", { created: false, id: "", status: "open" });
    if (createdInfo && createdInfo.created && createdInfo.id) {
      isCreated = true;
      workOrderId = String(createdInfo.id);
      workOrderStatus = String(createdInfo.status || "open");
    }

    function applyStateFromStatus() {
      if (!isCreated) {
        // до create: только create, форма активна по unit
        setButtonsState("created_locked_open", els); // не показываем
        if (createBtn) createBtn.style.display = "";
        if (editBtn) editBtn.style.display = "none";
        if (saveBtn) saveBtn.style.display = "none";
        if (paidBtn) paidBtn.style.display = "none";
        if (unpaidBtn) unpaidBtn.style.display = "none";
        return;
      }

      // created: customer/unit больше не меняем
      if (customerSel) customerSel.disabled = true;
      if (unitSel) unitSel.disabled = true;
      if (addUnitBtn) addUnitBtn.disabled = true;

      if (workOrderStatus === "paid") {
        setEditingMode(false, els);
        setButtonsState("paid", els);
      } else {
        setEditingMode(false, els);
        setButtonsState("created_locked_open", els);
      }
    }

    // edit -> enable
    editBtn?.addEventListener("click", function () {
      if (!isCreated || !workOrderId) return;
      if (workOrderStatus === "paid") return;

      setEditingMode(true, els);
      setButtonsState("editing_open", els);
    });

    // save -> API update labors + totals
    saveBtn?.addEventListener("click", async function () {
      if (!isCreated || !workOrderId) return;

      try {
        const labors = serializeBlocks(blocksContainer);
        const totals = serializeTotals(blocksContainer);

        await apiPostJson(
          `/work_orders/api/work_orders/${encodeURIComponent(workOrderId)}/update`,
          { labors, totals }
        );

        // после сохранения снова лочим
        setEditingMode(false, els);
        setButtonsState("created_locked_open", els);
        toast("Saved.");
      } catch (e) {
        toast(e.message || "Save failed.");
      }
    });

    // paid -> status paid
    paidBtn?.addEventListener("click", async function () {
      if (!isCreated || !workOrderId) return;

      try {
        await apiPostJson(`/work_orders/api/work_orders/${encodeURIComponent(workOrderId)}/status`, { status: "paid" });
        workOrderStatus = "paid";
        applyStateFromStatus();
        toast("Marked as paid.");
      } catch (e) {
        toast(e.message || "Failed to set paid.");
      }
    });

    // unpaid -> back to open and show edit again
    unpaidBtn?.addEventListener("click", async function () {
      if (!isCreated || !workOrderId) return;

      try {
        await apiPostJson(`/work_orders/api/work_orders/${encodeURIComponent(workOrderId)}/status`, { status: "open" });
        workOrderStatus = "open";
        applyStateFromStatus();
        toast("Marked as unpaid.");
      } catch (e) {
        toast(e.message || "Failed to set unpaid.");
      }
    });

    // initial state
    if (addUnitBtn) {
      const initialCustomerId = String(customerSel?.value || "").trim();
      addUnitBtn.disabled = !initialCustomerId;
    }

    const initialCustomerId = String(customerSel?.value || "").trim();
    const initialDefaultRateCode = getCustomerDefaultLaborRate(customersData, initialCustomerId);
    applyDefaultLaborRateToAll(blocksContainer, initialDefaultRateCode, true);
    recalcAll(blocksContainer, pricing, laborRates);

    applyStateFromStatus();
  });
})();
