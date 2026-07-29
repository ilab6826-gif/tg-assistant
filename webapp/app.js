(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const API_BASE = "/api";
  const STORAGE_KEY = "tracked_orders";
  const MAX_TRACKED = 25;

  // ---------- Telegram WebApp bootstrap ----------

  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor("#0a0910"); } catch (e) {}
    try { tg.setBackgroundColor("#0a0910"); } catch (e) {}
  }

  function haptic(style) {
    if (tg && tg.HapticFeedback) {
      try { tg.HapticFeedback.impactOccurred(style || "light"); } catch (e) {}
    }
  }

  function notify(type) {
    if (tg && tg.HapticFeedback) {
      try { tg.HapticFeedback.notificationOccurred(type); } catch (e) {}
    }
  }

  // ---------- Storage (CloudStorage with localStorage fallback) ----------
  // telegram-web-app.js exposes window.Telegram.WebApp even outside a real
  // Telegram client (a version "6.0" stub), where CloudStorage methods throw
  // synchronously instead of just failing gracefully - so both a version
  // check and a try/catch are needed to safely fall back to localStorage.

  function cloudStorageAvailable() {
    if (!tg || !tg.CloudStorage) return false;
    if (tg.isVersionAtLeast && !tg.isVersionAtLeast("6.9")) return false;
    return true;
  }

  function readLocal() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); } catch (e) { return []; }
  }

  function writeLocal(value) {
    try { localStorage.setItem(STORAGE_KEY, value); } catch (e) {}
  }

  const storage = {
    get() {
      return new Promise((resolve) => {
        if (!cloudStorageAvailable()) return resolve(readLocal());
        try {
          tg.CloudStorage.getItem(STORAGE_KEY, (err, value) => {
            if (err || !value) return resolve(readLocal());
            try { resolve(JSON.parse(value)); } catch (e) { resolve([]); }
          });
        } catch (e) {
          resolve(readLocal());
        }
      });
    },
    set(list) {
      const value = JSON.stringify(list.slice(0, MAX_TRACKED));
      writeLocal(value);
      return new Promise((resolve) => {
        if (!cloudStorageAvailable()) return resolve();
        try {
          tg.CloudStorage.setItem(STORAGE_KEY, value, () => resolve());
        } catch (e) {
          resolve();
        }
      });
    },
  };

  // ---------- DOM refs ----------

  const searchForm = document.getElementById("search-form");
  const orderInput = document.getElementById("order-input");
  const searchBtn = document.getElementById("search-btn");
  const searchError = document.getElementById("search-error");

  const ordersSection = document.getElementById("orders-section");
  const ordersList = document.getElementById("orders-list");
  const ordersCount = document.getElementById("orders-count");
  const emptyState = document.getElementById("empty-state");

  const viewList = document.getElementById("view-list");
  const viewDetail = document.getElementById("view-detail");
  const backBtn = document.getElementById("back-btn");

  const detailNumber = document.getElementById("detail-number");
  const detailProduct = document.getElementById("detail-product");
  const detailStatusPill = document.getElementById("detail-status-pill");
  const stepperEl = document.getElementById("stepper");

  const toastEl = document.getElementById("toast");

  let trackedNumbers = [];
  let toastTimer = null;

  // ---------- Toast ----------

  function showToast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-visible"), 2200);
  }

  // ---------- API ----------

  async function fetchOrderStatus(orderNumber) {
    const res = await fetch(`${API_BASE}/status/${encodeURIComponent(orderNumber)}`);
    if (res.status === 404) return { notFound: true };
    if (!res.ok) throw new Error("network");
    return res.json();
  }

  // ---------- View switching ----------

  function showListView() {
    viewDetail.classList.remove("is-active");
    viewList.classList.add("is-active");
    if (tg && tg.BackButton) tg.BackButton.hide();
  }

  function showDetailView() {
    viewList.classList.remove("is-active");
    viewDetail.classList.add("is-active");
    if (tg && tg.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(showListView);
    }
  }

  backBtn.addEventListener("click", () => { haptic("light"); showListView(); });

  // ---------- Stepper rendering ----------

  const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function renderStepper(order) {
    const statuses = order.statuses || [];
    const current = order.status;

    stepperEl.innerHTML = "";
    statuses.forEach((label, idx) => {
      const stepNum = idx + 1;
      const li = document.createElement("li");
      li.className = "step";
      li.style.animationDelay = `${idx * 70}ms`;

      let state = "pending";
      if (stepNum < current) state = "done";
      else if (stepNum === current) state = "active";
      li.classList.add(`is-${state}`);

      li.innerHTML = `
        <div class="step-line"><div class="step-line-fill"></div></div>
        <div class="step-node"><span>${stepNum}</span>${CHECK_SVG}</div>
        <div class="step-body">
          <div class="step-title">${label}</div>
          <div class="step-hint">Сейчас здесь</div>
        </div>
      `;
      stepperEl.appendChild(li);
    });
  }

  function renderDetail(order) {
    detailNumber.textContent = order.order_number;
    detailProduct.textContent = order.product || "Товар не указан";
    detailStatusPill.textContent = order.status_label || "";
    detailStatusPill.classList.toggle("is-done", order.status >= (order.statuses || []).length);
    renderStepper(order);
  }

  async function openOrder(orderNumber, { fromSearch = false } = {}) {
    try {
      const order = await fetchOrderStatus(orderNumber);
      if (order.notFound) {
        if (fromSearch) showSearchError("Заказ с таким номером не найден");
        return null;
      }
      renderDetail(order);
      showDetailView();
      haptic("medium");
      return order;
    } catch (e) {
      if (fromSearch) showSearchError("Не получилось получить статус, попробуй ещё раз");
      else showToast("Не удалось обновить статус заказа");
      return null;
    }
  }

  // ---------- Search form ----------

  function showSearchError(text) {
    searchError.textContent = text;
    searchError.classList.add("is-visible");
    searchForm.classList.add("has-error");
    notify("error");
    setTimeout(() => searchForm.classList.remove("has-error"), 450);
  }

  function clearSearchError() {
    searchError.classList.remove("is-visible");
    searchError.textContent = "";
  }

  orderInput.addEventListener("input", () => {
    orderInput.value = orderInput.value.toUpperCase();
    clearSearchError();
  });

  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const value = orderInput.value.trim();
    if (!value) return;

    clearSearchError();
    searchBtn.classList.add("is-loading");
    searchBtn.disabled = true;

    const order = await openOrder(value, { fromSearch: true });

    searchBtn.classList.remove("is-loading");
    searchBtn.disabled = false;

    if (order) {
      await addTrackedNumber(order.order_number);
      orderInput.value = "";
      renderOrdersList();
    }
  });

  // ---------- Tracked orders list ----------

  async function addTrackedNumber(orderNumber) {
    trackedNumbers = [orderNumber, ...trackedNumbers.filter((n) => n !== orderNumber)].slice(0, MAX_TRACKED);
    await storage.set(trackedNumbers);
  }

  async function removeTrackedNumber(orderNumber) {
    trackedNumbers = trackedNumbers.filter((n) => n !== orderNumber);
    await storage.set(trackedNumbers);
    renderOrdersList();
    showToast(`Заказ ${orderNumber} убран из списка`);
  }

  function statusStateClass(status, total) {
    if (status >= total) return "is-done";
    if (status <= 1) return "";
    return "is-active";
  }

  function buildOrderItem(orderNumber, data) {
    const item = document.createElement("div");
    item.className = "order-item";

    if (!data || data.notFound) {
      item.innerHTML = `
        <div class="order-item-dot">?</div>
        <div class="order-item-body">
          <div class="order-item-number">${orderNumber}</div>
          <div class="order-item-product">Заказ не найден</div>
        </div>
        <button class="order-item-remove" type="button" aria-label="Удалить">×</button>
      `;
    } else {
      const total = (data.statuses || []).length || 6;
      const stateClass = statusStateClass(data.status, total);
      const dotContent = data.status >= total ? CHECK_SVG : `<span>${data.status}</span>`;
      item.innerHTML = `
        <div class="order-item-dot ${stateClass}">${dotContent}</div>
        <div class="order-item-body">
          <div class="order-item-number">${orderNumber}</div>
          <div class="order-item-product">${escapeHtml(data.product || "Товар не указан")}</div>
        </div>
        <div class="order-item-status ${stateClass}">${data.status_label || ""}</div>
        <button class="order-item-remove" type="button" aria-label="Удалить">×</button>
      `;
    }

    item.addEventListener("click", (e) => {
      if (e.target.closest(".order-item-remove")) return;
      haptic("light");
      openOrder(orderNumber);
    });

    item.querySelector(".order-item-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      haptic("rigid");
      removeTrackedNumber(orderNumber);
    });

    return item;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function renderOrdersList() {
    const hasOrders = trackedNumbers.length > 0;
    ordersSection.classList.toggle("is-visible", hasOrders);
    emptyState.classList.toggle("is-visible", !hasOrders);
    ordersCount.textContent = hasOrders ? String(trackedNumbers.length) : "";

    if (!hasOrders) {
      ordersList.innerHTML = "";
      return;
    }

    ordersList.innerHTML = "";
    const skeletons = trackedNumbers.map((num) => {
      const el = document.createElement("div");
      el.className = "order-item";
      el.style.opacity = "0.5";
      el.innerHTML = `
        <div class="order-item-dot">…</div>
        <div class="order-item-body">
          <div class="order-item-number">${num}</div>
          <div class="order-item-product">Загрузка…</div>
        </div>
      `;
      ordersList.appendChild(el);
      return el;
    });

    const results = await Promise.all(
      trackedNumbers.map((num) => fetchOrderStatus(num).catch(() => ({ notFound: true })))
    );

    ordersList.innerHTML = "";
    trackedNumbers.forEach((num, idx) => {
      const el = buildOrderItem(num, results[idx]);
      el.style.animationDelay = `${idx * 60}ms`;
      ordersList.appendChild(el);
    });
  }

  // ---------- Init ----------

  async function init() {
    try {
      trackedNumbers = await storage.get();
      await renderOrdersList();
    } catch (e) {
      trackedNumbers = [];
      emptyState.classList.add("is-visible");
    }
  }

  init();
})();
