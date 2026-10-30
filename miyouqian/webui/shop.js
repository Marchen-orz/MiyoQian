// 计划保存在内存里，筛选和翻页不会丢掉未渲染的计划。
let shopRunningProgress = {};
let shopScheduler = {};
let shopGoods = [];
let shopGames = [{ key: "", name: "全部分区" }];
let shopSelectedGame = "";
let shopSelectedPlans = new Set();
let shopGoodsLoading = false;
let shopGoodsLoadSeq = 0;
let shopExchangeNowGoodsId = "";
let shopFilterStatus = "";
let shopPlanFilter = "";
let shopCurrentPage = 1;
let shopServerOffset = 0;
let shopRevision = 0;
let shopSavedRevision = 0;
let shopPlanRenderKey = "";
let shopBatchRunning = false;
let shopDialogOpen = false;
const shopPendingRuns = new Set();
const shopQueuedRuns = new Set();
const shopMetaCache = new Map();
const shopDetailCache = new Map();
const SHOP_PAGE_SIZE = 4;

function shopNow() { return Date.now() / 1000 + shopServerOffset; }
function shopPlans() { return config?.shop_exchange?.plans || []; }
function shopPlanById(id) { return shopPlans().find((p) => p.id === id); }
function markShopDirty() { shopRevision += 1; }
function shopError(error) { showToast(error.message || String(error), "error"); }
function shopIsRunning(id) {
  return shopQueuedRuns.has(id) || shopPendingRuns.has(id) || Boolean(shopRunningProgress[id]) || (shopScheduler.running_plans || []).includes(id);
}
function shopPlanAccountIndex(plan, accounts = config?.accounts || []) {
  const stuid = String(plan.account_stuid || "");
  if (stuid) return accounts.findIndex((a) => !isOverseas(a) && String(a.stuid || "") === stuid);
  const index = Number(plan.account_index ?? 0);
  return accounts[index] && !isOverseas(accounts[index]) ? index : -1;
}
function loggedInAccountChoices() {
  return (config?.accounts || []).map((account, index) => ({ account, index }))
    .filter(({ account }) => !account._draft && account.stuid && account.cookie && !isOverseas(account));
}
function shopPlanState(plan) {
  if (shopQueuedRuns.has(plan.id)) return { key: "running", label: "等待执行", tone: "running" };
  if (shopIsRunning(plan.id)) return { key: "running", label: "兑换中", tone: "running" };
  const account = config?.accounts?.[shopPlanAccountIndex(plan)];
  if (!account?.stuid || !account.cookie) return { key: "orphan", label: "账号需处理", tone: "danger" };
  if (plan.last_ok === true) return { key: "done", label: "已成功", tone: "ok" };
  if (plan.enable === false || plan.auto === false) return { key: "paused", label: "已暂停", tone: "paused" };
  if ((Number(plan.type) === 1 && !plan.address_id) || (Number(plan.type) === 2 && (!plan.uid || !plan.region || !plan.game_biz))) return { key: "unset", label: "收货信息待补全", tone: "warn" };
  if (plan.last_ok === false) return { key: "failed", label: Number(plan.exchange_at) > shopNow() && String(plan.last_attempt_key || "") !== `${plan.goods_id}:${Number(plan.exchange_at)}` && config?.shop_exchange?.enable ? "上次失败 · 仍待定时" : "兑换失败", tone: "danger" };
  const at = Number(plan.exchange_at || 0);
  if (!at) return { key: "unset", label: "未设时间", tone: "warn" };
  if (String(plan.last_attempt_key || "") === `${plan.goods_id}:${at}`) return { key: "missed", label: "本轮已执行", tone: "warn" };
  if (at <= shopNow() && !shopScheduler.phases?.[plan.id]) return { key: "missed", label: "已错过时间", tone: "warn" };
  if (!config?.shop_exchange?.enable) return { key: "pending", label: "总开关已关闭", tone: "paused" };
  const phase = shopScheduler.phases?.[plan.id];
  return { key: "pending", label: phase === "calibrating" ? "校准时间" : phase === "precise" ? "精确等待" : "等待兑换", tone: "active" };
}
function shopPlanStatus(plan) {
  const progress = shopRunningProgress[plan.id];
  if (shopQueuedRuns.has(plan.id)) return "批量兑换排队中";
  if (progress) return `${progress.attempt ? `第 ${progress.attempt} 次尝试 · ` : ""}${progress.message || "准备兑换"}`;
  return plan.last_result || "";
}
function shopCountdown(timestamp) {
  const delta = Math.ceil(Number(timestamp || 0) - shopNow());
  if (!timestamp) return "未设置时间";
  if (delta <= 0) return "已到兑换时间";
  const days = Math.floor(delta / 86400);
  const hours = Math.floor(delta % 86400 / 3600);
  const minutes = Math.floor(delta % 3600 / 60);
  const seconds = delta % 60;
  return days ? `${days} 天 ${hours} 小时后` : `${hours ? `${hours} 小时 ` : ""}${minutes} 分 ${seconds} 秒后`;
}
function getFilteredPlans() {
  const attention = new Set(["orphan", "failed", "missed", "unset"]);
  const rank = { running: 0, pending: 1, orphan: 2, failed: 2, unset: 2, missed: 3, paused: 4, done: 5 };
  return shopPlans().filter((plan) => {
    const state = shopPlanState(plan).key;
    return !shopPlanFilter || (shopPlanFilter === "attention" ? attention.has(state) : state === shopPlanFilter);
  }).sort((a, b) => rank[shopPlanState(a).key] - rank[shopPlanState(b).key] ||
    (Number(a.exchange_at) || Infinity) - (Number(b.exchange_at) || Infinity));
}
function collectShopExchange() {
  const shop = config?.shop_exchange || {};
  const number = (id, fallback) => {
    const value = $(id)?.value;
    return value === undefined || value === "" ? fallback : Number(value);
  };
  return { ...shop, enable: $("shopEnable")?.checked ?? shop.enable ?? false,
    retry_seconds: number("shopRetrySeconds", shop.retry_seconds ?? 20),
    retry_interval: number("shopRetryInterval", shop.retry_interval ?? 0.4),
    push: $("shopPush")?.checked ?? shop.push ?? false, plans: shop.plans || [] };
}
function renderShopConfig() {
  if (!$("shopEnable")) return;
  const shop = config?.shop_exchange || {};
  $("shopEnable").checked = Boolean(shop.enable);
  $("shopRetrySeconds").value = shop.retry_seconds ?? 20;
  $("shopRetryInterval").value = shop.retry_interval ?? 0.4;
  $("shopPush").checked = Boolean(shop.push);
  renderShopGameFilter();
  renderShopGoods();
  renderShopPlans();
}
function renderShopPlans(force = true) {
  const list = $("shopPlans");
  if (!list) return;
  const existing = new Set(shopPlans().map((p) => p.id));
  shopSelectedPlans = new Set([...shopSelectedPlans].filter((id) => existing.has(id)));
  const plans = getFilteredPlans();
  const signature = JSON.stringify([plans, shopRunningProgress, shopScheduler.phases, [...shopSelectedPlans], [...shopPendingRuns], [...shopQueuedRuns], config?.shop_exchange?.enable, plans.map(shopPlanState), plans.map((p) => shopCachedMeta(p))]);
  if (!force && signature === shopPlanRenderKey) { updateShopCountdowns(); return; }
  if (!force && isEditingShopConfig()) { updateShopCountdowns(); return; }
  shopPlanRenderKey = signature;
  list.innerHTML = plans.length ? plans.map(shopPlanRow).join("") :
    `<div class="empty-state shop-empty"><strong>${shopPlans().length ? "没有符合条件的计划" : "暂无兑换计划"}</strong><span>在左侧商品点「计划」，可一次为多个账号添加。</span></div>`;
  if ($("shopPlansMetric")) $("shopPlansMetric").textContent = String(shopPlans().length);
  updateShopSelection();
}
function shopAccountOptions(plan) {
  const selected = shopPlanAccountIndex(plan);
  return (selected < 0 ? `<option value="" data-stuid="${escapeAttr(plan.account_stuid || "")}" selected>账号已删除，请重新选择</option>` : "") +
    (config?.accounts || []).map((a, index) => isOverseas(a) ? "" : `<option value="${index}" data-stuid="${escapeAttr(a.stuid || "")}" ${index === selected ? "selected" : ""}>${escapeHtml(accountLabel(a))}</option>`).join("");
}
function shopPlanRow(plan) {
  const id = escapeAttr(plan.id);
  const state = shopPlanState(plan);
  const running = shopIsRunning(plan.id);
  const account = config?.accounts?.[shopPlanAccountIndex(plan)];
  const result = shopPlanStatus(plan);
  return `<article class="shop-plan" data-shop-plan="${id}">
    <div class="shop-plan-summary">
      <label class="check-row shop-plan-check"><input type="checkbox" aria-label="选择 ${escapeAttr(plan.goods_name || plan.goods_id)}" data-plan-select="${id}" ${shopSelectedPlans.has(plan.id) ? "checked" : ""}></label>
      <div class="shop-plan-title"><strong>${escapeHtml(plan.goods_name || plan.goods_id)}</strong><small>${escapeHtml(account ? accountLabel(account) : "账号已删除")} · ${escapeHtml(String(plan.price ?? "-"))} 米游币</small><small>${escapeHtml(timestampToBeijingText(plan.exchange_at) || "未设置时间")} · <span data-shop-countdown="${Number(plan.exchange_at || 0)}">${escapeHtml(shopCountdown(plan.exchange_at))}</span></small></div>
      <div class="shop-plan-badges"><span class="plan-badge ${state.tone}">${state.label}</span></div>
    </div>
    <div class="shop-plan-foot"><span class="shop-plan-result" title="${escapeAttr(result)}">${escapeHtml(result)}</span>
      <div class="shop-plan-actions"><button class="ghost" type="button" data-shop-edit="${id}" aria-haspopup="dialog" ${running ? "disabled" : ""}>配置</button><button class="ghost" type="button" data-shop-plan-now="${id}" ${running ? "disabled" : ""}>${running ? "兑换中" : "兑换"}</button><button class="ghost icon-only" type="button" data-shop-remove="${id}" title="删除计划" ${running ? "disabled" : ""}><svg><use href="#i-trash"></use></svg></button></div></div>
  </article>`;
}
function updateShopSelection() {
  const plans = getFilteredPlans();
  const selected = plans.filter((p) => shopSelectedPlans.has(p.id)).length;
  const all = $("shopPlanSelectAll");
  if (all) { all.checked = plans.length > 0 && selected === plans.length; all.indeterminate = selected > 0 && selected < plans.length; }
  if ($("shopSelectedCount")) $("shopSelectedCount").textContent = shopSelectedPlans.size ? `已选 ${shopSelectedPlans.size} 项` : "全选";
  $("shopBatchBar")?.classList.toggle("is-hidden", !shopSelectedPlans.size);
  document.querySelectorAll("[data-shop-batch]").forEach((el) => { el.disabled = shopBatchRunning; });
  const dirty = shopRevision > shopSavedRevision;
  if ($("shopSaveState")) { $("shopSaveState").textContent = dirty ? "有更改尚未保存，点此重试" : ""; $("shopSaveState").style.cursor = dirty ? "pointer" : ""; }
  const cleanup = shopPlans().filter(shopCanCleanup).length;
  if ($("shopCleanupBtn")) { $("shopCleanupBtn").textContent = cleanup ? `清理（${cleanup}）` : "清理"; $("shopCleanupBtn").disabled = !cleanup; }
}
function shopCanCleanup(plan) { return ["done", "missed"].includes(shopPlanState(plan).key) && !shopIsRunning(plan.id); }
function isShopGoodSoldOut(good) { return Boolean(good?.sold_out); }
function canShopGoodAddPlan(good) { return good?.display_status !== "ended" && (!isShopGoodSoldOut(good) || good?.display_status === "sold_out_with_next"); }
function canShopGoodExchangeNow(good) { return !isShopGoodSoldOut(good) && ["online", "always"].includes(good?.display_status); }
function getFilteredGoods() {
  return shopGoods.filter((good) => {
    if (shopFilterStatus === "sold_out") return isShopGoodSoldOut(good);
    if (shopFilterStatus === "available") return canShopGoodExchangeNow(good);
    return true;
  });
}
function renderShopGameFilter() {
  if ($("shopGameFilter")) $("shopGameFilter").innerHTML = shopGames.map((g) => `<option value="${escapeAttr(g.key)}" ${g.key === shopSelectedGame ? "selected" : ""}>${escapeHtml(g.name)}</option>`).join("");
}
function renderShopGoods() {
  const list = $("shopGoods");
  if (!list) return;
  if ($("shopGoodsMetric")) $("shopGoodsMetric").textContent = shopGoodsLoading ? "加载中" : `${shopGoods.length} 件`;
  const select = $("shopGameFilter"), button = $("shopRefreshBtn");
  if (select) select.disabled = shopGoodsLoading;
  if (button) {
    button.disabled = shopGoodsLoading;
    button.classList.toggle("is-loading", shopGoodsLoading);
    const label = button.querySelector("span");
    if (label) label.textContent = shopGoodsLoading ? "加载中" : "刷新商品";
  }
  if (shopGoodsLoading) {
    list.innerHTML = `<div class="empty-state shop-empty shop-loading"><span class="qr-loading" aria-hidden="true"></span><strong>商品加载中</strong><span>正在获取商品图片、兑换时间、库存和限购信息。</span></div>`;
    renderShopPagination();
    return;
  }
  const filtered = getFilteredGoods();
  shopCurrentPage = Math.max(1, Math.min(shopCurrentPage, Math.ceil(filtered.length / SHOP_PAGE_SIZE) || 1));
  const start = (shopCurrentPage - 1) * SHOP_PAGE_SIZE;
  list.innerHTML = filtered.length ? filtered.slice(start, start + SHOP_PAGE_SIZE).map((g) => shopGoodCard(g, shopGoods.indexOf(g))).join("") :
    `<div class="empty-state shop-empty"><strong>暂无商品数据</strong><span>${shopFilterStatus ? "当前筛选条件下没有商品。" : "点击刷新商品后，会显示兑换时间、库存、价格和图片。"}</span></div>`;
  renderShopPagination();
}
function shopGoodCard(good, index) {
  const sold = isShopGoodSoldOut(good);
  const canAdd = canShopGoodAddPlan(good);
  const canNow = canShopGoodExchangeNow(good);
  const exchanging = shopExchangeNowGoodsId === String(good.goods_id || "");
  const progress = Object.entries(shopRunningProgress).find(([id]) => id.startsWith(`adhoc:${good.goods_id}:`))?.[1];
  const nowText = exchanging ? `兑换中${progress?.attempt ? ` · ${progress.attempt} 次` : ""}` : sold ? "已售罄" : canNow ? "兑换" : "即将开启";
  const nowTitle = exchanging ? "正在发送兑换请求" : sold ? "商品已售罄" : canNow ? "立即发送兑换请求" : "商品还未开启兑换";
  const image = good.icon ? `<img src="${escapeAttr(good.icon)}" alt="${escapeAttr(good.goods_name)}" loading="lazy" />` : `<div class="shop-image-fallback">无图</div>`;
  return `<article class="shop-good ${sold ? "is-sold-out" : ""}" data-shop-good="${index}">
    <div class="shop-good-image">${image}</div>
    <div class="shop-good-main"><div class="shop-good-title"><strong>${escapeHtml(good.goods_name)}</strong></div><div class="shop-good-meta"><span>${good.display_status === "sold_out_with_next" ? "下次兑换" : "兑换"} ${escapeHtml(good.exchange_time || "-")}</span><span class="${sold ? "sold-out" : ""}">${sold ? "已售罄" : `库存 ${escapeHtml(String(good.stock ?? "-"))}`}</span><span>${escapeHtml(String(good.price ?? 0))} 米游币</span><span>${escapeHtml(good.limit || "-")}</span></div></div>
    <div class="shop-good-actions"><button class="ghost" type="button" data-shop-add="${index}" title="${canAdd ? "加入兑换计划" : "商品已售罄"}" ${canAdd ? "" : "disabled"}><svg><use href="#i-plus"></use></svg><span>计划</span></button><button class="primary ${exchanging ? "is-loading" : ""}" type="button" data-shop-now="${index}" title="${nowTitle}" ${canNow && !exchanging ? "" : "disabled"}><svg><use href="#i-play"></use></svg><span>${nowText}</span></button></div></article>`;
}
function getVisiblePages(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = [1];
  const left = Math.max(2, current - 2), right = Math.min(total - 1, current + 2);
  if (left > 2) pages.push("...");
  for (let i = left; i <= right; i++) pages.push(i);
  if (right < total - 1) pages.push("...");
  pages.push(total);
  return pages;
}
function renderShopPagination() {
  let pager = $("shopPagination");
  if (!pager && $("shopGoods")) {
    pager = document.createElement("div"); pager.id = "shopPagination"; pager.className = "shop-pagination";
    $("shopGoods").after(pager);
  }
  if (!pager) return;
  const total = shopGoodsLoading ? 0 : Math.ceil(getFilteredGoods().length / SHOP_PAGE_SIZE);
  pager.style.display = total > 1 ? "flex" : "none";
  if (total <= 1) { pager.innerHTML = ""; return; }
  const current = shopCurrentPage;
  const arrow = (d) => `<svg width="10" height="10" viewBox="0 0 10 10"><path d="${d}" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>`;
  pager.innerHTML = `<button class="ghost page-btn" data-page="prev" ${current <= 1 ? "disabled" : ""}>${arrow("M7 1L3 5l4 4")}</button>` +
    getVisiblePages(current, total).map((p) => p === "..." ? `<span class="page-ellipsis">…</span>` : `<button class="ghost page-btn ${p === current ? "is-active" : ""}" data-page="${p}">${p}</button>`).join("") +
    `<button class="ghost page-btn" data-page="next" ${current >= total ? "disabled" : ""}>${arrow("M3 1l4 4-4 4")}</button><span class="page-info">${current} / ${total}</span>`;
}
async function loadShopGoods() {
  shopSelectedGame = $("shopGameFilter")?.value ?? shopSelectedGame;
  const seq = ++shopGoodsLoadSeq;
  shopGoodsLoading = true;
  renderShopGoods();
  try {
    const data = await api(`/api/shop/goods?game=${encodeURIComponent(shopSelectedGame)}`);
    if (seq !== shopGoodsLoadSeq) return;
    shopGoods = data.goods || [];
    shopDetailCache.clear();
    if (data.games?.length) shopGames = data.games;
    renderShopGameFilter();
  } finally {
    if (seq === shopGoodsLoadSeq) { shopGoodsLoading = false; renderShopGoods(); }
  }
}
// 缓存中保留进行中的请求，同账号的多条计划共用一次查询。
function shopCached(cache, key, load, ttl = 60000) {
  const cached = cache.get(key);
  if (cached && cached.expires > Date.now()) return cached.promise;
  const entry = { expires: Date.now() + ttl, promise: null };
  entry.promise = Promise.resolve().then(load).catch((error) => { if (cache.get(key) === entry) cache.delete(key); throw error; });
  cache.set(key, entry);
  return entry.promise;
}
function shopAccountMeta(accountIndex, gameBiz = "") {
  const account = config?.accounts?.[accountIndex];
  if (!account?.stuid || isOverseas(account)) return Promise.reject(new Error("请选择已登录的国服账号"));
  return shopCached(shopMetaCache, `${account.stuid}:${gameBiz}`, () => api(`/api/shop/account-meta?account_index=${accountIndex}&game_biz=${encodeURIComponent(gameBiz)}`));
}
function shopCachedMeta(plan) {
  const account = config?.accounts?.[shopPlanAccountIndex(plan)];
  return shopMetaCache.get(`${account?.stuid}:${Number(plan.type) === 2 ? plan.game_biz || "" : ""}`)?.value;
}
async function loadShopPlanMeta(plan) {
  const index = shopPlanAccountIndex(plan);
  const biz = Number(plan.type) === 2 ? plan.game_biz || "" : "";
  const stuid = String(config.accounts[index]?.stuid || "");
  const meta = await shopAccountMeta(index, biz);
  const entry = shopMetaCache.get(`${stuid}:${biz}`);
  if (entry) entry.value = meta;
  return meta;
}
async function loadAllPlanAddresses() {
  await shopMapLimit(shopPlans(), (p) => loadShopPlanMeta(p).catch(() => null));
  if (typeof activeView !== "undefined" && activeView === "shop") renderShopPlans(false);
}
function buildAddressOptions(addresses, selectedId) {
  return `<option value="">请选择收货地址</option>` +
    (selectedId && !addresses.some((a) => String(a.id) === String(selectedId)) ? `<option value="${escapeAttr(selectedId)}" selected>原地址 ${escapeHtml(selectedId)}（需核实）</option>` : "") +
    addresses.map((a) => `<option value="${escapeAttr(a.id)}" ${String(a.id) === String(selectedId) ? "selected" : ""}>${escapeHtml([a.name, a.address].filter(Boolean).join(" · ") || a.id)}</option>`).join("");
}
function shopPlanAddressSelectHtml(plan) { return buildAddressOptions(shopCachedMeta(plan)?.addresses || [], plan.address_id || ""); }
function shopRoleOptions(plan) {
  const roles = shopCachedMeta(plan)?.roles || [];
  return `<option value="">请选择游戏角色</option>` + (!roles.some((r) => r.uid === plan.uid && r.region === plan.region) && plan.uid ? `<option value="current" selected>${escapeHtml(shopRoleDisplay(plan))}</option>` : "") +
    roles.map((r, i) => `<option value="${i}" ${r.uid === plan.uid && r.region === plan.region ? "selected" : ""}>${escapeHtml([r.nickname, r.uid, r.region_name].filter(Boolean).join(" / "))}</option>`).join("");
}
function shopRoleDisplay(plan) { return [plan.role_name, plan.uid].filter(Boolean).join(" / ") || "未选择角色"; }
function shopServerDisplay(plan) { return [plan.region_name || plan.region, plan.game_biz].filter(Boolean).join(" / ") || "不需要"; }
function shopBalance(meta) {
  const points = meta?.points;
  for (const key of ["points", "point", "total_points", "balance"]) {
    if (points?.[key] !== undefined && points[key] !== null && points[key] !== "" && Number.isFinite(Number(points[key]))) return Number(points[key]);
  }
  return null;
}
function shopMetaLoginError(meta) { return [meta.points_error, meta.addresses_error, meta.roles_error].find((s) => /未登录|登录.*失效|登录.*过期|cookie.*过期|expired/i.test(s || "")); }
function assignShopRole(plan, role) {
  plan.uid = role?.uid || ""; plan.region = role?.region || "";
  plan.role_name = role?.nickname || ""; plan.region_name = role?.region_name || "";
}
function applyShopAccountBinding(target, source) {
  for (const key of ["account_index", "account_stuid", "address_id", "uid", "region", "role_name", "region_name"]) target[key] = source[key];
}
async function bindShopPlanAccount(plan, index) {
  const account = config.accounts[index];
  if (!account?.cookie || !account.stuid || isOverseas(account)) throw new Error("请选择已登录的国服账号");
  const draft = { ...plan, account_index: index, account_stuid: String(account.stuid), address_id: "" };
  assignShopRole(draft, null);
  const meta = await loadShopPlanMeta(draft);
  const currentIndex = shopPlanAccountIndex(draft);
  if (currentIndex < 0) throw new Error("执行账号已删除，请重新选择");
  draft.account_index = currentIndex;
  const expired = shopMetaLoginError(meta);
  if (expired) throw new Error(`登录已失效：${expired}`);
  if (Number(draft.type) === 2) {
    if (!meta.roles?.length) throw new Error("该账号没有商品对应的绑定角色");
    assignShopRole(draft, meta.roles[0]);
  } else {
    if (Number(draft.type) === 1 && meta.addresses_error) throw new Error(`地址获取失败：${meta.addresses_error}`);
    draft.address_id = String(meta.addresses?.[0]?.id || "");
  }
  return draft;
}
async function buildShopPlan(good, accountIndex, exchangeAt = null) {
  const accountStuid = String(config.accounts[accountIndex]?.stuid || "");
  if (!accountStuid) throw new Error("请选择已登录的国服账号");
  const [detail, fp] = await Promise.all([
    shopCached(shopDetailCache, String(good.goods_id), () => api(`/api/shop/good-detail?goods_id=${encodeURIComponent(good.goods_id)}`)),
    shopCached(shopDetailCache, `device-fp:${config?.device?.id || ""}`, () => api("/api/shop/device-fp")),
  ]);
  const base = { ...good, ...detail };
  const at = exchangeAt ?? Number(base.exchange_timestamp || 0);
  const plan = { id: globalThis.crypto?.randomUUID?.() || `p${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`,
    enable: true, auto: true, account_index: accountIndex, account_stuid: String(config.accounts[accountIndex]?.stuid || ""),
    goods_id: String(base.goods_id || good.goods_id), goods_name: base.goods_name, icon: base.icon || "", price: base.price,
    stock: base.stock, type: Number(base.type || 0), exchange_at: at, game: base.game || "", game_biz: base.game_biz || "",
    device_fp: fp.device_fp || "", uid: "", region: "", role_name: "", region_name: "", address_id: "", last_result: "", last_ok: null, last_attempt_key: "", last_run: "" };
  if (plan.type === 2 && !plan.game_biz) throw new Error("商品详情缺少 game_biz，无法匹配游戏角色");
  const currentIndex = config.accounts.findIndex((a) => !isOverseas(a) && String(a.stuid || "") === accountStuid);
  return bindShopPlanAccount(plan, currentIndex);
}
function shopPlanDuplicateKey(plan) {
  return JSON.stringify([String(plan.goods_id), String(plan.account_stuid || config?.accounts?.[plan.account_index]?.stuid || ""), Number(plan.exchange_at || 0)]);
}
// 提交失败时保留弹窗和输入；关闭后把焦点还给打开弹窗的按钮。
function shopDialog(title, content, confirmText, onConfirm, setup = null) {
  if (shopDialogOpen) return Promise.resolve(null);
  shopDialogOpen = true;
  return new Promise((resolve) => {
    const previous = document.activeElement;
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `<div class="modal-card shop-dialog" role="dialog" aria-modal="true" aria-labelledby="shopDialogTitle"><div class="modal-head"><h2 id="shopDialogTitle">${escapeHtml(title)}</h2><button class="ghost icon-only" data-modal-cancel aria-label="关闭"><svg><use href="#i-x"></use></svg></button></div>${content}<p class="shop-dialog-feedback" role="status" aria-live="polite"></p><div class="modal-actions"><button class="ghost" data-modal-cancel>取消</button><button class="primary" data-modal-confirm>${escapeHtml(confirmText)}</button></div></div>`;
    let busy = false, closed = false;
    const finish = (value) => { if (closed || busy) return; closed = true; shopDialogOpen = false; overlay.remove(); previous?.focus?.(); resolve(value); };
    document.body.append(overlay);
    overlay.querySelectorAll("[data-modal-cancel]").forEach((el) => el.addEventListener("click", () => finish(null)));
    overlay.addEventListener("click", (event) => { if (event.target === overlay) finish(null); });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(null);
      if (event.key !== "Tab") return;
      const elements = [...overlay.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]')];
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
    const submit = overlay.querySelector("[data-modal-confirm]");
    overlay.querySelector(".shop-dialog").addEventListener("change", () => { if (!busy) overlay.querySelector(".shop-dialog-feedback").textContent = ""; });
    submit.addEventListener("click", async () => {
      if (busy) return;
      busy = true; submit.disabled = true;
      const feedback = overlay.querySelector(".shop-dialog-feedback");
      feedback.textContent = "正在处理…";
      try {
        const result = await onConfirm(overlay, feedback);
        busy = false;
        finish(result);
      } catch (error) { feedback.textContent = error.message; busy = false; submit.disabled = false; }
    });
    overlay.querySelector("input, select, [data-modal-confirm]")?.focus();
    if (setup) setup(overlay);
  });
}
function shopConfirm(title, message, action = "确认") {
  return shopDialog(title, `<p>${escapeHtml(message)}</p>`, action, async () => true);
}
function shopResetRound(plan, at) {
  if (Number(plan.exchange_at || 0) !== at) { plan.exchange_at = at; plan.last_result = ""; plan.last_ok = null; plan.last_run = ""; }
}
async function saveShopChanges(message = "兑换计划已保存") {
  markShopDirty();
  renderShopPlans();
  try { await autoSaveConfig(); }
  finally { updateShopSelection(); }
  showToast(message, "ok");
}
async function addShopPlan(good) { return addShopPlans([good]); }
async function addShopPlans(goods) {
  goods = goods.filter((g) => g && canShopGoodAddPlan(g));
  const choices = loggedInAccountChoices();
  if (!goods.length) throw new Error("请选择可以加入计划的商品");
  if (!choices.length) throw new Error("请先添加并登录国服账号");
  const title = `添加兑换计划 · ${goods.length} 件商品`;
  const content = `<p class="shop-inline-note">为选中的账号分别建立计划。实物默认使用账号第一个收货地址，虚拟商品默认使用第一个绑定角色，添加后可在计划配置中调整。</p>
    <div class="shop-dialog-accounts">${choices.map(({ account, index }) => `<label class="check-row"><input type="checkbox" data-add-account="${escapeAttr(account.stuid)}" ${choices.length === 1 ? "checked" : ""}><span>${escapeHtml(accountLabel(account))}</span><small class="shop-balance" data-balance="${index}">余额获取中</small></label>`).join("")}</div>
    <div class="shop-dialog-goods">${goods.map((g, i) => `<label><span>${escapeHtml(g.goods_name)} · ${escapeHtml(String(g.price ?? "-"))} 米游币</span><input type="datetime-local" step="1" data-add-time="${i}" value="${escapeAttr(Number(g.exchange_timestamp) > shopNow() ? timestampToLocalInput(g.exchange_timestamp) : "")}"></label>`).join("")}</div><p class="shop-inline-note">以上时间均为北京时间。没有公布开售时间的商品需手动设置未来时间；余额仅供参考，多个计划会分别消耗米游币。</p>`;
  const result = await shopDialog(title, content, "添加计划", async (overlay, feedback) => {
    const identities = [...overlay.querySelectorAll("[data-add-account]:checked")].map((el) => el.dataset.addAccount);
    if (!identities.length) throw new Error("请至少选择一个账号");
    const times = goods.map((g, i) => localInputToTimestamp(overlay.querySelector(`[data-add-time="${i}"]`).value));
    if (times.some((at) => at <= shopNow())) throw new Error("请为每件商品设置未来的兑换时间");
    const additions = [], errors = [];
    let skipped = 0;
    const keys = new Set(shopPlans().map(shopPlanDuplicateKey));
    for (const stuid of identities) {
      const index = config.accounts.findIndex((a) => !isOverseas(a) && String(a.stuid) === stuid);
      for (let i = 0; i < goods.length; i++) {
        const good = goods[i];
        const candidate = { goods_id: good.goods_id, account_stuid: stuid, exchange_at: times[i] };
        if (keys.has(shopPlanDuplicateKey(candidate))) { skipped += 1; continue; }
        feedback.textContent = `正在准备 ${good.goods_name} · ${additions.length + skipped + errors.length + 1}/${identities.length * goods.length}`;
        try {
          const plan = await buildShopPlan(good, index, times[i]);
          if (Number(plan.type) === 1 && !plan.address_id) throw new Error("请先在米游社添加收货地址");
          additions.push(plan); keys.add(shopPlanDuplicateKey(plan));
        } catch (error) { errors.push(`${good.goods_name} / ${stuid}：${error.message}`); }
      }
    }
    // 请求期间可能有别的操作添加计划，入库前再按最新列表去重。
    const currentKeys = new Set(shopPlans().map(shopPlanDuplicateKey));
    const unique = additions.filter((p) => { const key = shopPlanDuplicateKey(p); if (currentKeys.has(key)) { skipped += 1; return false; } currentKeys.add(key); return true; });
    if (!unique.length && errors.length) throw new Error(errors.join("；"));
    config.shop_exchange ||= { enable: false, plans: [] };
    config.shop_exchange.plans ||= [];
    config.shop_exchange.plans.push(...unique);
    if (unique.length) {
      markShopDirty();
      try { await autoSaveConfig(); }
      catch (error) { const ids = new Set(unique.map((p) => p.id)); config.shop_exchange.plans = shopPlans().filter((p) => !ids.has(p.id)); throw error; }
    }
    return { added: unique.length, skipped, errors };
  }, (overlay) => {
    choices.forEach(async ({ index }) => {
      const label = overlay.querySelector(`[data-balance="${index}"]`);
      try {
        const meta = await shopAccountMeta(index);
        const value = shopBalance(meta);
        label.textContent = shopMetaLoginError(meta) ? "登录已失效" : value === null ? "余额暂未获取" : `余额 ${value} 米游币${goods.reduce((n, g) => n + Number(g.price || 0), 0) > value ? " · 可能不足" : ""}`;
      } catch { label.textContent = "余额暂未获取"; }
    });
  });
  if (!result) return;
  renderShopPlans();
  const message = `已添加 ${result.added} 项，跳过重复 ${result.skipped} 项${result.errors.length ? `，失败 ${result.errors.length} 项：${result.errors.join("；")}` : ""}${config.shop_exchange.enable ? "" : "。自动兑换总开关已关闭，请按需开启"}`;
  showToast(message, result.errors.length ? "warn" : "ok");
}
async function exchangeGoodNow(good) {
  if (!canShopGoodExchangeNow(good)) throw new Error("商品当前不可立即兑换");
  const choices = loggedInAccountChoices();
  if (!choices.length) throw new Error("请先登录国服账号");
  const selected = await shopDialog("立即兑换", `<p>${escapeHtml(good.goods_name)} · 每次消耗 ${escapeHtml(String(good.price ?? "-"))} 米游币</p><label><span>执行账号</span><select data-exchange-account>${choices.map(({ account }) => `<option value="${escapeAttr(account.stuid)}">${escapeHtml(accountLabel(account))}</option>`).join("")}</select></label><p class="shop-inline-note">确认后立即发送兑换请求。实物使用账号第一个地址，虚拟商品使用第一个绑定角色。</p>`, "核实信息", async (overlay) => {
    const stuid = overlay.querySelector("[data-exchange-account]").value;
    const index = config.accounts.findIndex((a) => !isOverseas(a) && String(a.stuid) === stuid);
    const plan = await buildShopPlan(good, index, 0);
    const destination = Number(plan.type) === 2 ? shopRoleDisplay(plan) + " · " + shopServerDisplay(plan) :
      (shopCachedMeta(plan)?.addresses || []).find((a) => String(a.id) === plan.address_id);
    if (plan.type === 1 && !plan.address_id) throw new Error("账号没有收货地址，请先在米游社添加");
    return { plan, destination: typeof destination === "string" ? destination : [destination?.name, destination?.address].filter(Boolean).join(" · ") || "无需收货信息" };
  });
  if (selected && !await shopConfirm("核实兑换信息", `${good.goods_name} · ${accountLabel(config.accounts[shopPlanAccountIndex(selected.plan)])} · ${selected.destination}。确认后消耗 ${good.price ?? "-"} 米游币。`, "立即兑换")) return;
  if (!selected) return;
  shopExchangeNowGoodsId = String(good.goods_id); renderShopGoods();
  try { await exchangePlanNow(selected.plan); }
  finally { shopExchangeNowGoodsId = ""; renderShopGoods(); }
}
async function exchangePlanNow(planOrId, quiet = false) {
  const id = typeof planOrId === "string" ? planOrId : `adhoc:${planOrId.goods_id}:${planOrId.account_stuid || planOrId.account_index}`;
  if (shopIsRunning(id)) throw new Error("该计划正在兑换中，请稍候");
  shopPendingRuns.add(id); renderShopPlans(false);
  try {
    const response = await api("/api/shop/exchange", { method: "POST", body: JSON.stringify(typeof planOrId === "string" ? { plan_id: planOrId } : { plan: planOrId }) });
    const result = response.result || {};
    if (response.config?.shop_exchange) mergeShopRuntime(response.config.shop_exchange);
    if (!quiet) showToast(`${result.ok ? "兑换成功" : "兑换失败"}：${result.message || "未知结果"}（响应码 ${result.retcode ?? "-"}，请求 ${result.attempt || 0} 次）`, result.ok ? "ok" : "error");
    return result;
  } finally { shopPendingRuns.delete(id); await refreshStatus().catch(() => {}); renderShopPlans(false); }
}
async function runShopPlans(ids) {
  if (shopBatchRunning) throw new Error("上一批兑换尚未结束，请稍候");
  const plans = ids.map(shopPlanById).filter(Boolean);
  const ready = plans.filter((p) => !shopIsRunning(p.id));
  const invalid = ready.find((p) => !config.accounts[shopPlanAccountIndex(p)]?.cookie || (Number(p.type) === 1 && !p.address_id) || (Number(p.type) === 2 && (!p.uid || !p.region || !p.game_biz)));
  if (invalid) throw new Error(`${invalid.goods_name || invalid.goods_id} 的账号或收货信息不完整，请先点「配置」核实`);
  if (!ready.length) throw new Error("所选计划均在兑换中");
  const details = ready.map((p) => {
    const account = config.accounts[shopPlanAccountIndex(p)];
    const address = shopCachedMeta(p)?.addresses?.find((a) => String(a.id) === String(p.address_id));
    const destination = address ? [address.name, address.address].filter(Boolean).join(" · ") : `收货地址 ID：${p.address_id || "未选择"}`;
    return `<p><strong>${escapeHtml(p.goods_name || p.goods_id)}</strong> · ${escapeHtml(account ? accountLabel(account) : "账号需处理")} · ${escapeHtml(String(p.price ?? "-"))} 米游币<br><small>${escapeHtml(Number(p.type) === 2 ? shopRoleDisplay(p) + " · " + shopServerDisplay(p) : destination)}</small></p>`;
  }).join("");
  if (!await shopDialog(`立即执行 ${ready.length} 项计划`, `<div class="shop-dialog-goods">${details}</div><p>确认后立即发送请求并消耗米游币，请核实以上账号和收货信息。</p>`, "确认兑换", async () => true)) return;
  await autoSaveConfig();
  if (shopBatchRunning) throw new Error("上一批兑换尚未结束，请稍候");
  shopBatchRunning = true;
  ready.forEach((p) => shopQueuedRuns.add(p.id));
  renderShopPlans();
  let results;
  try {
    results = await shopMapLimit(ready, async (p) => {
      shopQueuedRuns.delete(p.id);
      try { const result = await exchangePlanNow(p.id, true); return { name: p.goods_name, ...result }; }
      catch (error) { return { name: p.goods_name, ok: false, message: error.message }; }
    }, 4);
  } finally { shopBatchRunning = false; ready.forEach((p) => shopQueuedRuns.delete(p.id)); renderShopPlans(false); updateShopSelection(); }
  const failed = results.filter((r) => !r.ok);
  showToast(`执行完成：成功 ${results.length - failed.length} 项，失败 ${failed.length} 项${failed.length ? `。${failed.map((r) => `${r.name}：${r.message}`).join("；")}` : ""}`, failed.length ? "warn" : "ok");
}
async function shopMapLimit(items, action, concurrency = 4) {
  let cursor = 0;
  const results = new Array(items.length);
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) { const index = cursor++; results[index] = await action(items[index], index); }
  }));
  return results;
}
async function deleteShopPlans(ids, cleanup = false) {
  const targets = new Set(ids.filter((id) => !shopIsRunning(id)));
  if (!targets.size) throw new Error("正在兑换的计划暂不能删除");
  if (!await shopConfirm(cleanup ? "清理已结束计划" : "删除兑换计划", `将删除 ${targets.size} 项计划及其页面中的执行记录。`, "确认删除")) return;
  const removed = shopPlans().filter((p) => targets.has(p.id) && !shopIsRunning(p.id));
  config.shop_exchange.plans = shopPlans().filter((p) => !removed.includes(p));
  try { await saveShopChanges("计划已删除"); }
  catch (error) {
    const existing = new Set(shopPlans().map((p) => p.id));
    config.shop_exchange.plans.push(...removed.filter((p) => !existing.has(p.id)));
    renderShopPlans();
    throw error;
  }
}
async function batchShopPlans(action) {
  const ids = [...shopSelectedPlans];
  if (action === "run") return runShopPlans(ids);
  if (action === "delete") return deleteShopPlans(ids);
  const plans = ids.map(shopPlanById).filter((p) => p && !shopIsRunning(p.id));
  if (!plans.length) throw new Error("正在兑换的计划暂不能修改");
  if (action === "enable" || action === "pause") {
    plans.forEach((p) => { p.enable = action === "enable"; if (action === "enable") p.auto = true; });
    return saveShopChanges(`已${action === "enable" ? "启用" : "暂停"} ${plans.length} 项计划${plans.some((p) => Number(p.exchange_at) <= shopNow()) ? "，已过期的计划需设置未来时间" : ""}`);
  }
  if (action === "time") {
    const originalTimes = plans.map((p) => Number(p.exchange_at || 0));
    const result = await shopDialog(`修改 ${plans.length} 项计划时间`, `<label><span>修改方式</span><select data-time-mode><option value="set">设为同一时间</option><option value="shift">按原时间平移</option></select></label><label><span>北京时间</span><input data-time-at type="datetime-local" step="1"></label><label><span>平移分钟数（负数表示提前）</span><input data-time-shift type="number" step="0.5" value="0"></label>`, "应用时间", async (overlay) => {
      const shift = overlay.querySelector("[data-time-mode]").value === "shift";
      const minutes = Number(overlay.querySelector("[data-time-shift]").value);
      const at = localInputToTimestamp(overlay.querySelector("[data-time-at]").value);
      const times = originalTimes.map((value) => shift ? value + minutes * 60 : at);
      if (times.some((t) => !Number.isFinite(t) || t <= shopNow())) throw new Error("修改后的所有时间都必须晚于当前时间");
      if (plans.some((p) => shopIsRunning(p.id))) throw new Error("有计划已开始兑换，请结束后重试");
      plans.forEach((p, i) => shopResetRound(p, Math.floor(times[i])));
      await saveShopChanges(`已修改 ${plans.length} 项计划时间`);
      return true;
    });
    return result;
  }
  if (action === "account") {
    const choices = loggedInAccountChoices();
    if (!choices.length) throw new Error("请先登录国服账号");
    await shopDialog(`更换 ${plans.length} 项计划账号`, `<label><span>执行账号</span><select data-batch-account>${choices.map(({ account }) => `<option value="${escapeAttr(account.stuid)}">${escapeHtml(accountLabel(account))}</option>`).join("")}</select></label><p>将重新匹配该账号的第一个地址或游戏角色。运行结果保留，已执行的时间不会重新触发。</p>`, "更换账号", async (overlay) => {
      const stuid = overlay.querySelector("[data-batch-account]").value;
      const index = config.accounts.findIndex((a) => !isOverseas(a) && String(a.stuid) === stuid);
      const replacements = await shopMapLimit(plans, (p) => bindShopPlanAccount(p, index));
      if (plans.some((p) => shopIsRunning(p.id))) throw new Error("有计划已开始兑换，请结束后重试");
      replacements.forEach((p) => { const live = shopPlanById(p.id); if (live) applyShopAccountBinding(live, p); });
      await saveShopChanges(`已更换 ${replacements.length} 项计划账号`);
      return true;
    });
  }
}
function mergeShopRuntime(remote) {
  if (!config || !remote) return;
  const byId = new Map((remote.plans || []).map((p) => [p.id, p]));
  shopPlans().forEach((plan) => {
    const latest = byId.get(plan.id);
    if (!latest || Number(latest.exchange_at || 0) !== Number(plan.exchange_at || 0)) return;
    if (plan.last_run && (!latest.last_run || latest.last_run < plan.last_run)) return;
    const changed = latest.last_run !== plan.last_run || latest.last_ok !== plan.last_ok;
    for (const key of ["last_result", "last_ok", "last_attempt_key", "last_run"]) if (key in latest) plan[key] = latest[key];
    if (changed && latest.last_ok === true) plan.enable = false;
  });
}
function receiveShopStatus(scheduler, remote) {
  shopScheduler = scheduler;
  shopRunningProgress = scheduler.running_progress || {};
  if (Number.isFinite(scheduler.now)) shopServerOffset = scheduler.now - Date.now() / 1000;
  mergeShopRuntime(remote);
  if ($("shopScheduleMetric")) $("shopScheduleMetric").textContent = scheduler.running_count ? `${scheduler.running_count} 项兑换中` : scheduler.enabled ? "已启用" : "已关闭";
  if ($("shopNextRun")) {
    const name = scheduler.next_goods_name || "暂无待执行计划";
    const at = Number(scheduler.next_run_ts || 0);
    $("shopNextRun").textContent = name;
    $("shopNextRun").title = at ? `${name} · ${timestampToBeijingText(at)}（北京时间）` : name;
    if ($("shopNextTime")) $("shopNextTime").innerHTML = at ? `${escapeHtml(timestampToBeijingText(at).slice(5, 16))} · <span data-shop-countdown="${at}">${escapeHtml(shopCountdown(at))}</span>` : "";
  }
  if (typeof activeView !== "undefined" && activeView === "shop") {
    renderShopPlans(false);
    document.querySelectorAll("[data-shop-plan]").forEach((row) => {
      const plan = shopPlanById(row.dataset.shopPlan);
      if (!plan) return;
      const state = shopPlanState(plan), badge = row.querySelector(".plan-badge"), result = row.querySelector(".shop-plan-result");
      if (badge) { badge.className = `plan-badge ${state.tone}`; badge.textContent = state.label; }
      if (result) { result.textContent = shopPlanStatus(plan); result.title = shopPlanStatus(plan); }
      row.querySelectorAll("[data-shop-edit], [data-shop-plan-now], [data-shop-remove]").forEach((el) => { el.disabled = shopIsRunning(plan.id); });
    });
    if (shopExchangeNowGoodsId) renderShopGoods();
  }
}
function shopPlanEditorHtml(draft, time, busy) {
  const type = Number(draft.type);
  return `<fieldset class="shop-edit-form" ${busy ? "disabled" : ""}><div class="form-grid two">
    <label><span>执行账号</span><select data-edit-field="account">${shopAccountOptions(draft)}</select></label>
    <label><span>兑换时间（北京时间）</span><input data-edit-field="time" type="datetime-local" step="1" value="${escapeAttr(time)}"></label>
    ${type === 1 ? `<label class="wide"><span>收货地址</span><select data-edit-field="address">${shopPlanAddressSelectHtml(draft)}</select></label>` : ""}
    ${type === 2 ? `<label class="wide"><span>游戏角色</span><select data-edit-field="role">${shopRoleOptions(draft)}</select></label><div class="readonly-field wide"><span>服务器</span><strong>${escapeHtml(shopServerDisplay(draft))}</strong></div>` : ""}
    <label class="check-row"><input type="checkbox" data-edit-field="enable" ${draft.enable !== false ? "checked" : ""}><span>启用该计划</span></label>
    <label class="check-row"><input type="checkbox" data-edit-field="auto" ${draft.auto !== false ? "checked" : ""}><span>到点自动执行</span></label>
  </div></fieldset>`;
}
// 改动先留在草稿里，点「保存」才一次写入计划并保存；校验或保存失败时弹窗保持打开。
async function editShopPlan(id) {
  const plan = shopPlanById(id);
  if (!plan) return;
  if (shopIsRunning(id)) throw new Error("该计划正在兑换，结束后再修改配置");
  const draft = { ...plan };
  let time = timestampToLocalInput(plan.exchange_at);
  let busy = shopPlanAccountIndex(plan) >= 0 && !shopCachedMeta(plan);
  await shopDialog("配置兑换计划", `<p class="shop-dialog-sub">${escapeHtml(plan.goods_name || plan.goods_id)} · ${escapeHtml(String(plan.price ?? "-"))} 米游币</p><div data-plan-editor></div>
    <p class="shop-inline-note">已错过或执行过的时间不会再次自动触发，需要重新执行请设置新的未来时间。</p>
    <p class="shop-inline-note">最近执行：${escapeHtml(plan.last_run || "尚未执行")} · ${escapeHtml(plan.last_result || "暂无结果")}</p>`, "保存", async () => {
    if (busy) throw new Error("正在读取账号信息，请稍候");
    const live = shopPlanById(id);
    if (!live) throw new Error("该计划已被删除");
    if (shopIsRunning(id)) throw new Error("计划已开始兑换，结束后再修改配置");
    draft.account_index = shopPlanAccountIndex(draft);
    if (draft.account_index < 0) throw new Error("请选择执行账号");
    const at = localInputToTimestamp(time);
    if (at !== Number(live.exchange_at || 0) && at <= shopNow()) throw new Error("请设置未来的兑换时间");
    if (Number(draft.type) === 1 && !draft.address_id) throw new Error("请选择收货地址");
    if (Number(draft.type) === 2 && !draft.uid) throw new Error("请选择游戏角色");
    applyShopAccountBinding(live, draft);
    live.enable = draft.enable !== false;
    live.auto = draft.auto !== false;
    shopResetRound(live, at);
    await saveShopChanges();
    return true;
  }, (overlay) => {
    const box = overlay.querySelector("[data-plan-editor]"), feedback = overlay.querySelector(".shop-dialog-feedback");
    const render = (focus = "") => { box.innerHTML = shopPlanEditorHtml(draft, time, busy); box.querySelector(`[data-edit-field="${focus}"]`)?.focus(); };
    // 账号变化要重新读取地址或角色，期间锁住表单；失败时草稿不变，下拉框回到原账号。
    const load = async (action) => {
      busy = true; render();
      try { await action(); } catch (error) { feedback.textContent = error.message; }
      busy = false; render("account");
    };
    box.addEventListener("change", (event) => {
      const field = event.target, key = field.dataset?.editField;
      if (!key || busy) return;
      if (key === "time") time = field.value;
      else if (key === "enable" || key === "auto") draft[key] = field.checked;
      else if (key === "address") draft.address_id = field.value;
      else if (key === "role") {
        if (field.value === "current") return;
        assignShopRole(draft, field.value === "" ? null : shopCachedMeta(draft)?.roles?.[Number(field.value)] ?? null);
        render("role");
      } else if (key === "account") {
        const stuid = field.selectedOptions?.[0]?.dataset.stuid;
        const index = config.accounts.findIndex((a) => !isOverseas(a) && String(a.stuid) === stuid);
        load(async () => applyShopAccountBinding(draft, await bindShopPlanAccount(draft, index)));
      }
    });
    if (busy) load(() => loadShopPlanMeta(plan));
    else { render(); box.querySelector("select")?.focus(); }
  });
}
function bindShopEvents() {
  const on = (id, name, action) => $(id)?.addEventListener(name, action);
  on("shopStatusFilter", "change", (e) => { shopFilterStatus = e.target.value; shopCurrentPage = 1; renderShopGoods(); });
  on("shopRefreshBtn", "click", () => loadShopGoods().catch(shopError));
  on("shopGameFilter", "change", () => { shopCurrentPage = 1; loadShopGoods().catch(shopError); });
  on("shopPlanSelectAll", "change", (e) => { getFilteredPlans().forEach((p) => e.target.checked ? shopSelectedPlans.add(p.id) : shopSelectedPlans.delete(p.id)); renderShopPlans(); });
  on("shopPlanFilter", "change", (e) => { shopPlanFilter = e.target.value; renderShopPlans(); });
  on("shopSaveState", "click", () => { if (shopRevision > shopSavedRevision) saveShopChanges().catch(shopError); });
  on("shopCleanupBtn", "click", () => deleteShopPlans(shopPlans().filter(shopCanCleanup).map((p) => p.id), true).catch(shopError));
  document.querySelectorAll("[data-shop-batch]").forEach((el) => el.addEventListener("click", () => batchShopPlans(el.dataset.shopBatch).catch(shopError)));
  on("shopGoods", "click", (event) => {
    const add = event.target.closest("[data-shop-add]"), now = event.target.closest("[data-shop-now]");
    if (add && !add.disabled) addShopPlan(shopGoods[Number(add.dataset.shopAdd)]).catch(shopError);
    if (now && !now.disabled) exchangeGoodNow(shopGoods[Number(now.dataset.shopNow)]).catch(shopError);
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-page]");
    if (!button || button.disabled || !button.closest("#shopPagination")) return;
    const page = button.dataset.page;
    shopCurrentPage = page === "prev" ? shopCurrentPage - 1 : page === "next" ? shopCurrentPage + 1 : Number(page);
    renderShopGoods();
    const list = $("shopGoods");
    if (list) list.scrollTop = 0;
  });
  on("shopPlans", "click", (event) => {
    const edit = event.target.closest("[data-shop-edit]"), remove = event.target.closest("[data-shop-remove]"), run = event.target.closest("[data-shop-plan-now]");
    if (edit && !edit.disabled) editShopPlan(edit.dataset.shopEdit).catch(shopError);
    if (remove && !remove.disabled) deleteShopPlans([remove.dataset.shopRemove]).catch(shopError);
    if (run && !run.disabled) runShopPlans([run.dataset.shopPlanNow]).catch(shopError);
  });
  on("shopPlans", "change", (event) => {
    const field = event.target;
    if (field.matches("[data-plan-select]")) { field.checked ? shopSelectedPlans.add(field.dataset.planSelect) : shopSelectedPlans.delete(field.dataset.planSelect); updateShopSelection(); }
  });
}
function updateShopCountdowns() {
  if (typeof activeView !== "undefined" && activeView !== "shop") return;
  document.querySelectorAll("[data-shop-countdown]").forEach((el) => { el.textContent = shopCountdown(Number(el.dataset.shopCountdown)); });
}
