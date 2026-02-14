(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function readJsonScript(id, fallback) {
    const el = $(id);
    if (!el) return fallback;
    try {
      return JSON.parse(el.textContent || "null") ?? fallback;
    } catch (e) {
      return fallback;
    }
  }

  function toNum(v) {
    if (v === null || v === undefined) return null;
    const s = String(v).trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  function money(n) {
    if (!Number.isFinite(n)) return "";
    return n.toFixed(2);
  }

  function round2(n) {
    return Math.round(n * 100) / 100;
  }

  function calcPriceFromRule(cost, mode, valuePercent) {
    if (!Number.isFinite(cost) || cost <= 0) return null;
    if (!Number.isFinite(valuePercent)) return null;

    const vp = valuePercent / 100;

    if (mode === "markup") {
      // price = cost * (1 + markup%)
      return round2(cost * (1 + vp));
    }

    // margin:
    // margin = (price - cost)/price  => price = cost/(1 - margin)
    const denom = 1 - vp;
    if (denom <= 0) return round2(cost);
    return round2(cost / denom);
  }

  function matchRule(cost, rules) {
    if (!Number.isFinite(cost) || !Array.isArray(rules)) return null;

    for (const r of rules) {
      const from = toNum(r.from);
      const to = r.to === null ? null : toNum(r.to);
      const value_percent = toNum(r.value_percent);

      if (from === null || value_percent === null) continue;
      if (cost < from) continue;

      if (to === null) return { value_percent };
      if (cost <= to) return { value_percent };
    }
    return null;
  }

  function getHourlyRate(rates, code) {
    if (!Array.isArray(rates) || !code) return null;
    const found = rates.find(x => String(x.code) === String(code));
    if (!found) return null;
    const hr = toNum(found.hourly_rate);
    return hr;
  }

  function updateTotalsUI(laborTotal, partsTotal) {
    const laborEl = $("laborTotalDisplay");
    const partsEl = $("partsTotalDisplay");
    const grandEl = $("grandTotalDisplay");

    if (laborEl) laborEl.textContent = Number.isFinite(laborTotal) ? `$${money(laborTotal)}` : "—";
    if (partsEl) partsEl.textContent = Number.isFinite(partsTotal) ? `$${money(partsTotal)}` : "—";

    const grand = (Number.isFinite(laborTotal) ? laborTotal : 0) + (Number.isFinite(partsTotal) ? partsTotal : 0);
    if (grandEl) grandEl.textContent = (Number.isFinite(laborTotal) || Number.isFinite(partsTotal)) ? `$${money(round2(grand))}` : "—";
  }

  function recalcLabor(rates) {
    const hoursInput = $("labor_hours");
    const rateSelect = $("labor_rate_code");

    if (!hoursInput || !rateSelect) return null;

    const hours = toNum(hoursInput.value);
    const code = String(rateSelect.value || "").trim();

    if (hours === null || !code) return null;

    const hr = getHourlyRate(rates, code);
    if (hr === null) return null;

    return round2(hours * hr);
  }

  // ---------- Parts rows ----------

  function makePartsRow(index) {
    const tr = document.createElement("tr");
    tr.className = "parts-row";
    tr.dataset.index = String(index);

    tr.innerHTML = `
      <td>
        <input class="form-control form-control-sm part-number" name="part_number_${index}" maxlength="64">
      </td>
      <td>
        <input class="form-control form-control-sm part-description" name="part_description_${index}" maxlength="200">
      </td>
      <td>
        <input class="form-control form-control-sm part-qty" name="part_qty_${index}" inputmode="numeric">
      </td>
      <td>
        <input class="form-control form-control-sm part-cost" name="part_cost_${index}" inputmode="decimal">
      </td>
      <td>
        <input class="form-control form-control-sm part-price" value="" readonly tabindex="-1">
      </td>
      <td class="part-line-total">
        <span class="text-muted">—</span>
      </td>
    `;
    return tr;
  }

  function rowHasAnyInput(tr) {
    const pn = tr.querySelector(".part-number")?.value || "";
    const ds = tr.querySelector(".part-description")?.value || "";
    const q = tr.querySelector(".part-qty")?.value || "";
    const c = tr.querySelector(".part-cost")?.value || "";
    return String(pn).trim() || String(ds).trim() || String(q).trim() || String(c).trim();
  }

  function recalcRow(tr, pricing) {
    const qty = toNum(tr.querySelector(".part-qty")?.value);
    const cost = toNum(tr.querySelector(".part-cost")?.value);

    const priceInput = tr.querySelector(".part-price");
    const lineCell = tr.querySelector(".part-line-total");

    if (!pricing || !Array.isArray(pricing.rules)) {
      if (priceInput) priceInput.value = "";
      if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
      return { lineTotal: null };
    }

    if (qty === null || qty <= 0 || cost === null || cost < 0) {
      if (priceInput) priceInput.value = "";
      if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
      return { lineTotal: null };
    }

    const rule = matchRule(cost, pricing.rules);
    if (!rule) {
      if (priceInput) priceInput.value = "";
      if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
      return { lineTotal: null };
    }

    const price = calcPriceFromRule(cost, pricing.mode, rule.value_percent);
    if (price === null) {
      if (priceInput) priceInput.value = "";
      if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
      return { lineTotal: null };
    }

    const lineTotal = round2(price * qty);

    if (priceInput) priceInput.value = money(price);
    if (lineCell) lineCell.innerHTML = `<strong>$${money(lineTotal)}</strong>`;

    return { lineTotal };
  }

  function recalcAllParts(tbody, pricing) {
    let total = 0;
    const rows = tbody.querySelectorAll("tr.parts-row");
    rows.forEach(tr => {
      const any = rowHasAnyInput(tr);
      if (!any) {
        // keep row empty display
        const priceInput = tr.querySelector(".part-price");
        const lineCell = tr.querySelector(".part-line-total");
        if (priceInput) priceInput.value = "";
        if (lineCell) lineCell.innerHTML = `<span class="text-muted">—</span>`;
        return;
      }

      const r = recalcRow(tr, pricing);
      if (r.lineTotal !== null && Number.isFinite(r.lineTotal)) total += r.lineTotal;
    });
    total = round2(total);
    return total > 0 ? total : null;
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

  function attachPartsHandlers(tbody, pricing, laborRates) {
    const handler = function () {
      ensureTrailingEmptyRow(tbody);

      const laborTotal = recalcLabor(laborRates);
      const partsTotal = recalcAllParts(tbody, pricing);

      updateTotalsUI(
        laborTotal !== null ? laborTotal : null,
        partsTotal !== null ? partsTotal : null
      );
    };

    tbody.addEventListener("input", (e) => {
      if (e.target && e.target.closest("tr.parts-row")) handler();
    });

    // initial
    handler();
  }

  function attachLaborHandlers(pricing, laborRates, tbody) {
    const hoursInput = $("labor_hours");
    const rateSelect = $("labor_rate_code");

    const handler = function () {
      const laborTotal = recalcLabor(laborRates);
      const partsTotal = tbody ? recalcAllParts(tbody, pricing) : null;
      updateTotalsUI(
        laborTotal !== null ? laborTotal : null,
        partsTotal !== null ? partsTotal : null
      );
    };

    if (hoursInput) hoursInput.addEventListener("input", handler);
    if (rateSelect) rateSelect.addEventListener("change", handler);

    // initial
    handler();
  }

  document.addEventListener("DOMContentLoaded", function () {
    const laborRates = readJsonScript("laborRatesData", []);
    const pricing = readJsonScript("partsPricingRulesData", null);

    const tbody = $("partsTbody");
    if (!tbody) return;

    // create initial single row if server didn't render rows
    if (tbody.querySelectorAll("tr.parts-row").length === 0) {
      tbody.appendChild(makePartsRow(0));
    }

    ensureTrailingEmptyRow(tbody);

    attachPartsHandlers(tbody, pricing, laborRates);
    attachLaborHandlers(pricing, laborRates, tbody);
  });
})();
