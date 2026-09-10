(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const API_BASE = "/api";
  const THEME_BG = "#0E1E39";

  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor(THEME_BG); } catch (e) {}
    try { tg.setBackgroundColor(THEME_BG); } catch (e) {}
    // Иначе на iOS свайп по галерее и списку случайно закрывает приложение.
    try { tg.disableVerticalSwipes(); } catch (e) {}
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

  function selectionChanged() {
    if (tg && tg.HapticFeedback) {
      try { tg.HapticFeedback.selectionChanged(); } catch (e) {}
    }
  }

  function initData() {
    return tg && tg.initData ? tg.initData : "";
  }

  function unsafeUser() {
    return tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
  }

  // ---------- DOM ----------

  const topbar = document.getElementById("topbar");
  const topbarTitle = document.getElementById("topbar-title");
  const heroGreeting = document.getElementById("hero-greeting");
  const refreshBtn = document.getElementById("refresh-btn");

  const loadingState = document.getElementById("loading-state");
  const ordersSection = document.getElementById("orders-section");
  const ordersList = document.getElementById("orders-list");
  const ordersCount = document.getElementById("orders-count");
  const filters = document.getElementById("filters");
  const segmentedThumb = document.getElementById("segmented-thumb");
  const segments = Array.from(document.querySelectorAll(".segment"));
  const filterEmpty = document.getElementById("filter-empty");
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
  const detailStatusPill = document.getElementById("detail-status-pill");
  const itemsList = document.getElementById("items-list");
  const itemsCount = document.getElementById("items-count");
  const progressPercent = document.getElementById("progress-percent");
  const progressFill = document.getElementById("progress-fill");
  const progressHint = document.getElementById("progress-hint");
  const stepperEl = document.getElementById("stepper");
  const toastEl = document.getElementById("toast");
  const trackingCard = document.getElementById("tracking-card");
  const trackingCarrier = document.getElementById("tracking-carrier");
  const trackingNumberBtn = document.getElementById("tracking-number");
  const trackingLinkBtn = document.getElementById("tracking-link");

  const inviteCard = document.getElementById("invite-card");
  const inviteSub = document.getElementById("invite-sub");
  const inviteInvited = document.getElementById("invite-invited");
  const inviteRewarded = document.getElementById("invite-rewarded");
  const inviteBonus = document.getElementById("invite-bonus");
  const inviteShare = document.getElementById("invite-share");
  const inviteCopy = document.getElementById("invite-copy");
  const homescreenCard = document.getElementById("homescreen-card");
  const homescreenAdd = document.getElementById("homescreen-add");
  const homescreenLater = document.getElementById("homescreen-later");

  let cachedOrders = [];
  let cachedReferral = null;
  let activeFilter = "all";
  let toastTimer = null;

  // ---------- Верхняя панель ----------

  function syncTopbar() {
    topbar.classList.toggle("is-stuck", window.scrollY > 28);
  }

  window.addEventListener("scroll", syncTopbar, { passive: true });

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

  // ---------- Навигация между экранами ----------

  function showListView() {
    viewDetail.classList.remove("is-active");
    viewList.classList.add("is-active");
    document.body.classList.remove("is-detail");
    topbarTitle.textContent = "Мои заказы";
    if (tg && tg.BackButton) tg.BackButton.hide();
  }

  function showDetailView(order) {
    viewList.classList.remove("is-active");
    viewDetail.classList.add("is-active");
    document.body.classList.add("is-detail");
    topbarTitle.textContent = order ? order.order_number : "Заказ";
    window.scrollTo({ top: 0, behavior: "instant" });
    syncTopbar();
    if (tg && tg.BackButton) tg.BackButton.show();
  }

  backBtn.addEventListener("click", () => { haptic("light"); showListView(); });
  if (tg && tg.BackButton) tg.BackButton.onClick(showListView);

  // ---------- Утилиты ----------

  const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const BOX_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M21 8 12 3 3 8m18 0-9 5m9-5v9l-9 5m0-9L3 8m9 5v9M3 8v9l9 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function plural(count, one, few, many) {
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
  }

  function formatDate(isoLike) {
    if (!isoLike) return "";
    const [datePart] = isoLike.split(" ");
    const [y, m, d] = datePart.split("-");
    if (!y || !m || !d) return isoLike;
    return `${d}.${m}.${y}`;
  }

  function formatMoney(value) {
    return `${Number(value || 0).toLocaleString("ru-RU")} ₽`;
  }

  function totalSteps(order) {
    return (order.statuses || []).length || 7;
  }

  function isDelivered(order) {
    return order.status >= totalSteps(order);
  }

  function statusStateClass(order) {
    return isDelivered(order) ? "is-done" : "is-active";
  }

  // ---------- Галерея ----------

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

    // Браузер возвращает прежнее смещение уже после отрисовки новых слайдов:
    // без второго сброса заказ открывается на том фото, где его закрыли.
    requestAnimationFrame(() => {
      galleryTrack.scrollLeft = 0;
      updateGalleryIndicator();
    });
  }

  // ---------- Детали заказа ----------

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
      li.style.animationDelay = `${120 + idx * 55}ms`;
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

  function renderTracking(order) {
    const number = (order && order.tracking) || "";
    trackingCard.hidden = !number;
    trackingLinkBtn.hidden = true;
    trackingLinkBtn.onclick = null;
    if (!number) return;

    trackingCarrier.textContent = order.carrier || "";
    trackingNumberBtn.textContent = number;
    trackingNumberBtn.onclick = async () => {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(number);
        } else {
          throw new Error("clipboard");
        }
        showToast("Трек скопирован");
        haptic("light");
      } catch (err) {
        showToast(number);
      }
    };

    const url = order.tracking_url || "";
    if (!url) return;
    trackingLinkBtn.hidden = false;
    trackingLinkBtn.onclick = () => {
      haptic("medium");
      if (tg && typeof tg.openLink === "function") {
        try {
          tg.openLink(url);
          return;
        } catch (err) {}
      }
      window.open(url, "_blank", "noopener");
    };
  }

  function renderStepper(order) {
    const statuses = order.statuses || [];
    const current = order.status;
    stepperEl.innerHTML = "";

    statuses.forEach((label, idx) => {
      const stepNum = idx + 1;
      const li = document.createElement("li");
      li.className = "step";
      li.style.animationDelay = `${160 + idx * 60}ms`;

      let state = "pending";
      if (stepNum < current) state = "done";
      else if (stepNum === current) state = "active";
      li.classList.add(`is-${state}`);

      li.innerHTML = `
        <div class="step-line"><div class="step-line-fill"></div></div>
        <div class="step-node"><span>${stepNum}</span>${CHECK_SVG}</div>
        <div class="step-body">
          <div class="step-title">${escapeHtml(label)}</div>
          <div class="step-hint">Заказ здесь сейчас</div>
        </div>
      `;
      stepperEl.appendChild(li);
    });
  }

  function renderDetail(order) {
    const total = totalSteps(order);
    const done = isDelivered(order);
    const progress = Math.min(100, Math.round((order.status / total) * 100));
    const items = order.items || [];

    renderGallery(order.photos);

    detailNumber.textContent = order.order_number;
    detailStatusPill.textContent = order.status_label || "";
    detailStatusPill.classList.toggle("is-done", done);

    const metaParts = [];
    if (items.length) {
      metaParts.push(`${items.length} ${plural(items.length, "товар", "товара", "товаров")}`);
    }
    if (order.created_at) metaParts.push(`оформлен ${formatDate(order.created_at)}`);
    detailMeta.textContent = metaParts.join(" · ");

    renderItems(items);
    renderTracking(order);

    progressPercent.textContent = `${progress}%`;
    progressHint.textContent = done
      ? "Заказ доставлен — спасибо за покупку"
      : order.tracking
        ? `Этап ${order.status} из ${total} · трек ниже`
        : `Этап ${order.status} из ${total}`;

    // Ширина ставится в следующем кадре, иначе переход от 0% не проигрывается.
    progressFill.style.width = "0%";
    requestAnimationFrame(() => { progressFill.style.width = `${progress}%`; });

    renderStepper(order);
  }

  function openOrderDetail(order) {
    renderDetail(order);
    showDetailView(order);
    haptic("medium");
  }

  // ---------- Строка списка ----------

  function buildOrderItem(order) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "order-item";

    const total = totalSteps(order);
    const done = isDelivered(order);
    const stateClass = statusStateClass(order);
    const photos = order.photos || [];
    const count = (order.items || []).length;

    const preview = photos.length
      ? `<img class="order-item-photo" src="${escapeHtml(photos[0])}" alt="" loading="lazy">`
      : `<span class="order-item-photo is-empty">${BOX_SVG}</span>`;
    const badge = done ? `<span class="order-item-badge">${CHECK_SVG}</span>` : "";
    const countChip = count > 1
      ? `<span class="order-item-chip">${count} ${plural(count, "товар", "товара", "товаров")}</span>`
      : "";
    const trackChip = order.tracking
      ? `<span class="order-item-chip">Трек</span>`
      : "";
    const dashes = Array.from({ length: total }, (_, i) => {
      const on = i < order.status ? " is-on" : "";
      return `<span class="${on.trim()}" style="animation-delay:${i * 45}ms"></span>`;
    }).join("");

    row.innerHTML = `
      <span class="order-item-lead">
        ${preview}
        ${badge}
      </span>
      <span class="order-item-body">
        <span class="order-item-number">${escapeHtml(order.order_number)}${countChip}${trackChip}</span>
        <span class="order-item-product">${escapeHtml(order.product || "Товар не указан")}</span>
        <span class="order-item-status ${stateClass}">${escapeHtml(order.status_label || "")}</span>
        <span class="order-item-steps ${done ? "is-done" : ""}">${dashes}</span>
      </span>
      <svg class="order-item-chevron" viewBox="0 0 24 24" fill="none"><path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    `;

    row.addEventListener("click", () => {
      haptic("light");
      openOrderDetail(order);
    });

    return row;
  }

  // ---------- Фильтры ----------

  function matchesFilter(order) {
    if (activeFilter === "active") return !isDelivered(order);
    if (activeFilter === "done") return isDelivered(order);
    return true;
  }

  function paintOrders() {
    const visible = cachedOrders.filter(matchesFilter);

    ordersList.innerHTML = "";
    visible.forEach((order, idx) => {
      const row = buildOrderItem(order);
      row.style.animationDelay = `${idx * 55}ms`;
      ordersList.appendChild(row);
    });

    ordersCount.textContent = visible.length ? String(visible.length) : "";
    filterEmpty.classList.toggle("is-visible", visible.length === 0);
    ordersList.hidden = visible.length === 0;
  }

  function applyFilter(name, index) {
    activeFilter = name;
    segments.forEach((btn, i) => btn.classList.toggle("is-active", i === index));
    segmentedThumb.style.transform = `translateX(${index * 100}%)`;
  }

  function setFilter(name, index) {
    if (activeFilter === name) return;
    applyFilter(name, index);
    selectionChanged();
    paintOrders();
  }

  segments.forEach((btn, index) => {
    btn.addEventListener("click", () => setFilter(btn.dataset.filter, index));
  });

  // ---------- Список ----------

  function setLoading(isLoading) {
    loadingState.classList.toggle("is-visible", isLoading);
    refreshBtn.classList.toggle("is-spinning", isLoading);
  }

  function renderOrdersList(orders, { needsUsername = false } = {}) {
    cachedOrders = orders;
    const hasOrders = orders.length > 0;
    const showFilters = orders.length > 1;

    ordersSection.classList.toggle("is-visible", hasOrders);
    emptyState.classList.toggle("is-visible", !hasOrders && !needsUsername);
    usernameHint.classList.toggle("is-visible", needsUsername);
    filters.classList.toggle("is-visible", showFilters);

    // Со скрытыми сегментами выбранная категория недоступна — возвращаем «Все».
    if (!showFilters) applyFilter("all", 0);

    if (needsUsername) {
      emptySub.textContent = "Задай @username в настройках Telegram — тогда заказы будут подтягиваться автоматически.";
    } else if (!hasOrders) {
      emptySub.textContent = "Когда менеджер оформит заказ на твой @username, он появится здесь автоматически.";
    }

    paintOrders();
  }

  function renderInvite(referral) {
    cachedReferral = referral || null;
    const visible = !!(referral && referral.code);
    inviteCard.classList.toggle("is-visible", visible);
    if (!visible) return;

    inviteSub.textContent =
      `Друг оформляет первый заказ — тебе ${formatMoney(referral.your_bonus)} на следующий, ` +
      `ему скидка ${formatMoney(referral.friend_bonus)} на первый.`;
    inviteInvited.textContent = String(referral.invited || 0);
    inviteRewarded.textContent = String(referral.rewarded || 0);
    inviteBonus.textContent = formatMoney(referral.bonus);
  }

  async function copyInviteLink() {
    if (!cachedReferral) return;
    const value = cachedReferral.link || cachedReferral.code;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        throw new Error("clipboard");
      }
      showToast("Ссылка скопирована");
      haptic("light");
    } catch (err) {
      showToast(cachedReferral.link ? "Не удалось скопировать" : `Код: ${cachedReferral.code}`);
    }
  }

  inviteShare.addEventListener("click", () => {
    if (!cachedReferral) return;
    haptic("medium");
    const link = cachedReferral.link;
    if (link && tg && typeof tg.openTelegramLink === "function") {
      const share = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(cachedReferral.share_text || "")}`;
      try {
        tg.openTelegramLink(share);
        return;
      } catch (err) {}
    }
    copyInviteLink();
  });

  inviteCopy.addEventListener("click", () => {
    haptic("light");
    copyInviteLink();
  });

  // ---------- На главный экран ----------

  const HOME_SCREEN_HIDE_KEY = "pr0ject-homescreen-hidden";

  function hideHomeScreenCard() {
    homescreenCard.classList.remove("is-visible");
  }

  function showHomeScreenCard() {
    try {
      if (window.localStorage && localStorage.getItem(HOME_SCREEN_HIDE_KEY) === "1") return;
    } catch (err) {}
    homescreenCard.classList.add("is-visible");
  }

  function rememberHomeScreenHidden() {
    try { localStorage.setItem(HOME_SCREEN_HIDE_KEY, "1"); } catch (err) {}
  }

  function initHomeScreen() {
    if (!tg || typeof tg.addToHomeScreen !== "function") return;
    if (typeof tg.isVersionAtLeast === "function" && !tg.isVersionAtLeast("8.0")) return;

    const applyStatus = (status) => {
      if (status === "added" || status === "unsupported") {
        hideHomeScreenCard();
        return;
      }
      showHomeScreenCard();
    };

    try {
      tg.onEvent("homeScreenAdded", () => {
        rememberHomeScreenHidden();
        hideHomeScreenCard();
        showToast("Иконка на главном экране");
        notify("success");
      });
    } catch (err) {}

    try {
      tg.onEvent("homeScreenFailed", () => {
        showToast("Не получилось добавить");
      });
    } catch (err) {}

    try {
      tg.checkHomeScreenStatus(applyStatus);
    } catch (err) {
      showHomeScreenCard();
    }
  }

  homescreenAdd.addEventListener("click", () => {
    haptic("medium");
    if (!tg || typeof tg.addToHomeScreen !== "function") {
      showToast("Открой трекер в Telegram на телефоне");
      return;
    }
    try {
      tg.addToHomeScreen();
    } catch (err) {
      showToast("Обнови Telegram — эта функция в новых версиях");
    }
  });

  homescreenLater.addEventListener("click", () => {
    haptic("light");
    rememberHomeScreenHidden();
    hideHomeScreenCard();
  });

  async function loadOrders({ silent = false } = {}) {
    if (!silent) setLoading(true);
    else refreshBtn.classList.add("is-spinning");

    try {
      const payload = await fetchMyOrders();
      const user = payload.user || {};
      const fallback = unsafeUser();
      const name = user.first_name || (fallback && fallback.first_name) || "друг";
      heroGreeting.textContent = `Привет, ${name}`;
      renderOrdersList(payload.orders || [], { needsUsername: !!payload.needs_username });
      renderInvite(payload.referral);
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

  // ---------- Поиск по номеру ----------

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

  // ---------- Старт ----------

  syncTopbar();
  initHomeScreen();
  loadOrders();
})();
