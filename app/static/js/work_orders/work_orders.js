(function () {
  "use strict";

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body || {}),
    });

    let data = null;
    try { data = await res.json(); } catch { data = null; }

    if (!res.ok || !data || data.ok !== true) {
      const msg = (data && (data.error || data.message)) ? (data.error || data.message) : "Failed to update.";
      throw new Error(msg);
    }

    return data;
  }

  async function getJson(url) {
    const res = await fetch(url, {
      method: "GET",
      headers: { "Accept": "application/json" },
    });

    let data = null;
    try { data = await res.json(); } catch { data = null; }

    if (!res.ok || !data || data.ok !== true) {
      const msg = (data && (data.error || data.message)) ? (data.error || data.message) : "Failed to fetch.";
      throw new Error(msg);
    }

    return data;
  }

  let currentWorkOrderId = null;
  let paymentsLoaded = false;

  // ========== MARK PAID BUTTON LOGIC ==========
  document.addEventListener("click", async function (e) {
    const btn = e.target.closest(".js-mark-paid");
    if (!btn) return;

    const workOrderId = String(btn.dataset.workOrderId || "").trim();
    if (!workOrderId) return;

    currentWorkOrderId = workOrderId;

    // Fetch payment info
    try {
      const data = await getJson(`/work_orders/api/work_orders/${encodeURIComponent(workOrderId)}/payments`);
      
      // Update modal with balance info
      document.getElementById("paymentListInvoiceTotal").textContent = `$${(data.grand_total || 0).toFixed(2)}`;
      document.getElementById("paymentListAlreadyPaid").textContent = `$${(data.paid_amount || 0).toFixed(2)}`;
      document.getElementById("paymentListRemainingBalance").textContent = `$${(data.remaining_balance || 0).toFixed(2)}`;
      
      // Pre-fill amount with remaining balance
      const remainingBalance = data.remaining_balance || 0;
      document.getElementById("paymentListAmountInput").value = remainingBalance > 0 ? remainingBalance.toFixed(2) : "";
      document.getElementById("paymentListMethodInput").value = "cash";
      document.getElementById("paymentListNotesInput").value = "";

      // Show modal
      const modal = new bootstrap.Modal(document.getElementById("paymentModalList"));
      modal.show();
    } catch (err) {
      alert(err.message || "Failed to load payment info.");
    }
  });

  document.getElementById("paymentListSubmitBtn")?.addEventListener("click", async function () {
    if (!currentWorkOrderId) return;

    const amount = parseFloat(document.getElementById("paymentListAmountInput").value || "0");
    const paymentMethod = document.getElementById("paymentListMethodInput").value;
    const notes = document.getElementById("paymentListNotesInput").value;

    if (amount <= 0) {
      alert("Please enter a valid payment amount.");
      return;
    }

    const btn = this;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
      const data = await postJson(`/work_orders/api/work_orders/${encodeURIComponent(currentWorkOrderId)}/payment`, {
        amount,
        payment_method: paymentMethod,
        notes
      });

      // Close modal
      const modal = bootstrap.Modal.getInstance(document.getElementById("paymentModalList"));
      modal.hide();

      // Update UI
      if (data.is_fully_paid) {
        const row = document.querySelector(`button[data-work-order-id="${currentWorkOrderId}"]`)?.closest("tr");
        if (row) {
          const td = row.querySelector("td:nth-child(7)");
          if (td) {
            td.innerHTML = '<span class="badge bg-success">Paid</span>';
          }
        }
      }

      alert("Payment recorded successfully!");
      currentWorkOrderId = null;
      
      // Refresh payments tab if it's loaded
      if (paymentsLoaded) {
        loadPaymentsData();
      }
    } catch (err) {
      alert(err.message || "Failed to record payment.");
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });

  // ========== PAYMENTS TAB LOGIC ==========
  
  async function loadPaymentsData() {
    const loadingEl = document.getElementById("payments-loading");
    const contentEl = document.getElementById("payments-content");
    const emptyEl = document.getElementById("payments-empty");

    loadingEl.classList.remove("d-none");
    contentEl.classList.add("d-none");
    emptyEl.classList.add("d-none");

    try {
      const response = await fetch("/work_orders/api/work_orders/all-payments", {
        method: "GET",
        headers: { "Accept": "application/json" },
      });

      let allPaymentsData = [];

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      if (!data.ok) {
        throw new Error(data.error || "API returned error");
      }

      allPaymentsData = data.payments || [];
      loadingEl.classList.add("d-none");

      if (allPaymentsData.length === 0) {
        emptyEl.classList.remove("d-none");
        return;
      }

      // Build payments table
      let html = `
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th>Work Order ID</th>
                <th>Amount</th>
                <th>Method</th>
                <th>Date</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
      `;

      allPaymentsData.forEach(payment => {
        try {
          const dt = new Date(payment.created_at);
          const createdAt = dt.toLocaleString("en-US", {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
          });

          const woId = String(payment.work_order_id || "").substring(0, 8) || "—";
          const amount = parseFloat(payment.amount) || 0;
          const method = String(payment.payment_method || "cash").toLowerCase();
          const notes = String(payment.notes || "").trim();

          html += `
            <tr>
              <td><code>${woId}</code></td>
              <td class="fw-semibold">$${amount.toFixed(2)}</td>
              <td><span class="badge bg-secondary">${method}</span></td>
              <td><small>${createdAt}</small></td>
              <td>${notes ? `<small>${notes}</small>` : "<small class='text-muted'>—</small>"}</td>
            </tr>
          `;
        } catch (itemErr) {
          console.warn("Error formatting payment:", payment, itemErr);
        }
      });

      html += `
            </tbody>
          </table>
        </div>
      `;

      contentEl.innerHTML = html;
      contentEl.classList.remove("d-none");
      paymentsLoaded = true;
    } catch (err) {
      console.error("Error loading payments:", err);
      loadingEl.classList.add("d-none");
      emptyEl.classList.remove("d-none");
      emptyEl.innerHTML = `<div class="alert alert-danger mb-0">Error loading payments: ${err.message}</div>`;
    }
  }

  // Listen for Payments tab activation
  const paymentsTab = document.getElementById("tab-payments");
  if (paymentsTab) {
    paymentsTab.addEventListener("shown.bs.tab", function () {
      if (!paymentsLoaded) {
        loadPaymentsData();
      }
    });
  }

})();
