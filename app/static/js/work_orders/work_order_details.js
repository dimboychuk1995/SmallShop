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
  function escapeText(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

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
      <td>
        <input class="form-control form-control-sm part-number" name="labors[${laborIndex}][parts][${rowIndex}][part_number]" maxlength="64" autocomplete="off">
        <input type="hidden" class="part-core-charge" name="labors[${laborIndex}][parts][${rowIndex}][core_charge]" value="0">
        <input type="hidden" class="part-misc-charge" name="labors[${laborIndex}][parts][${rowIndex}][misc_charge]" value="0">
        <input type="hidden" class="part-misc-charge-description" name="labors[${laborIndex}][parts][${rowIndex}][misc_charge_description]" value="">
      </td>
      <td><input class="form-control form-control-sm part-description" name="labors[${laborIndex}][parts][${rowIndex}][description]" maxlength="200" autocomplete="off"></td>
      <td><input class="form-control form-control-sm part-qty" name="labors[${laborIndex}][parts][${rowIndex}][qty]" inputmode="numeric"></td>
      <td>
        <input class="form-control form-control-sm part-cost" name="labors[${laborIndex}][parts][${rowIndex}][cost]" inputmode="decimal" readonly tabindex="-1">
        <div class="small text-muted mt-1 part-charges-meta"></div>
      </td>
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
    const core = toNum(tr.querySelector(".part-core-charge")?.value);
    const misc = toNum(tr.querySelector(".part-misc-charge")?.value);
    const miscDesc = tr.querySelector(".part-misc-charge-description")?.value || "";
    const hasCharges = (Number.isFinite(core) && core > 0) || (Number.isFinite(misc) && misc > 0);
    return !!(String(pn).trim() || String(ds).trim() || String(q).trim() || String(c).trim() || String(p).trim() || hasCharges || String(miscDesc).trim());
  }

  function getRowMiscItems(tr) {
    const raw = String(tr.querySelector(".part-misc-charge-description")?.value || "").trim();
    if (!raw) return [];

    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map((x) => ({
          description: String(x?.description || "").trim(),
          price: toNum(x?.price),
        }))
        .filter((x) => x.description);
    } catch {
      return raw
        .split("|")
        .map((x) => ({ description: String(x || "").trim(), price: null }))
        .filter((x) => x.description);
    }
  }

  function getRowCharges(tr) {
    const coreRaw = toNum(tr.querySelector(".part-core-charge")?.value);
    const miscRaw = toNum(tr.querySelector(".part-misc-charge")?.value);

    const coreCharge = Number.isFinite(coreRaw) && coreRaw > 0 ? round2(coreRaw) : 0;
    const miscCharge = Number.isFinite(miscRaw) && miscRaw > 0 ? round2(miscRaw) : 0;
    return { coreCharge, miscCharge };
  }

  function setRowChargesMeta(tr) {
    const metaEl = tr.querySelector(".part-charges-meta");
    if (!metaEl) return;
    const { coreCharge } = getRowCharges(tr);
    if (coreCharge <= 0) {
      metaEl.textContent = "";
      return;
    }
    metaEl.textContent = `Core: $${money(coreCharge)}`;
  }

  function clearRowCalc(tr) {
    const lineCell = tr.querySelector(".part-line-total");
    if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
    setRowChargesMeta(tr);
  }

  function calcRowLineTotal(tr, pricing) {
    const qty = toNum(tr.querySelector(".part-qty")?.value);
    const cost = toNum(tr.querySelector(".part-cost")?.value);
    const priceInput = tr.querySelector(".part-price");
    const lineCell = tr.querySelector(".part-line-total");
    const { coreCharge, miscCharge } = getRowCharges(tr);
    setRowChargesMeta(tr);

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

    const unitTotal = round2(price + coreCharge);
    const lt = round2(unitTotal * qty);
    if (lineCell) {
      const chips = [];
      if (coreCharge > 0) chips.push(`core $${money(coreCharge)}`);
      const meta = chips.length ? `<div class="small text-muted">+ ${chips.join(" • ")}</div>` : "";
      lineCell.innerHTML = `<strong>$${money(lt)}</strong>${meta}`;
    }
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
    if (!tbody) {
      return {
        partsTotal: null,
        coreTotal: 0,
        miscTotal: 0,
      };
    }

    let total = 0;
    let coreTotal = 0;
    let miscTotal = 0;
    const miscBreakdownMap = new Map();
    const rows = Array.from(tbody.querySelectorAll("tr.parts-row"));

    for (const tr of rows) {
      if (!rowHasAnyInput(tr)) {
        clearRowCalc(tr);
        continue;
      }
      const lt = calcRowLineTotal(tr, pricing);
      if (lt !== null && Number.isFinite(lt)) total += lt;

      const qty = toNum(tr.querySelector(".part-qty")?.value);
      const { coreCharge, miscCharge } = getRowCharges(tr);
      const miscItems = getRowMiscItems(tr);
      if (qty !== null && qty > 0) {
        coreTotal += round2(coreCharge * qty);
        miscTotal += round2(miscCharge * qty);

        let hadPricedItems = false;
        for (const item of miscItems) {
          if (!Number.isFinite(item.price) || item.price <= 0) continue;
          hadPricedItems = true;
          const amount = round2(item.price * qty);
          const prev = miscBreakdownMap.get(item.description) || 0;
          miscBreakdownMap.set(item.description, round2(prev + amount));
        }

        if (!hadPricedItems && miscCharge > 0) {
          const fallbackDescriptions = miscItems.map((x) => x.description).filter(Boolean);
          const fallbackKey = fallbackDescriptions.length === 1 ? fallbackDescriptions[0] : "Misc charge";
          const amount = round2(miscCharge * qty);
          const prev = miscBreakdownMap.get(fallbackKey) || 0;
          miscBreakdownMap.set(fallbackKey, round2(prev + amount));
        }
      }
    }

    total = round2(total);
    coreTotal = round2(coreTotal);
    miscTotal = round2(miscTotal);
    return {
      partsTotal: total > 0 ? total : null,
      coreTotal,
      miscTotal,
      miscBreakdown: Array.from(miscBreakdownMap.entries()).map(([description, amount]) => ({
        description,
        amount: round2(amount),
      })),
    };
  }

  // ---------------- totals per block + grand ----------------
  function setBlockTotalsUI(blockEl, laborTotal, partsTotal, coreTotal, miscTotal, miscBreakdown) {
    const laborEl = blockEl.querySelector(".laborTotalDisplay");
    const partsEl = blockEl.querySelector(".partsTotalDisplay");
    const coreWrap = blockEl.querySelector(".coreTotalWrap");
    const coreEl = blockEl.querySelector(".coreTotalDisplay");
    const miscWrap = blockEl.querySelector(".miscTotalWrap");
    const miscEl = blockEl.querySelector(".miscTotalDisplay");
    const miscDescWrap = blockEl.querySelector(".miscDescriptionsWrap");
    const miscDescEl = blockEl.querySelector(".miscDescriptionsDisplay");
    const blockElTotal = blockEl.querySelector(".laborFullTotalDisplay");

    if (laborEl) laborEl.textContent = Number.isFinite(laborTotal) ? `$${money(laborTotal)}` : "—";
    if (partsEl) partsEl.textContent = Number.isFinite(partsTotal) ? `$${money(partsTotal)}` : "—";
    const hasCore = Number.isFinite(coreTotal) && coreTotal > 0;
    const hasMisc = Number.isFinite(miscTotal) && miscTotal > 0;
    if (coreWrap) coreWrap.style.display = hasCore ? "" : "none";
    if (miscWrap) miscWrap.style.display = hasMisc ? "" : "none";
    if (coreEl) coreEl.textContent = hasCore ? `$${money(coreTotal)}` : "—";
    if (miscEl) miscEl.textContent = hasMisc ? `$${money(miscTotal)}` : "—";
    const breakdown = Array.isArray(miscBreakdown) ? miscBreakdown : [];
    const hasMiscBreakdown = breakdown.length > 0;
    const hasMiscSummary = hasMisc || hasMiscBreakdown;
    if (miscDescWrap) miscDescWrap.style.display = hasMiscSummary ? "" : "none";
    if (miscDescEl) {
      if (!hasMiscSummary) {
        miscDescEl.textContent = "—";
      } else {
        const lines = [];
        if (hasMisc) lines.push(`<div>Total: $${money(miscTotal)}</div>`);
        for (const row of breakdown) {
          if (!Number.isFinite(row.amount) || row.amount <= 0) continue;
          lines.push(`<div>${escapeText(row.description)}: $${money(row.amount)}</div>`);
        }
        miscDescEl.innerHTML = lines.join("");
      }
    }

    const sum =
      (Number.isFinite(laborTotal) ? laborTotal : 0)
      + (Number.isFinite(partsTotal) ? partsTotal : 0)
      + (Number.isFinite(miscTotal) ? miscTotal : 0);
    if (blockElTotal) {
      blockElTotal.textContent = (Number.isFinite(laborTotal) || Number.isFinite(partsTotal)) ? `$${money(round2(sum))}` : "—";
    }
  }

  function recalcBlock(blockEl, pricing, laborRates) {
    ensureTrailingEmptyRow(blockEl);
    const laborTotal = calcLaborTotal(blockEl, laborRates);
    const partsTotals = calcPartsTotal(blockEl, pricing);
    const partsTotal = partsTotals.partsTotal;
    const coreTotal = partsTotals.coreTotal;
    const miscTotal = partsTotals.miscTotal;
    const miscBreakdown = partsTotals.miscBreakdown;
    setBlockTotalsUI(blockEl, laborTotal, partsTotal, coreTotal, miscTotal, miscBreakdown);
    const labor = Number.isFinite(laborTotal) ? laborTotal : 0;
    const parts = Number.isFinite(partsTotal) ? partsTotal : 0;
    const core = Number.isFinite(coreTotal) ? coreTotal : 0;
    const misc = Number.isFinite(miscTotal) ? miscTotal : 0;
    return {
      labor,
      parts,
      core,
      misc,
      total: round2(labor + parts + misc),
    };
  }

  function recalcAll(blocksContainer, pricing, laborRates) {
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));
    let laborGrand = 0;
    let partsGrand = 0;
    let coreGrand = 0;
    let miscGrand = 0;
    let grand = 0;
    for (const b of blocks) {
      const totals = recalcBlock(b, pricing, laborRates);
      laborGrand += totals.labor;
      partsGrand += totals.parts;
      coreGrand += totals.core;
      miscGrand += totals.misc;
      grand += totals.total;
    }
    laborGrand = round2(laborGrand);
    partsGrand = round2(partsGrand);
    coreGrand = round2(coreGrand);
    miscGrand = round2(miscGrand);
    grand = round2(grand);

    const laborGrandEl = $("laborGrandTotalDisplay");
    if (laborGrandEl) laborGrandEl.textContent = blocks.length ? `$${money(laborGrand)}` : "—";

    const partsGrandEl = $("partsGrandTotalDisplay");
    if (partsGrandEl) partsGrandEl.textContent = blocks.length ? `$${money(partsGrand)}` : "—";

    const coreGrandWrap = $("coreGrandTotalWrap");
    const coreGrandEl = $("coreGrandTotalDisplay");
    const hasCoreGrand = coreGrand > 0;
    if (coreGrandWrap) coreGrandWrap.style.display = hasCoreGrand ? "" : "none";
    if (coreGrandEl) coreGrandEl.textContent = hasCoreGrand ? `$${money(coreGrand)}` : "—";

    const miscGrandWrap = $("miscGrandTotalWrap");
    const miscGrandEl = $("miscGrandTotalDisplay");
    const hasMiscGrand = miscGrand > 0;
    if (miscGrandWrap) miscGrandWrap.style.display = hasMiscGrand ? "" : "none";
    if (miscGrandEl) miscGrandEl.textContent = hasMiscGrand ? `$${money(miscGrand)}` : "—";

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
    let coreSum = 0;
    let miscSum = 0;
    let grandSum = 0;

    blocks.forEach((bEl) => {
      const laborText = bEl.querySelector(".laborTotalDisplay")?.textContent || "0";
      const partsText = bEl.querySelector(".partsTotalDisplay")?.textContent || "0";
      const blockText = bEl.querySelector(".laborFullTotalDisplay")?.textContent || "0";
      const coreText = bEl.querySelector(".coreTotalDisplay")?.textContent || "0";
      const miscText = bEl.querySelector(".miscTotalDisplay")?.textContent || "0";

      const laborTotal = round2(parseMoneyText(laborText));
      const partsTotal = round2(parseMoneyText(partsText));
      const coreTotal = round2(parseMoneyText(coreText));
      const miscTotal = round2(parseMoneyText(miscText));
      const blockTotal = round2(parseMoneyText(blockText));

      laborSum += laborTotal;
      partsSum += partsTotal;
      coreSum += coreTotal;
      miscSum += miscTotal;
      grandSum += blockTotal;

      outBlocks.push({
        labor_total: laborTotal,
        parts_total: partsTotal,
        core_total: coreTotal,
        misc_total: miscTotal,
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
      core_total: round2(coreSum),
      misc_total: round2(miscSum),
      grand_total: grandFinal,
      labors: outBlocks,
    };
  }

  function applyTotalsSnapshotToUi(blocksContainer, totals) {
    if (!totals || typeof totals !== "object" || !blocksContainer) return;

    const blockTotals = Array.isArray(totals.labors) ? totals.labors : [];
    const blocks = Array.from(blocksContainer.querySelectorAll(".wo-labor"));

    blocks.forEach((bEl, idx) => {
      const bt = blockTotals[idx] || {};
      const labor = toNum(bt.labor_total);
      const parts = toNum(bt.parts_total);
      const core = toNum(bt.core_total);
      const misc = toNum(bt.misc_total);
      if (labor === null && parts === null && core === null && misc === null) return;
      setBlockTotalsUI(
        bEl,
        Number.isFinite(labor) ? round2(labor) : null,
        Number.isFinite(parts) ? round2(parts) : null,
        Number.isFinite(core) ? round2(core) : 0,
        Number.isFinite(misc) ? round2(misc) : 0,
        [],
      );
    });

    const laborGrand = toNum(totals.labor_total);
    const partsGrand = toNum(totals.parts_total);
    const coreGrand = toNum(totals.core_total);
    const miscGrand = toNum(totals.misc_total);
    const grand = toNum(totals.grand_total);

    const laborGrandEl = $("laborGrandTotalDisplay");
    if (laborGrandEl && Number.isFinite(laborGrand)) laborGrandEl.textContent = `$${money(round2(laborGrand))}`;

    const partsGrandEl = $("partsGrandTotalDisplay");
    if (partsGrandEl && Number.isFinite(partsGrand)) partsGrandEl.textContent = `$${money(round2(partsGrand))}`;

    const coreGrandWrap = $("coreGrandTotalWrap");
    const coreGrandEl = $("coreGrandTotalDisplay");
    const hasCoreGrand = Number.isFinite(coreGrand) && coreGrand > 0;
    if (coreGrandWrap) coreGrandWrap.style.display = hasCoreGrand ? "" : "none";
    if (coreGrandEl) coreGrandEl.textContent = hasCoreGrand ? `$${money(round2(coreGrand))}` : "—";

    const miscGrandWrap = $("miscGrandTotalWrap");
    const miscGrandEl = $("miscGrandTotalDisplay");
    const hasMiscGrand = Number.isFinite(miscGrand) && miscGrand > 0;
    if (miscGrandWrap) miscGrandWrap.style.display = hasMiscGrand ? "" : "none";
    if (miscGrandEl) miscGrandEl.textContent = hasMiscGrand ? `$${money(round2(miscGrand))}` : "—";

    const grandEl = $("grandTotalDisplay");
    if (grandEl && Number.isFinite(grand)) grandEl.textContent = `$${money(round2(grand))}`;
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

  async function fetchVinDetails(vin) {
    const url = `/work_orders/api/vin?vin=${encodeURIComponent(vin)}`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.ok ? data : null;
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
      const coreCost = (it.core_has_charge && Number.isFinite(toNum(it.core_cost))) ? toNum(it.core_cost) : 0;
      const miscCost = (it.misc_has_charge && Array.isArray(it.misc_charges))
        ? round2(it.misc_charges.reduce((sum, ch) => sum + (toNum(ch?.price) || 0), 0))
        : 0;
      const chargesText = (coreCost > 0 || miscCost > 0)
        ? ` • Charges: core $${money(coreCost)}${miscCost > 0 ? `, misc $${money(miscCost)}` : ""}`
        : "";
      const meta = `Stock: ${it.in_stock ?? 0} • Avg cost: $${money(toNum(it.average_cost) ?? 0)}${chargesText}`;
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
    const coreInput = tr.querySelector(".part-core-charge");
    const miscInput = tr.querySelector(".part-misc-charge");
    const miscDescriptionInput = tr.querySelector(".part-misc-charge-description");

    if (pn) pn.value = part.part_number || "";
    if (ds) {
      const d = (part.description || "").trim();
      const ref = (part.reference || "").trim();
      ds.value = ref && ref !== d ? `${d} (${ref})` : d;
    }
    if (cost) cost.value = (part.average_cost != null) ? String(part.average_cost) : "";

    const coreCharge = (part?.core_has_charge && Number.isFinite(toNum(part?.core_cost)))
      ? Math.max(0, round2(toNum(part.core_cost)))
      : 0;
    const miscCharge = (part?.misc_has_charge && Array.isArray(part?.misc_charges))
      ? Math.max(0, round2(part.misc_charges.reduce((sum, ch) => sum + (toNum(ch?.price) || 0), 0)))
      : 0;
    const miscItems = (Array.isArray(part?.misc_charges) ? part.misc_charges : [])
      .map((ch) => ({
        description: String(ch?.description || "").trim(),
        price: Number.isFinite(toNum(ch?.price)) ? round2(toNum(ch?.price)) : null,
      }))
      .filter((x) => x.description);

    if (coreInput) coreInput.value = String(coreCharge);
    if (miscInput) miscInput.value = String(miscCharge);
    if (miscDescriptionInput) miscDescriptionInput.value = JSON.stringify(miscItems);
    setRowChargesMeta(tr);

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
      tr.querySelector(".part-core-charge").name = `labors[${idx}][parts][${rIdx}][core_charge]`;
      tr.querySelector(".part-misc-charge").name = `labors[${idx}][parts][${rIdx}][misc_charge]`;
      tr.querySelector(".part-misc-charge-description").name = `labors[${idx}][parts][${rIdx}][misc_charge_description]`;
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
    clone.querySelectorAll(".part-core-charge, .part-misc-charge").forEach(i => {
      i.value = "0";
    });
    clone.querySelectorAll(".part-misc-charge-description").forEach(i => {
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

      if (t.classList?.contains("part-number") || t.classList?.contains("part-description")) {
        const tr = t.closest("tr.parts-row");
        if (tr) {
          const coreInput = tr.querySelector(".part-core-charge");
          const miscInput = tr.querySelector(".part-misc-charge");
          const miscDescriptionInput = tr.querySelector(".part-misc-charge-description");
          if (coreInput) coreInput.value = "0";
          if (miscInput) miscInput.value = "0";
          if (miscDescriptionInput) miscDescriptionInput.value = "";
          setRowChargesMeta(tr);
          delete tr.dataset.priceAutofilled;
        }
      }

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
        tr.querySelector(".part-core-charge").value = String(p?.core_charge ?? p?.core_cost ?? 0);
        tr.querySelector(".part-misc-charge").value = String(p?.misc_charge ?? 0);
        tr.querySelector(".part-misc-charge-description").value = String(p?.misc_charge_description ?? "");
        setRowChargesMeta(tr);
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
        const coreCharge = String(tr.querySelector(".part-core-charge")?.value || "").trim();
        const miscCharge = String(tr.querySelector(".part-misc-charge")?.value || "").trim();
        const miscChargeDescription = String(tr.querySelector(".part-misc-charge-description")?.value || "").trim();
        if (!(part_number || description || qty || cost || price || coreCharge || miscCharge || miscChargeDescription)) return;
        parts.push({
          part_number,
          description,
          qty: qty === "" ? 0 : Number(qty),
          cost: cost === "" ? 0 : Number(cost),
          price: price === "" ? 0 : Number(price),
          core_charge: coreCharge === "" ? 0 : Number(coreCharge),
          misc_charge: miscCharge === "" ? 0 : Number(miscCharge),
          misc_charge_description: miscChargeDescription,
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
    const totalsSnapshot = readJsonScript("workOrderTotalsData", {});

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

    const unitVinInput = $("unitVinInput");
    const unitMakeInput = $("unitMakeInput");
    const unitModelInput = $("unitModelInput");
    const unitYearInput = $("unitYearInput");
    const unitTypeInput = $("unitTypeInput");

    const els = {
      editor, customerSel, unitSel, addUnitBtn, addLaborBtn,
      createBtn, editBtn, saveBtn, paidBtn, unpaidBtn
    };

    let lastVinLookup = "";
    const debouncedVinLookup = debounce(async function () {
      if (!unitVinInput) return;
      const vin = String(unitVinInput.value || "").trim().toUpperCase();
      if (vin.length !== 17) return;
      if (vin === lastVinLookup) return;
      lastVinLookup = vin;

      const data = await fetchVinDetails(vin);
      if (!data) return;

      if (unitMakeInput && data.make) unitMakeInput.value = data.make;
      if (unitModelInput && data.model) unitModelInput.value = data.model;
      if (unitYearInput && data.year) unitYearInput.value = data.year;
      if (unitTypeInput && data.type) unitTypeInput.value = data.type;
    }, 500);

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

    unitVinInput?.addEventListener("input", debouncedVinLookup);
    unitVinInput?.addEventListener("blur", debouncedVinLookup);

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

    if (isCreated) {
      applyTotalsSnapshotToUi(blocksContainer, totalsSnapshot);
    }

    applyStateFromStatus();
  });
})();
