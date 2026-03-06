(function() {
  const modal = document.getElementById('createVendorModal');
  const form = document.getElementById('vendorForm');
  const editingVendorId = document.getElementById('editingVendorId');
  const modalTitle = document.getElementById('createVendorModalLabel');
  const submitBtn = document.getElementById('vendorSubmitBtn');
  const activeGroup = document.getElementById('vendorActiveGroup');
  
  // Form fields
  const nameInput = document.getElementById('vendorName');
  const phoneInput = document.getElementById('vendorPhone');
  const emailInput = document.getElementById('vendorEmail');
  const websiteInput = document.getElementById('vendorWebsite');
  const pcFirstInput = document.getElementById('vendorPCFirst');
  const pcLastInput = document.getElementById('vendorPCLast');
  const addressInput = document.getElementById('vendorAddress');
  const notesInput = document.getElementById('vendorNotes');
  const isActiveInput = document.getElementById('vendorIsActive');

  const ordersModalEl = document.getElementById('vendorOrdersModal');
  const ordersTitle = document.getElementById('vendorOrdersModalLabel');
  const ordersSummary = document.getElementById('vendorOrdersSummary');
  const ordersBody = document.getElementById('vendorOrdersTableBody');
  const ordersPrevBtn = document.getElementById('vendorOrdersPrevBtn');
  const ordersNextBtn = document.getElementById('vendorOrdersNextBtn');

  const ordersState = {
    vendorId: '',
    vendorName: '',
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

  function renderStatusBadge(status) {
    const normalized = String(status || 'ordered').toLowerCase();
    if (normalized === 'received') {
      return '<span class="badge bg-success">received</span>';
    }
    return '<span class="badge bg-warning text-dark">' + escapeHtml(normalized) + '</span>';
  }

  function setOrdersLoading(message) {
    if (ordersBody) {
      ordersBody.innerHTML =
        '<tr><td colspan="4" class="text-center text-muted py-4">' + escapeHtml(message) + '</td></tr>';
    }
  }

  function updateOrdersPaginationControls() {
    const pg = ordersState.pagination;
    const hasPrev = !!(pg && pg.has_prev);
    const hasNext = !!(pg && pg.has_next);

    if (ordersPrevBtn) ordersPrevBtn.disabled = !hasPrev;
    if (ordersNextBtn) ordersNextBtn.disabled = !hasNext;
  }

  async function loadVendorOrders(page) {
    if (!ordersState.vendorId) return;

    const targetPage = Number(page) > 0 ? Number(page) : 1;
    ordersState.page = targetPage;
    ordersState.pagination = null;
    updateOrdersPaginationControls();
    setOrdersLoading('Loading part orders...');

    try {
      const url = '/vendors/api/' + encodeURIComponent(ordersState.vendorId)
        + '/part-orders?page=' + encodeURIComponent(String(targetPage))
        + '&per_page=' + encodeURIComponent(String(ordersState.perPage));

      const res = await fetch(url, {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        setOrdersLoading(data?.error || 'Failed to load part orders.');
        if (ordersSummary) ordersSummary.textContent = 'Unable to load data.';
        return;
      }

      const vendorName = data?.vendor?.name || ordersState.vendorName || 'Vendor';
      ordersState.vendorName = vendorName;
      ordersState.pagination = data.pagination || null;

      if (ordersTitle) {
        ordersTitle.textContent = 'Part Orders - ' + vendorName;
      }

      const pg = ordersState.pagination || {};
      if (ordersSummary) {
        ordersSummary.textContent = 'Page ' + String(pg.page || 1)
          + ' of ' + String(pg.pages || 1)
          + ' · ' + String(pg.total || 0) + ' total';
      }

      const items = Array.isArray(data.items) ? data.items : [];
      if (!ordersBody) return;

      if (items.length === 0) {
        ordersBody.innerHTML =
          '<tr><td colspan="4" class="text-center text-muted py-4">No part orders for this vendor.</td></tr>';
      } else {
        ordersBody.innerHTML = items.map(function(item) {
          return '<tr>'
            + '<td><span class="badge bg-secondary">' + escapeHtml(item.order_number || '-') + '</span></td>'
            + '<td class="text-end">' + escapeHtml(String(item.items_count ?? 0)) + '</td>'
            + '<td>' + renderStatusBadge(item.status) + '</td>'
            + '<td>' + escapeHtml(item.created_at || '-') + '</td>'
            + '</tr>';
        }).join('');
      }

      updateOrdersPaginationControls();
    } catch (err) {
      setOrdersLoading('Network error while loading part orders.');
      if (ordersSummary) ordersSummary.textContent = 'Unable to load data.';
    }
  }

  function openVendorOrders(vendorId, vendorName) {
    if (!vendorId) return;

    ordersState.vendorId = vendorId;
    ordersState.vendorName = vendorName || 'Vendor';
    ordersState.page = 1;
    ordersState.pagination = null;

    if (ordersTitle) {
      ordersTitle.textContent = 'Part Orders - ' + ordersState.vendorName;
    }
    if (ordersSummary) {
      ordersSummary.textContent = 'Loading...';
    }
    updateOrdersPaginationControls();
    setOrdersLoading('Loading part orders...');

    if (ordersModalEl && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(ordersModalEl).show();
      return;
    }

    // Fallback if global bootstrap object is unavailable.
    loadVendorOrders(1);
  }

  ordersModalEl?.addEventListener('show.bs.modal', function(e) {
    const trigger = e.relatedTarget;
    const vendorId = trigger?.getAttribute('data-vendor-id') || ordersState.vendorId;
    const vendorName = trigger?.getAttribute('data-vendor-name') || ordersState.vendorName || 'Vendor';
    if (!vendorId) return;

    ordersState.vendorId = vendorId;
    ordersState.vendorName = vendorName;
    loadVendorOrders(1);
  });

  // Reset form when modal opens for create
  modal?.addEventListener('show.bs.modal', function(e) {
    const triggerBtn = e.relatedTarget;
    
    // Check if this is an edit button
    if (triggerBtn && triggerBtn.classList.contains('editVendorBtn')) {
      return; // Let the edit handler deal with it
    }
    
    // Reset for create mode
    editingVendorId.value = '';
    modalTitle.textContent = 'Create new vendor';
    submitBtn.textContent = 'Create Vendor';
    activeGroup.style.display = 'none';
    form.reset();
  });

  // Handle edit button clicks
  document.addEventListener('click', async function(e) {
    const btn = e.target.closest('.editVendorBtn');
    if (!btn) return;
    
    const vendorId = btn.getAttribute('data-vendor-id');
    if (!vendorId) return;

    try {
      const res = await fetch(`/vendors/api/${encodeURIComponent(vendorId)}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      
      const data = await res.json();
      
      if (!res.ok || !data.ok) {
        alert(data?.error || 'Failed to load vendor data');
        return;
      }
      
      const vendor = data.item;
      
      // Set form to edit mode
      editingVendorId.value = vendor._id;
      modalTitle.textContent = 'Edit vendor';
      submitBtn.textContent = 'Update Vendor';
      activeGroup.style.display = 'block';
      
      // Populate form fields
      nameInput.value = vendor.name || '';
      phoneInput.value = vendor.phone || '';
      emailInput.value = vendor.email || '';
      websiteInput.value = vendor.website || '';
      pcFirstInput.value = vendor.primary_contact_first_name || '';
      pcLastInput.value = vendor.primary_contact_last_name || '';
      addressInput.value = vendor.address || '';
      notesInput.value = vendor.notes || '';
      isActiveInput.checked = vendor.is_active !== false;
      
    } catch (err) {
      alert('Network error while loading vendor data');
    }
  });

  // Open orders modal by clicking vendor row, excluding interactive controls.
  document.addEventListener('click', function(e) {
    const row = e.target.closest('.vendorOrdersRow');
    if (!row) return;

    if (e.target.closest('a, button, form, input, select, textarea, label')) {
      return;
    }

    const opener = row.querySelector('.openVendorOrdersBtn');
    if (opener) {
      opener.click();
      return;
    }

    const vendorId = row.getAttribute('data-vendor-id') || '';
    const vendorName = row.getAttribute('data-vendor-name') || 'Vendor';
    openVendorOrders(vendorId, vendorName);
  });

  // Keyboard support for clickable row.
  document.addEventListener('keydown', function(e) {
    const row = e.target.closest('.vendorOrdersRow');
    if (!row) return;

    if (e.target.closest('a, button, form, input, select, textarea, label')) {
      return;
    }

    if (e.key !== 'Enter' && e.key !== ' ') {
      return;
    }

    e.preventDefault();
    const opener = row.querySelector('.openVendorOrdersBtn');
    if (opener) {
      opener.click();
      return;
    }

    const vendorId = row.getAttribute('data-vendor-id') || '';
    const vendorName = row.getAttribute('data-vendor-name') || 'Vendor';
    openVendorOrders(vendorId, vendorName);
  });

  ordersPrevBtn?.addEventListener('click', function() {
    const pg = ordersState.pagination;
    if (!pg || !pg.has_prev) return;
    loadVendorOrders(pg.prev_page);
  });

  ordersNextBtn?.addEventListener('click', function() {
    const pg = ordersState.pagination;
    if (!pg || !pg.has_next) return;
    loadVendorOrders(pg.next_page);
  });

  // Handle form submission
  form?.addEventListener('submit', async function(e) {
    const vendorId = editingVendorId.value;
    
    // If editing, use AJAX
    if (vendorId) {
      e.preventDefault();
      
      const formData = {
        name: nameInput.value.trim(),
        phone: phoneInput.value.trim(),
        email: emailInput.value.trim(),
        website: websiteInput.value.trim(),
        primary_contact_first_name: pcFirstInput.value.trim(),
        primary_contact_last_name: pcLastInput.value.trim(),
        address: addressInput.value.trim(),
        notes: notesInput.value.trim(),
        is_active: isActiveInput.checked
      };
      
      try {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving...';
        
        const res = await fetch(`/vendors/api/${encodeURIComponent(vendorId)}/update`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          },
          body: JSON.stringify(formData)
        });
        
        const data = await res.json();
        
        if (!res.ok || !data.ok) {
          alert(data?.error || 'Failed to update vendor');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Update Vendor';
          return;
        }
        
        // Success - reload page
        window.location.reload();
        
      } catch (err) {
        alert('Network error while updating vendor');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Update Vendor';
      }
    }
    // Otherwise let the form submit normally for create
  });
})();
