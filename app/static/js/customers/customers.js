(function() {
  const customerModalEl = document.getElementById('createCustomerModal');
  const customerForm = document.getElementById('customerForm');
  const editingCustomerId = document.getElementById('editingCustomerId');
  const customerModalTitle = document.getElementById('createCustomerModalLabel');
  const customerSubmitBtn = document.getElementById('customerSubmitBtn');
  const customerDeactivateBtn = document.getElementById('customerDeactivateBtn');

  const companyNameInput = document.getElementById('customerCompanyName');
  const firstNameInput = document.getElementById('customerFirstName');
  const lastNameInput = document.getElementById('customerLastName');
  const phoneInput = document.getElementById('customerPhone');
  const emailInput = document.getElementById('customerEmail');
  const addressInput = document.getElementById('customerAddress');

  const woModalEl = document.getElementById('customerWorkOrdersModal');
  const workOrderDetailsBaseUrl = woModalEl?.getAttribute('data-work-order-details-url') || '/work_orders/details';
  const woModalTitle = document.getElementById('customerWorkOrdersModalLabel');
  const woSummary = document.getElementById('customerWorkOrdersSummary');
  const woCurrentBalance = document.getElementById('customerCurrentBalance');
  const woBody = document.getElementById('customerWorkOrdersTableBody');
  const woPrevBtn = document.getElementById('customerWorkOrdersPrevBtn');
  const woNextBtn = document.getElementById('customerWorkOrdersNextBtn');

  const woState = {
    customerId: '',
    customerName: '',
    page: 1,
    perPage: 10,
    pagination: null,
  };

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, function(ch) {
      if (ch === '&') return '&amp;';
      if (ch === '<') return '&lt;';
      if (ch === '>') return '&gt;';
      if (ch === '"') return '&quot;';
      return '&#39;';
    });
  }

  function money(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return '$0.00';
    return '$' + n.toFixed(2);
  }

  function setWoLoading(message) {
    if (!woBody) return;
    woBody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">'
      + escapeHtml(message)
      + '</td></tr>';
  }

  function renderWoStatus(status) {
    const normalized = String(status || 'open').toLowerCase();
    if (normalized === 'paid') {
      return '<span class="badge bg-success">paid</span>';
    }
    return '<span class="badge bg-warning text-dark">' + escapeHtml(normalized) + '</span>';
  }

  function updateWoPager() {
    const pg = woState.pagination;
    if (woPrevBtn) woPrevBtn.disabled = !(pg && pg.has_prev);
    if (woNextBtn) woNextBtn.disabled = !(pg && pg.has_next);
  }

  async function loadCustomerWorkOrders(page) {
    if (!woState.customerId) return;

    const targetPage = Number(page) > 0 ? Number(page) : 1;
    woState.page = targetPage;
    woState.pagination = null;
    updateWoPager();
    setWoLoading('Loading work orders...');

    try {
      const url = '/customers/api/' + encodeURIComponent(woState.customerId)
        + '/work-orders?page=' + encodeURIComponent(String(targetPage))
        + '&per_page=' + encodeURIComponent(String(woState.perPage));

      const res = await fetch(url, {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        setWoLoading(data?.error || 'Failed to load work orders.');
        if (woSummary) woSummary.textContent = 'Unable to load data.';
        return;
      }

      const customerName = data?.customer?.name || woState.customerName || 'Customer';
      woState.customerName = customerName;
      woState.pagination = data.pagination || null;

      if (woModalTitle) woModalTitle.textContent = 'Work Orders - ' + customerName;
      if (woCurrentBalance) woCurrentBalance.textContent = money(data?.customer?.current_balance || 0);

      const pg = woState.pagination || {};
      if (woSummary) {
        woSummary.textContent = 'Page ' + String(pg.page || 1)
          + ' of ' + String(pg.pages || 1)
          + ' · ' + String(pg.total || 0) + ' total';
      }

      const items = Array.isArray(data.items) ? data.items : [];
      if (!woBody) return;

      if (items.length === 0) {
        woBody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No work orders for this customer.</td></tr>';
      } else {
        woBody.innerHTML = items.map(function(item) {
          const detailsUrl = workOrderDetailsBaseUrl + '?work_order_id=' + encodeURIComponent(String(item.id || ''));
          return '<tr>'
            + '<td><a href="' + escapeHtml(detailsUrl) + '" target="_blank" rel="noopener noreferrer" class="text-decoration-none">'
            + escapeHtml(String(item.wo_number || '-'))
            + '</a></td>'
            + '<td>' + renderWoStatus(item.status) + '</td>'
            + '<td class="text-end">' + escapeHtml(money(item.grand_total)) + '</td>'
            + '<td class="text-end">' + escapeHtml(money(item.paid_amount)) + '</td>'
            + '<td class="text-end">' + escapeHtml(money(item.remaining_balance)) + '</td>'
            + '<td>' + escapeHtml(item.created_at || '-') + '</td>'
            + '</tr>';
        }).join('');
      }

      updateWoPager();
    } catch (err) {
      setWoLoading('Network error while loading work orders.');
      if (woSummary) woSummary.textContent = 'Unable to load data.';
    }
  }

  function openCustomerWorkOrders(customerId, customerName) {
    if (!customerId) return;

    woState.customerId = customerId;
    woState.customerName = customerName || 'Customer';
    woState.page = 1;
    woState.pagination = null;

    if (woModalTitle) woModalTitle.textContent = 'Work Orders - ' + woState.customerName;
    if (woCurrentBalance) woCurrentBalance.textContent = '$0.00';
    if (woSummary) woSummary.textContent = 'Loading...';
    setWoLoading('Loading work orders...');

    if (woModalEl && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(woModalEl).show();
    }

    loadCustomerWorkOrders(1);
  }

  customerModalEl?.addEventListener('show.bs.modal', async function(e) {
    const trigger = e.relatedTarget;

    if (!trigger || !trigger.classList.contains('editCustomerBtn')) {
      editingCustomerId.value = '';
      customerModalTitle.textContent = 'Add Customer';
      customerSubmitBtn.textContent = 'Create';
      customerDeactivateBtn.style.display = 'none';
      customerForm.reset();
      return;
    }

    const customerId = trigger.getAttribute('data-customer-id');
    if (!customerId) return;

    try {
      const res = await fetch('/customers/api/' + encodeURIComponent(customerId), {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        alert(data?.error || 'Failed to load customer data');
        return;
      }

      const customer = data.item || {};
      editingCustomerId.value = customer._id || '';
      customerModalTitle.textContent = 'Edit Customer';
      customerSubmitBtn.textContent = 'Update';

      companyNameInput.value = customer.company_name || '';
      firstNameInput.value = customer.first_name || '';
      lastNameInput.value = customer.last_name || '';
      phoneInput.value = customer.phone || '';
      emailInput.value = customer.email || '';
      addressInput.value = customer.address || '';

      customerDeactivateBtn.style.display = customer.is_active === false ? 'none' : 'inline-block';
    } catch (err) {
      alert('Network error while loading customer data');
    }
  });

  customerDeactivateBtn?.addEventListener('click', async function() {
    const customerId = editingCustomerId.value;
    if (!customerId) return;

    if (!window.confirm('Deactivate this customer?')) {
      return;
    }

    try {
      customerDeactivateBtn.disabled = true;
      const res = await fetch('/customers/api/' + encodeURIComponent(customerId) + '/deactivate', {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        alert(data?.error || 'Failed to deactivate customer');
        customerDeactivateBtn.disabled = false;
        return;
      }

      window.location.reload();
    } catch (err) {
      alert('Network error while deactivating customer');
      customerDeactivateBtn.disabled = false;
    }
  });

  customerForm?.addEventListener('submit', async function(e) {
    const customerId = editingCustomerId.value;
    if (!customerId) {
      return;
    }

    e.preventDefault();

    const payload = {
      company_name: companyNameInput.value.trim(),
      first_name: firstNameInput.value.trim(),
      last_name: lastNameInput.value.trim(),
      phone: phoneInput.value.trim(),
      email: emailInput.value.trim(),
      address: addressInput.value.trim(),
    };

    try {
      customerSubmitBtn.disabled = true;
      customerSubmitBtn.textContent = 'Saving...';

      const res = await fetch('/customers/api/' + encodeURIComponent(customerId) + '/update', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        alert(data?.error || 'Failed to update customer');
        customerSubmitBtn.disabled = false;
        customerSubmitBtn.textContent = 'Update';
        return;
      }

      window.location.reload();
    } catch (err) {
      alert('Network error while updating customer');
      customerSubmitBtn.disabled = false;
      customerSubmitBtn.textContent = 'Update';
    }
  });

  document.addEventListener('click', function(e) {
    const row = e.target.closest('.customerWorkOrdersRow');
    if (!row) return;

    if (e.target.closest('a, button, form, input, select, textarea, label')) {
      return;
    }

    const customerId = row.getAttribute('data-customer-id') || '';
    const customerName = row.getAttribute('data-customer-name') || 'Customer';
    openCustomerWorkOrders(customerId, customerName);
  });

  document.addEventListener('keydown', function(e) {
    const row = e.target.closest('.customerWorkOrdersRow');
    if (!row) return;

    if (e.target.closest('a, button, form, input, select, textarea, label')) {
      return;
    }

    if (e.key !== 'Enter' && e.key !== ' ') {
      return;
    }

    e.preventDefault();
    const customerId = row.getAttribute('data-customer-id') || '';
    const customerName = row.getAttribute('data-customer-name') || 'Customer';
    openCustomerWorkOrders(customerId, customerName);
  });

  woPrevBtn?.addEventListener('click', function() {
    const pg = woState.pagination;
    if (!pg || !pg.has_prev) return;
    loadCustomerWorkOrders(pg.prev_page);
  });

  woNextBtn?.addEventListener('click', function() {
    const pg = woState.pagination;
    if (!pg || !pg.has_next) return;
    loadCustomerWorkOrders(pg.next_page);
  });
})();
