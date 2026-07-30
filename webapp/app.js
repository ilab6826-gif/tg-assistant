(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const API_BASE = "/api";

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

  function initData() {
    return tg && tg.initData ? tg.initData : "";
  }

  function unsafeUser() {
    return tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
  }

  // ---------- DOM ----------

  const heroGreeting = document.getElementById("hero-greeting");
  const refreshBtn = document.getElementById("refresh-btn");
  const loadingState = document.getElementById("loading-state");
  const ordersSection = document.getElementById("orders-section");
  const ordersList = document.getElementById("orders-list");
  const ordersCount = document.getElementById("orders-count");
  const emptyState = document.getElementById("empty-state");
  const emptySub = document.getElementById("empty-sub");
  const usernameHint = document.getElementById("username-hint");

  const searchForm = document.getElementById("search-form");
  const orderInput = document.getElementById("order-input");
  const searchBtn = document.getElementById("search-btn");
  const searchError = document.getElementById("search-error");

  const viewList = document.getElementById("view-list");
  const viewDetail = document.getElementById("view-detail");
  const backBtn = document.getElementById("back-btn");

  const gallery = document.getElementById("gallery");
  const galleryTrack = document.getElementById("gallery-track");
  const galleryDots = document.getElementById("gallery-dots");
  const galleryCounter = document.getElementById("gallery-counter");

  const detailNumber = document.getElementById("detail-number");
  const detailMeta = document.getElementById("detail-meta");
  const itemsList = document.getElementById("items-list");
  const itemsCount = document.getElementById("items-count");
  const detailStatusPill = document.getElementById("detail-status-pill");
  const progressPercent = document.getElementById("progress-percent");
  const progressFill = document.getElementById("progress-fill");
  const stepperEl = document.getElementById("stepper");
  const toastEl = document.getElementById("toast");

  let cachedOrders = [];
  let toastTimer = null;

  // ---------- Toast ----------

  function showToast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-visible"), 2200);
  }

  // ---------- API ----------

  async function fetchMyOrders() {
    const headers = {};
    const data = initData();
    if (data) headers["X-Telegram-Init-Data"] = data;

    const res = await fetch(`${API_BASE}/my-orders`, { headers });
    if (!res.ok) throw new Error("network");
    return res.json();
  }

  async function fetchOrderStatus(orderNumber) {
    const res = await fetch(`${API_BASE}/status/${encodeURIComponent(orderNumber)}`);
    if (res.status === 404) return { notFound: true };
    if (!res.ok) throw new Error("network");
    return res.json();
  }

  // ---------- Views ----------

  function showListView() {
    viewDetail.classList.remove("is-active");
    viewList.classList.add("is-active");
    document.body.classList.remove("is-detail");
    if (tg && tg.BackButton) tg.BackButton.hide();
  }

  function showDetailView() {
    viewList.classList.remove("is-active");
    viewDetail.classList.add("is-active");
    document.body.classList.add("is-detail");
    window.scrollTo({ top: 0, behavior: "instant" });
    if (tg && tg.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(showListView);
    }
  }

  backBtn.addEventListener("click", () => { haptic("light"); showListView(); });

  // ---------- Rendering ----------

  const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const BOX_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M21 8 12 3 3 8m18 0-9 5m9-5v9l-9 5m0-9L3 8m9 5v9M3 8v9l9 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function statusStateClass(status, total) {
    if (status >= total) return "is-done";
    if (status <= 1) return "";
    return "is-active";
  }

  function formatDate(isoLike) {
    if (!isoLike) return "";
    const parts = isoLike.split(" ");
    if (parts.length < 1) return isoLike;
    const [datePart] = parts;
    const [y, m, d] = datePart.split("-");
    if (!y || !m || !d) return isoLike;
    return `${d}.${m}.${y}`;
  }

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

  function plural(count, one, few, many) {
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
  }

  // ---------- Gallery ----------

  function updateGalleryIndicator() {
    const total = galleryTrack.children.length;
    if (!total) return;
    const width = galleryTrack.clientWidth || 1;
    const index = Math.max(0, Math.min(total - 1, Math.round(galleryTrack.scrollLeft / width)));
    galleryCounter.textContent = `${index + 1} / ${total}`;
    Array.from(galleryDots.children).forEach((dot, i) => {
      dot.classList.toggle("is-active", i === index);
    });
  }

  let galleryTicking = false;
  galleryTrack.addEventListener("scroll", () => {
    if (galleryTicking) return;
    galleryTicking = true;
    requestAnimationFrame(() => {
      galleryTicking = false;
      updateGalleryIndicator();
    });
  }, { passive: true });

  function renderGallery(photos) {
    const list = photos || [];
    galleryTrack.innerHTML = "";
    galleryDots.innerHTML = "";
    gallery.hidden = list.length === 0;
    if (!list.length) return;

    list.forEach((url, idx) => {
      const slide = document.createElement("div");
      slide.className = "gallery-slide";

      const img = document.createElement("img");
      img.src = url;
      img.alt = `Фото товара ${idx + 1}`;
      img.loading = idx === 0 ? "eager" : "lazy";
      slide.appendChild(img);
      galleryTrack.appendChild(slide);

      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "gallery-dot";
      dot.setAttribute("aria-label", `Фото ${idx + 1}`);
      dot.addEventListener("click", () => {
        haptic("light");
        galleryTrack.scrollTo({ left: galleryTrack.clientWidth * idx, behavior: "smooth" });
      });
      galleryDots.appendChild(dot);
    });

    // Точек больше восьми в строку не влезает — там хватит и счётчика.
    galleryDots.hidden = list.length < 2 || list.length > 8;
    galleryCounter.hidden = list.length < 2;
    galleryTrack.scrollLeft = 0;
    updateGalleryIndicator();
  }

  // ---------- Order details ----------

  function renderItems(items) {
    const list = items || [];
    itemsList.innerHTML = "";
    itemsCount.textContent = list.length ? String(list.length) : "";

    if (!list.length) {
      const li = document.createElement("li");
      li.className = "item-row is-empty";
      li.textContent = "Состав заказа уточняется";
      itemsList.appendChild(li);
      return;
    }

    list.forEach((item, idx) => {
      const meta = [];
      if (item.size) meta.push(`Размер ${item.size}`);
      if (item.color) meta.push(item.color);

      const li = document.createElement("li");
      li.className = "item-row";
      li.style.animationDelay = `${idx * 55}ms`;
      li.innerHTML = `
        <span class="item-index">${idx + 1}</span>
        <span class="item-body">
          <span class="item-name">${escapeHtml(item.product || "Товар")}</span>
          ${meta.length ? `<span class="item-meta">${escapeHtml(meta.join(" · "))}</span>` : ""}
        </span>
      `;
      itemsList.appendChild(li);
    });
  }

  function renderDetail(order) {
    const total = (order.statuses || []).length || 7;
    const progress = Math.min(100, Math.round((order.status / total) * 100));
    const items = order.items || [];

    renderGallery(order.photos);

    detailNumber.textContent = order.order_number;
    detailStatusPill.textContent = order.status_label || "";
    detailStatusPill.classList.toggle("is-done", order.status >= total);

    const metaParts = [];
    if (items.length) {
      metaParts.push(`${items.length} ${plural(items.length, "товар", "товара", "товаров")}`);
    }
    if (order.created_at) metaParts.push(`оформлен ${formatDate(order.created_at)}`);
    detailMeta.textContent = metaParts.join(" · ");

    renderItems(items);

    progressPercent.textContent = `${progress}%`;
    progressFill.style.width = `${progress}%`;
    renderStepper(order);
  }

  function openOrderDetail(order) {
    renderDetail(order);
    showDetailView();
    haptic("medium");
  }

  function buildOrderItem(order) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "order-item";

    const total = (order.statuses || []).length || 7;
    const stateClass = statusStateClass(order.status, total);
    const dotContent = order.status >= total ? CHECK_SVG : `<span>${order.status}</span>`;
    const photos = order.photos || [];
    const count = (order.items || []).length;

    const preview = photos.length
      ? `<img class="order-item-photo" src="${escapeHtml(photos[0])}" alt="" loading="lazy">`
      : `<span class="order-item-photo is-empty">${BOX_SVG}</span>`;
    const countChip = count > 1
      ? `<span class="order-item-chip">${count} ${count > 4 ? "товаров" : "товара"}</span>`
      : "";

    item.innerHTML = `
      <div class="order-item-lead">
        ${preview}
        <span class="order-item-badge ${stateClass}">${dotContent}</span>
      </div>
      <div class="order-item-body">
        <div class="order-item-number">${escapeHtml(order.order_number)}${countChip}</div>
        <div class="order-item-product">${escapeHtml(order.product || "Товар не указан")}</div>
        <div class="order-item-status ${stateClass}">${escapeHtml(order.status_label || "")}</div>
      </div>
      <svg class="order-item-chevron" viewBox="0 0 24 24" fill="none"><path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    `;

    item.addEventListener("click", () => {
      haptic("light");
      openOrderDetail(order);
    });

    return item;
  }

  function setLoading(isLoading) {
    loadingState.classList.toggle("is-visible", isLoading);
    refreshBtn.classList.toggle("is-spinning", isLoading);
  }

  function renderOrdersList(orders, { needsUsername = false } = {}) {
    cachedOrders = orders;
    const hasOrders = orders.length > 0;

    ordersSection.classList.toggle("is-visible", hasOrders);
    emptyState.classList.toggle("is-visible", !hasOrders && !needsUsername);
    usernameHint.classList.toggle("is-visible", needsUsername);
    ordersCount.textContent = hasOrders ? String(orders.length) : "";

    ordersList.innerHTML = "";
    orders.forEach((order, idx) => {
      const el = buildOrderItem(order);
      el.style.animationDelay = `${idx * 60}ms`;
      ordersList.appendChild(el);
    });

    if (needsUsername) {
      emptySub.textContent = "Задай @username в настройках Telegram — тогда заказы будут подтягиваться автоматически.";
    } else if (!hasOrders) {
      emptySub.textContent = "Когда менеджер оформит заказ на твой @username, он появится здесь автоматически.";
    }
  }

  async function loadOrders({ silent = false } = {}) {
    if (!silent) setLoading(true);
    try {
      const payload = await fetchMyOrders();
      const user = payload.user || {};
      const name = user.first_name || (unsafeUser() && unsafeUser().first_name) || "друг";
      heroGreeting.textContent = `Привет, ${name}!`;
      renderOrdersList(payload.orders || [], { needsUsername: !!payload.needs_username });
      if (silent) showToast("Заказы обновлены");
    } catch (e) {
      if (!silent) {
        renderOrdersList([]);
        emptyState.classList.add("is-visible");
        emptySub.textContent = "Не удалось загрузить заказы. Проверь интернет и попробуй обновить.";
      } else {
        showToast("Не удалось обновить");
        notify("error");
      }
    } finally {
      setLoading(false);
    }
  }

  // ---------- Search by number (fallback) ----------

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

    try {
      const order = await fetchOrderStatus(value);
      if (order.notFound) {
        showSearchError("Заказ с таким номером не найден");
      } else {
        openOrderDetail(order);
        orderInput.value = "";
      }
    } catch (err) {
      showSearchError("Не получилось найти заказ, попробуй ещё раз");
    } finally {
      searchBtn.classList.remove("is-loading");
      searchBtn.disabled = false;
    }
  });

  refreshBtn.addEventListener("click", () => {
    haptic("light");
    loadOrders({ silent: true });
  });

  // ---------- Init ----------

  loadOrders();
})();
