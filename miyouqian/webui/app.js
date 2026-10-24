const gameOptions = [
  ["genshin", "原神"],
  ["starrail", "星穹铁道"],
  ["zzz", "绝区零"],
  ["honkai3rd", "崩坏3"],
  ["tears", "未定事件簿"],
  ["honkai2", "崩坏学园2"],
];

const cloudGameOptions = [
  ["genshin", "云原神", false, ""],
  ["zzz", "云绝区零", false, ""],
  [
    "starrail",
    "云星穹铁道",
    true,
    "云星穹铁道是版本更新赠送 600 分钟，不需要每日签到获取时长",
  ],
];

const pushChannelOptions = [
  ["pushplus", "pushplus"],
  ["serverchan", "Server酱³"],
  ["telegram", "Telegram"],
  ["dingrobot", "钉钉机器人"],
  ["feishubot", "飞书机器人"],
  ["wecombot", "企业微信机器人"],
  ["email", "邮箱"],
  ["qq", "QQ推送"],
  ["qqbot", "QQ机器人（QQ开放平台）"],
];

// 供测试断言渠道清单；应用自身不读这个导出
if (typeof globalThis !== "undefined") {
  globalThis.__myqPushChannelOptions = pushChannelOptions;
}

const captchaChannelOptions = [
  ["damagou", "打码狗(成本≈0.01元/次)"],
  ["custom", "自定义接口"],
];
const customCaptchaDocUrl = "/custom-captcha-api.md";
let customCaptchaDocText = "";

const bbsForumOptions = [
  ["5", "大别野"],
  ["2", "原神"],
  ["6", "崩坏：星穹铁道"],
  ["8", "绝区零"],
  ["1", "崩坏3"],
  ["3", "崩坏学园2"],
  ["4", "未定事件簿"],
  ["9", "崩坏：因缘精灵"]
];
const defaultBbsForums = ["5", "2"];
const bbsInteractionDisabledReason =
    "米游社改版，社区互动已无法获取米游币，待新获取方式更新~";

// 任务配置里的三个模块，和推送通道一样用按钮 + 弹窗
const taskModules = [
  ["game", "游戏社区签到"],
  ["cloud", "云游戏签到"],
  ["bbs", "米游币任务"],
];
let config = null;
let toastTimer = null;
let autoSaveTimer = null;
let isSavingConfig = false;
let lastLoginStatus = "";
let activeLoginIndex = null;
let localLoginPanel = null;
let loginCountdownTimer = null;
let loginErrorCollapseTimer = null;
let editingAccountIndex = null;
let expandedCloudAccounts = new Set();
let pushModalProvider = null; // 当前在弹窗里配置的推送通道，null 表示弹窗关闭
let pushModalEl = null;       // 弹窗遮罩层元素
let taskModalKind = null;     // 当前在弹窗里配置的任务（game / cloud / bbs）
let taskModalEl = null;
let qqBindState = null;
let qqBindTimer = null;
let qqBindTarget = "";
let qqBindRestored = false;
let editingCaptchaProviders = new Set();
let logsPinnedToBottom = true;
let activeView = "dashboard";
let shopRunningProgress = {};
let shopGoods = [];
let shopGames = [{ key: "", name: "全部分区" }];
let shopSelectedGame = "";
let shopOpenPlans = new Set();
let shopRequestInFlight = false;
let shopGoodsLoading = false;
let shopGoodsLoadSeq = 0;
let shopExchangeNowGoodsId = "";
let shopPlanAddressCache = new Map();
let shopFilterStatus = '';
let shopCurrentPage = 1;          // 当前页码，从1开始
const SHOP_PAGE_SIZE = 4;        // 每页显示商品数


const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "请求失败");
    error.status = response.status;
    error.code = data.code || "";
    error.aigis = data.aigis;
    error.data = data;
    throw error;
  }
  return data;
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2200);
}

async function loadConfig() {
  config = await api("/api/config");
  config.accounts = (config.accounts || []).map((account) => ({
    ...account,
    _draft: false,
  }));
  renderConfig();
  loadAllPlanAddresses();
}

function renderConfig() {
  $("scheduleEnable").checked = Boolean(config.schedule?.enable ?? true);
  $("scheduleTime").value = config.schedule?.time || "09:00";
  $("scheduleJitter").value = config.schedule?.jitter_minutes ?? 45;
  $("runOnStart").checked = Boolean(config.schedule?.run_on_start ?? false);

  $("captchaMaxRetries").value = config.captcha?.max_retries ?? 3;
  // 任务开关都在「任务配置」的弹窗里，这里刷新按钮和（如果开着的）弹窗内容
  renderTaskButtons();
  renderGames();
  renderCloudGames();
  renderBbsForums();
  renderPushChannels();
  renderCaptchaChannels();
  updateTaskDependencyState();
  renderTaskModalBody();
  renderAccounts();
  renderShopConfig();
}

function renderGames() {
  const host = $("gameChips");
  if (!host) return;
  const enabled = new Set(config.games?.enabled || []);
  host.innerHTML = gameOptions
    .map(
      ([key, label]) => `
        <label class="choice-toggle">
          <input type="checkbox" data-game="${key}" ${enabled.has(key) ? "checked" : ""} />
          <span>${label}</span>
        </label>
      `,
    )
    .join("");
  updateTaskDependencyState();
}

function renderCloudGames() {
  const host = $("cloudGameChips");
  if (!host) return;
  const enabled = new Set(config.cloud_games?.enabled || []);
  host.innerHTML = cloudGameOptions
    .map(([key, label, disabled, reason]) => {
      const title = reason ? ` title="${escapeAttr(reason)}"` : "";
      return `
        <label class="chip ${disabled ? "disabled" : ""}"${title}>
          <input type="checkbox" data-cloud-game="${key}" ${enabled.has(key) ? "checked" : ""} ${disabled ? 'data-cloud-game-disabled="1" disabled' : ""} />
          <span>${label}</span>
        </label>
      `;
    })
    .join("");
  updateTaskDependencyState();
}

function renderBbsForums() {
  const host = $("bbsForumChips");
  if (!host) return;
  const enabled = new Set(
      (config.bbs?.forums || defaultBbsForums).map((id) => String(id)),
  );
  host.innerHTML = bbsForumOptions
      .map(
          ([key, label]) => `
        <label class="choice-toggle">
          <input type="checkbox" data-bbs-forum="${key}" ${enabled.has(key) ? "checked" : ""} />
          <span>${label}</span>
        </label>
      `,
      )
      .join("");
  updateTaskDependencyState();
}

// 任务开关只在弹窗里存在；关掉对应开关时把下面的选项置灰
function updateTaskDependencyState() {
  const gameToggle = $("gameCheckin");
  const cloudToggle = $("cloudGameCheckin");
  const bbsToggle = $("bbsTasks");
  const bbsCheckin = $("bbsCheckin");

  if (gameToggle) {
    setTaskGroupDisabled("gameTaskGroup", "[data-game]", !gameToggle.checked);
  }
  if (cloudToggle) {
    setTaskGroupDisabled(
      "cloudGameTaskGroup",
      "[data-cloud-game]:not([data-cloud-game-disabled])",
      !cloudToggle.checked,
    );
  }
  if (bbsToggle) {
    setTaskGroupDisabled("bbsTaskGroup", "#bbsCheckin", !bbsToggle.checked);
  }
  if (bbsToggle && bbsCheckin) {
    const forumsEnabled = bbsToggle.checked && bbsCheckin.checked;
    $("bbsForumChips")?.classList.toggle("is-hidden", !forumsEnabled);
    setTaskGroupDisabled("bbsTaskGroup", "[data-bbs-forum]", !forumsEnabled);
  }

  updateAccountCloudGameInputs();
}

function setTaskGroupDisabled(groupId, selector, disabled) {
  const group = $(groupId);
  if (!group) return;
  group.classList.toggle("is-disabled", disabled);
  group.querySelectorAll(selector).forEach((input) => {
    input.disabled = disabled;
  });
}

function taskModuleLabel(kind) {
  const item = taskModules.find(([key]) => key === kind);
  return item ? item[1] : kind;
}

function taskModuleEnabled(kind) {
  if (kind === "game") return Boolean(config.features?.game_checkin ?? true);
  if (kind === "cloud") {
    return Boolean(config.features?.cloud_game_checkin ?? false);
  }
  return Boolean(config.features?.bbs_tasks ?? false);
}

function taskModuleStateText(kind) {
  if (!taskModuleEnabled(kind)) return "已关闭";
  if (kind === "game") {
    return `已启用 · ${(config.games?.enabled || []).length} 个游戏`;
  }
  if (kind === "cloud") {
    return `已启用 · ${(config.cloud_games?.enabled || []).length} 个云游戏`;
  }
  const forums = (config.bbs?.forums || defaultBbsForums).length;
  return `已启用 · ${forums} 个版块`;
}

function renderTaskButtons() {
  const host = $("taskButtons");
  if (!host) return;
  host.innerHTML = taskModules
    .map(([kind, label]) => {
      const classes = ["choice-button"];
      if (taskModuleEnabled(kind)) classes.push("is-on");
      return `
        <button class="${classes.join(" ")}" type="button" data-open-task="${kind}" title="配置${escapeAttr(label)}">
          <span class="choice-button-name">${escapeHtml(label)}</span>
          <span class="choice-button-state">${taskModuleStateText(kind)}</span>
        </button>
      `;
    })
    .join("");
  host.querySelectorAll("[data-open-task]").forEach((button) => {
    button.addEventListener("click", () => openTaskModal(button.dataset.openTask));
  });
}

function updateAccountCloudGameInputs() {
  document.querySelectorAll(".account-cloud").forEach((section) => {
    section.classList.remove("is-disabled");
  });
  document.querySelectorAll("[data-account-cloud-token]").forEach((input) => {
    const isStarrail = input.dataset.accountCloudToken === "starrail";
    input.disabled = isStarrail;
  });
}

function pushChannelLabel(provider) {
  const option = pushChannelOptions.find(([key]) => key === provider);
  return option ? option[1] : provider;
}

function pushChannelStateText(channel) {
  if (channel?.enable) return "已启用";
  return hasPushChannelConfig(channel) ? "已关闭" : "未配置";
}

function renderPushChannels() {
  const byProvider = new Map(
    (config.push?.channels || []).map((channel) => [channel.provider, channel]),
  );
  // 每个通道只占一个按钮，点开后在弹窗里填写参数
  $("pushChannels").innerHTML = pushChannelOptions
    .map(([provider, label]) => {
      const channel = byProvider.get(provider);
      const classes = ["choice-button"];
      if (channel?.enable) {
        classes.push("is-on");
      } else if (hasPushChannelConfig(channel)) {
        classes.push("is-configured");
      }
      return `
        <button class="${classes.join(" ")}" type="button" data-open-push="${provider}" title="配置${escapeAttr(label)}">
          <span class="choice-button-name">${escapeHtml(label)}</span>
          <span class="choice-button-state">${pushChannelStateText(channel)}</span>
        </button>
      `;
    })
    .join("");
  renderPushChannelModal();
  document.querySelectorAll("[data-open-push]").forEach((button) => {
    button.addEventListener("click", () =>
      openPushChannelModal(button.dataset.openPush),
    );
  });
  lockQqBotFieldsWhileBinding();
  loadQqBindState();
}

// 绑定期间会往配置里回写 OpenID 并重新拉配置，这期间不允许改字段，避免改动被覆盖
function lockQqBotFieldsWhileBinding() {
  const row = document.querySelector('[data-push-provider="qqbot"]');
  if (!row) return;
  const lock = Boolean(qqBindState?.running);
  row.querySelectorAll("[data-push-field]").forEach((field) => {
    field.disabled = lock;
  });
}

// 刷新页面时把服务端记住的绑定进度接回来，避免重复点绑定。
// 只在每次启动 / 发起绑定时查一次：这个函数会被 renderPushChannels 调用，
// 而它自己又会触发重画，不加这个标记就会无限递归。
async function loadQqBindState() {
  if (qqBindRestored) return;
  qqBindRestored = true;
  try {
    const state = await api("/api/qqbot/bind/status");
    if (!state.running) return;
    qqBindState = state;
    qqBindTarget = state.target || "";
    // 绑定进度只有 qqbot 的弹窗里能展示，恢复进度时顺手把弹窗打开
    openPushChannelModal("qqbot");
    scheduleQqBindPoll();
  } catch (error) {
    // 拿不到状态不影响其他功能，用户重新点一次绑定即可
  }
}

function bindQqBindEvents() {
  document.querySelectorAll("[data-qqbind]").forEach((button) => {
    button.addEventListener("click", () => {
      startQqBind(button.dataset.qqbind).catch((error) => showToast(error.message));
    });
  });
  document.querySelectorAll("[data-qqbind-cancel]").forEach((button) => {
    button.addEventListener("click", () => {
      cancelQqBind().catch((error) => showToast(error.message));
    });
  });
}

// ---------------------------------------------------------------------------
// 推送通道弹窗：一个通道就是一个按钮，点开后在这里填写参数并保存
// ---------------------------------------------------------------------------
function openPushChannelModal(provider) {
  if (!provider) return;
  if (pushModalEl) closePushChannelModal();
  if (taskModalEl) closeTaskModal();
  const channel = findPushChannel(provider);
  const label = pushChannelLabel(provider);
  pushModalProvider = provider;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-card choice-dialog" data-push-provider="${escapeAttr(provider)}" role="dialog" aria-modal="true" aria-labelledby="pushChannelModalTitle">
      <div class="modal-head">
        <div>
          <strong id="pushChannelModalTitle">${escapeHtml(label)}</strong>
          <p data-push-modal-state>${pushChannelStateText(channel)}</p>
        </div>
        <button class="ghost icon-only" type="button" data-push-modal-close title="关闭">
          <svg><use href="#i-x"></use></svg>
        </button>
      </div>
      <div class="push-channel-modal-flags">
        <label class="check-row push-channel-enable">
          <input type="checkbox" data-push-toggle="${escapeAttr(provider)}" ${channel?.enable ? "checked" : ""} />
          <span>启用此通道</span>
        </label>
        <label class="check-row push-channel-enable" title="所有推送通道共用这个开关">
          <input type="checkbox" data-push-error-only ${config.push?.error_only ? "checked" : ""} />
          <span>仅失败时推送</span>
        </label>
      </div>
      <div class="choice-modal-body" data-push-modal-body></div>
      <div class="modal-actions push-channel-modal-actions">
        <button class="ghost" type="button" data-push-modal-test title="只测试当前这个通道，不触发其它渠道（无需保存或启用）">
          <svg><use href="#i-play"></use></svg>
          <span>测试推送</span>
        </button>
        <div class="push-channel-modal-buttons">
          <button class="ghost" type="button" data-push-modal-close>取消</button>
          <button class="primary" type="button" data-push-modal-save>
            <svg><use href="#i-save"></use></svg>
            <span>保存</span>
          </button>
        </div>
      </div>
    </div>
  `;
  const toast = document.querySelector(".toast");
  document.body.insertBefore(overlay, toast || null);
  pushModalEl = overlay;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closePushChannelModal();
  });
  overlay.querySelectorAll("[data-push-modal-close]").forEach((button) => {
    button.addEventListener("click", () => closePushChannelModal());
  });
  overlay
    .querySelector("[data-push-modal-save]")
    .addEventListener("click", () => {
      savePushChannel().catch((error) => showToast(error.message));
    });
  overlay
    .querySelector("[data-push-modal-test]")
    .addEventListener("click", (event) => {
      testPushChannel(event.currentTarget).catch((error) =>
        showToast(error.message),
      );
    });
  overlay.querySelector("[data-push-error-only]").addEventListener("change", (event) => {
    // 这是全局开关，改完立即保存，所有弹窗里看到的都是同一个值
    config.push = config.push || {};
    config.push.error_only = event.target.checked;
    autoSaveConfig()
      .then(() => showToast(event.target.checked ? "已改为仅失败时推送" : "已改为每次都推送"))
      .catch((error) => showToast(error.message));
  });
  document.addEventListener("keydown", pushChannelModalKeydown);
  renderPushChannelModal();
  const firstField = overlay.querySelector(
    "[data-push-modal-body] input:not([type='hidden']):not([disabled])",
  );
  firstField?.focus({ preventScroll: true });
}

function pushChannelModalKeydown(event) {
  if (event.key === "Escape") closePushChannelModal();
}

function closePushChannelModal() {
  if (!pushModalEl) return;
  document.removeEventListener("keydown", pushChannelModalKeydown);
  pushModalEl.remove();
  pushModalEl = null;
  pushModalProvider = null;
}

function renderPushChannelModal() {
  if (!pushModalProvider || !pushModalEl) return;
  const provider = pushModalProvider;
  const channel = findPushChannel(provider);
  const toggle = pushModalEl.querySelector("[data-push-toggle]");
  if (toggle) toggle.checked = Boolean(channel?.enable);
  const errorOnly = pushModalEl.querySelector("[data-push-error-only]");
  if (errorOnly) errorOnly.checked = Boolean(config.push?.error_only);
  const state = pushModalEl.querySelector("[data-push-modal-state]");
  if (state) state.textContent = pushChannelStateText(channel);
  const body = pushModalEl.querySelector("[data-push-modal-body]");
  if (!body) return;
  body.innerHTML = `
    ${provider === "qqbot" ? qqBotBindPanel() : ""}
    ${pushChannelFields(provider, channel || emptyPushChannel(provider))}
  `;
  bindQqBindEvents();
  lockQqBotFieldsWhileBinding();
}

// 弹窗里填的参数只在这里写回内存配置，取消/关闭不会落盘
function syncPushChannelFromModal() {
  if (!pushModalProvider || !pushModalEl) return null;
  const card = pushModalEl.querySelector("[data-push-provider]");
  if (!card) return null;
  const provider = pushModalProvider;
  const channel = cleanPushChannel(collectPushChannel(card));
  const channels = (config.push?.channels || []).filter(
    (item) => item.provider !== provider,
  );
  if (shouldSavePushChannel(channel)) channels.push(channel);
  config.push = config.push || {};
  config.push.channels = channels;
  config.push.enable = channels.some((item) => item.enable);
  return channel;
}

// 用弹窗里当前填写的参数测这一条通道，不需要先保存，也不受启用开关影响
async function testPushChannel(button) {
  if (!pushModalProvider || !pushModalEl) return;
  const label = pushChannelLabel(pushModalProvider);
  const card = pushModalEl.querySelector("[data-push-provider]");
  if (!card) return;
  const channel = cleanPushChannel(collectPushChannel(card));
  if (!hasPushChannelConfig(channel)) {
    showToast(`请先填写${label}的参数再测试`);
    return;
  }
  if (button) button.disabled = true;
  showToast(`正在发送${label}测试消息…`);
  try {
    const response = await api("/api/push/test", {
      method: "POST",
      body: JSON.stringify({ channel }),
    });
    // 旧版服务端没有 single 字段：它会忽略 channel，把已启用的通道全测一遍
    if (response.single !== true) {
      showToast("服务端还在运行旧代码，本次测试可能触发了多个通道，请重启米游签服务");
      return;
    }
    showToast(response.result || "推送测试已完成");
  } catch (error) {
    // 旧版服务端会忽略 channel 参数，只在有启用通道时才测试
    if (String(error.message || "").includes("请先启用至少一个推送通道")) {
      throw new Error("服务端还在运行旧代码，请重启米游签服务后再测试");
    }
    throw error;
  } finally {
    if (button) button.disabled = false;
  }
}

async function savePushChannel() {
  if (!pushModalProvider || !pushModalEl) return;
  const label = pushChannelLabel(pushModalProvider);
  const before = JSON.parse(JSON.stringify(config.push?.channels || []));
  const channel = syncPushChannelFromModal();
  if (!channel) return;
  if (channel.enable && !hasPushChannelConfig(channel)) {
    // 没填参数就打开开关没有意义，回滚并提示
    config.push.channels = before;
    config.push.enable = before.some((item) => item.enable);
    showToast(`请先填写${label}的参数再启用`);
    return;
  }
  try {
    await autoSaveConfig();
  } catch (error) {
    config.push.channels = before;
    config.push.enable = before.some((item) => item.enable);
    showToast(error.message);
    return;
  }
  closePushChannelModal();
  renderPushChannels();
  showToast(channel.enable ? `${label} 已保存并启用` : `${label} 已保存`);
}

// ---------------------------------------------------------------------------
// 任务配置弹窗：游戏社区签到 / 云游戏签到 / 米游币任务
// ---------------------------------------------------------------------------
function bbsInteractionToggle(label) {
  return `
    <label class="choice-toggle is-disabled" title="${escapeAttr(bbsInteractionDisabledReason)}">
      <input type="checkbox" disabled />
      <span>${label}</span>
    </label>
  `;
}

function openTaskModal(kind) {
  if (!kind) return;
  if (taskModalEl) closeTaskModal();
  if (pushModalEl) closePushChannelModal();
  taskModalKind = kind;
  const label = taskModuleLabel(kind);
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-card choice-dialog task-modal-dialog" data-task-kind="${escapeAttr(kind)}" role="dialog" aria-modal="true" aria-labelledby="taskModalTitle">
      <div class="modal-head">
        <div>
          <strong id="taskModalTitle">${escapeHtml(label)}</strong>
          <p data-task-modal-state>${taskModuleStateText(kind)}</p>
        </div>
        <button class="ghost icon-only" type="button" data-task-modal-close title="关闭">
          <svg><use href="#i-x"></use></svg>
        </button>
      </div>
      <div class="choice-modal-body" data-task-modal-body></div>
      <div class="modal-actions">
        <button class="ghost" type="button" data-task-modal-close>取消</button>
        <button class="primary" type="button" data-task-modal-save>
          <svg><use href="#i-save"></use></svg>
          <span>保存</span>
        </button>
      </div>
    </div>
  `;
  const toast = document.querySelector(".toast");
  document.body.insertBefore(overlay, toast || null);
  taskModalEl = overlay;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeTaskModal();
  });
  overlay.querySelectorAll("[data-task-modal-close]").forEach((button) => {
    button.addEventListener("click", () => closeTaskModal());
  });
  overlay.querySelector("[data-task-modal-save]").addEventListener("click", () => {
    saveTaskModal().catch((error) => showToast(error.message));
  });
  // 开关一动，下面的选项立刻跟着置灰 / 显示
  overlay.addEventListener("change", () => updateTaskDependencyState());
  document.addEventListener("keydown", taskModalKeydown);
  renderTaskModalBody();
}

function taskModalKeydown(event) {
  if (event.key === "Escape") closeTaskModal();
}

function closeTaskModal() {
  if (!taskModalEl) return;
  document.removeEventListener("keydown", taskModalKeydown);
  taskModalEl.remove();
  taskModalEl = null;
  taskModalKind = null;
}

function renderTaskModalBody() {
  if (!taskModalKind || !taskModalEl) return;
  const kind = taskModalKind;
  const body = taskModalEl.querySelector("[data-task-modal-body]");
  if (!body) return;
  const state = taskModalEl.querySelector("[data-task-modal-state]");
  if (state) state.textContent = taskModuleStateText(kind);

  if (kind === "game") {
    body.innerHTML = `
      <label class="check-row">
        <input id="gameCheckin" type="checkbox" ${taskModuleEnabled("game") ? "checked" : ""} />
        <span>启用游戏社区签到</span>
      </label>
      <div class="task-group" id="gameTaskGroup">
        <div class="choice-toggles cols-3" id="gameChips"></div>
      </div>
    `;
    renderGames();
    return;
  }
  if (kind === "cloud") {
    body.innerHTML = `
      <label class="check-row">
        <input id="cloudGameCheckin" type="checkbox" ${taskModuleEnabled("cloud") ? "checked" : ""} />
        <span>启用云游戏签到</span>
      </label>
      <div class="task-group" id="cloudGameTaskGroup">
        <div class="chips" id="cloudGameChips"></div>
      </div>
    `;
    renderCloudGames();
    return;
  }
  body.innerHTML = `
    <label class="check-row">
      <input id="bbsTasks" type="checkbox" ${taskModuleEnabled("bbs") ? "checked" : ""} />
      <span>启用米游币任务</span>
    </label>
    <div class="task-group" id="bbsTaskGroup">
      <div class="choice-toggles cols-4">
        <label class="choice-toggle">
          <input id="bbsCheckin" type="checkbox" ${config.bbs?.checkin !== false ? "checked" : ""} />
          <span>社区签到</span>
        </label>
        ${bbsInteractionToggle("点赞")}
        ${bbsInteractionToggle("看帖")}
        ${bbsInteractionToggle("分享")}
      </div>
      <div class="choice-toggles cols-3" id="bbsForumChips"></div>
    </div>
  `;
  renderBbsForums();
}

function checkedInputValues(selector, read) {
  return Array.from(document.querySelectorAll(`${selector}:checked`)).map(read);
}

async function saveTaskModal() {
  if (!taskModalKind || !taskModalEl) return;
  const kind = taskModalKind;
  const label = taskModuleLabel(kind);
  const before = JSON.parse(
    JSON.stringify({
      features: config.features || {},
      games: config.games || {},
      cloud_games: config.cloud_games || {},
      bbs: config.bbs || {},
    }),
  );
  config.features = { ...(config.features || {}) };
  config.games = { ...(config.games || {}) };
  config.cloud_games = { ...(config.cloud_games || {}) };
  config.bbs = { ...(config.bbs || {}) };
  if (kind === "game") {
    config.features.game_checkin = Boolean($("gameCheckin")?.checked);
    config.games.enabled = checkedInputValues(
      "[data-game]",
      (input) => input.dataset.game,
    );
  } else if (kind === "cloud") {
    config.features.cloud_game_checkin = Boolean($("cloudGameCheckin")?.checked);
    config.cloud_games.enabled = checkedInputValues(
      "[data-cloud-game]",
      (input) => input.dataset.cloudGame,
    );
  } else {
    config.features.bbs_tasks = Boolean($("bbsTasks")?.checked);
    config.bbs.checkin = Boolean($("bbsCheckin")?.checked);
    config.bbs.forums = checkedInputValues(
      "[data-bbs-forum]",
      (input) => Number(input.dataset.bbsForum),
    );
    config.bbs.read = false;
    config.bbs.like = false;
    config.bbs.share = false;
  }
  try {
    await autoSaveConfig();
  } catch (error) {
    config.features = before.features;
    config.games = before.games;
    config.cloud_games = before.cloud_games;
    config.bbs = before.bbs;
    showToast(error.message);
    return;
  }
  closeTaskModal();
  renderTaskButtons();
  showToast(`${label} 已保存`);
}

function pushChannelFields(provider, channel) {
  const common = {
    token: channel.token || "",
    sendkey: channel.sendkey || "",
    uid: channel.uid || "",
    webhook: channel.webhook || "",
    plain_text: channel.plain_text ?? false,
    topic: channel.topic || "",
    chat_id: channel.chat_id || "",
    api_url: channel.api_url || "",
    secret: channel.secret || "",
    push_url: channel.push_url || "",
    access_token: channel.access_token || "",
    send_id: channel.send_id || "",
    msg_type: channel.msg_type || "",
    app_id: channel.app_id || "",
    client_secret: channel.client_secret || "",
    user_openid: channel.user_openid || "",
    group_openid: channel.group_openid || "",
    message_format: channel.message_format || "text",
    api_base: channel.api_base || "",
    smtp_host: channel.smtp_host || "",
    smtp_port: channel.smtp_port || 465,
    smtp_user: channel.smtp_user || "",
    smtp_password: channel.smtp_password || "",
    mail_from: channel.mail_from || "",
    mail_to: channel.mail_to || "",
    smtp_ssl: channel.smtp_ssl ?? true,
  };
  const field = (name, label, type = "text") => `
    <label>
      <span>${label}</span>
      <input data-push-field="${name}" type="${type}" value="${escapeAttr(common[name] || "")}" autocomplete="off" />
    </label>
  `;
  const selectBox = (name, label, options) => `
  <label>
    <span>${label}</span>
    <div class="select-wrapper">
        <select data-push-field="${name}">
            ${Object.entries(options).map(([value, text]) => `
            <option value="${escapeAttr(value)}" ${String(value) === String(common[name] || "") ? "selected" : ""}>${escapeHtml(text)}</option>
            `).join("")}
        </select>
    <svg class="select-arrow" width="12" height="8" aria-hidden="true">
        <use href="#arrow-down"/>
    </svg>
    </div>
  </label>
`;
  const checkbox = (name, label) => `
    <label class="check-row">
      <input data-push-field="${name}" type="checkbox" ${common[name] ? "checked" : ""} />
      <span>${label}</span>
    </label>
  `;  // OpenID 可以手填，也可以用下面的绑定按钮自动获取；手填时提示去哪儿找
  const openidField = (name, placeholder) => `
    <input data-push-field="${name}" type="text" value="${escapeAttr(common[name] || "")}" placeholder="${escapeAttr(placeholder)}" autocomplete="off" />
  `;
  // 和 field 不同，这里把 label、输入框、操作按钮竖着排，按钮才放得下
  const below = (label, ...content) => `
    <div class="push-field-stack">
      <span class="push-field-label">${escapeHtml(label)}</span>
      ${content.join("")}
    </div>
  `;
  const fields = {
    pushplus: [
      field("token", "Token", "password"),
      field("topic", "群组编码")
    ],
    serverchan: [
      field("sendkey", "SendKey", "password"),
      field("uid", "UID（可留空，自动从 SendKey 解析）"),
    ],
    qq: [
      field("push_url", "HTTP API", "text"),
      field("access_token", "Access Token", "text"),
      field("send_id", "Group ID / User ID", "text"),
      selectBox("msg_type", "推送方式", { group: "QQ群", private: "私信" })
    ],
    qqbot: [
      field("app_id", "AppID"),
      field("client_secret", "AppSecret", "password"),
      selectBox("message_format", "消息格式", { text: "纯文本", markdown: "Markdown" }),
      field("api_base", "接口地址（可留空）"),
      below(
          "私聊 OpenID",
          openidField("user_openid", "可手填；或点按钮后用 QQ 私聊机器人发送验证码自动获取"),
          qqBindButton("user", "绑定私聊"),
      ),
      below(
          "群 OpenID",
          openidField("group_openid", "可手填；或点按钮后把机器人拉进群、在群里 @机器人"),
          qqBindButton("group", "绑定群聊"),
      ),
    ],
    telegram: [
      field("token", "Bot Token", "password"),
      field("chat_id", "Chat ID"),
      field("api_url", "自定义 API URL (可选)"),
    ],
    dingrobot: [
      field("webhook", "Webhook", "password"),
      field("secret", "加签 Secret", "password"),
    ],
    feishubot: [field("webhook", "Webhook", "password"),field("secret", "Secret", "password")],
    wecombot: [
      field("webhook", "Webhook", "password"),
      checkbox("plain_text", "纯文本消息（兼容微信）"),
    ],
    email: [
      field("smtp_host", "SMTP 服务器"),
      field("smtp_port", "SMTP 端口", "number"),
      field("smtp_user", "邮箱账号"),
      field("smtp_password", "邮箱授权码", "password"),
      field("mail_from", "发件人"),
      field("mail_to", "收件人"),
      checkbox("smtp_ssl", "使用 SSL"),
    ],
  };


  const fieldsHtml = (fields[provider] || []).join("");
  return `<div class="push-channel-fields form-grid two compact">${fieldsHtml}</div>`;
}

// ---------------------------------------------------------------------------
// QQ 开放平台机器人：user_openid / group_openid 只能通过机器人收到消息时获取，
// 所以这里让用户先拿到验证码，再去私聊机器人或在群里 @机器人 发出来。
// ---------------------------------------------------------------------------
function qqBindButton(target, label) {
  const busy = Boolean(qqBindState?.running);
  return `
    <div class="push-field-row">
      <button class="ghost" type="button" data-qqbind="${target}" ${busy ? "disabled" : ""}>
        <svg><use href="#i-play"></use></svg>
        <span>${escapeHtml(label)}</span>
      </button>
    </div>
  `;
}

function qqBotBindPanel() {
  const state = qqBindState;
  if (!state || state.status === "idle") return "";
  const targetLabel = qqBindTarget === "group" ? "群聊" : "私聊";
  const classes = ["qq-bind-panel"];
  if (state.status === "error") classes.push("is-error");
  if (state.status === "success") classes.push("is-success");

  let body;
  if (state.status === "success") {
    body = `<span>${escapeHtml(state.message || "绑定成功")}</span>`;
    if (state.openid) {
      body += `<span>OpenID：<code>${escapeHtml(state.openid)}</code></span>`;
    }
  } else if (state.running) {
    const hint =
        qqBindTarget === "group"
            ? "把机器人拉进群，或在群里 @机器人 发送："
            : "用 QQ 私聊机器人，发送：";
    body = `<span>${escapeHtml(state.message || `正在等待${targetLabel}消息`)}<br />${hint}<code class="qq-bind-code">${escapeHtml(state.verify_code || "······")}</code></span>
      <div class="qq-bind-actions">
        <button class="ghost" type="button" data-qqbind-cancel="1">取消绑定</button>
      </div>`;
  } else {
    body = `<span>${escapeHtml(state.message || "绑定未完成")}</span>`;
  }
  return `<div class="${classes.join(" ")}">${body}</div>`;
}

async function startQqBind(target) {
  if (qqBindState?.running) {
    showToast("已有绑定正在进行，请稍候");
    return;
  }
  // 弹窗里刚填的 AppID/AppSecret 还没保存，先收进内存再校验
  syncPushChannelFromModal();
  collectConfig();
  const channel = cleanPushChannel(
      findPushChannel("qqbot") || emptyPushChannel("qqbot"),
  );
  if (!channel.app_id || !channel.client_secret) {
    throw new Error("请先填写 AppID 和 AppSecret 再绑定");
  }
  qqBindTarget = target;
  qqBindState = { running: true, status: "starting", message: "正在连接 QQ 网关", verify_code: "" };
  renderPushChannels();
  try {
    const state = await api("/api/qqbot/bind", {
      method: "POST",
      body: JSON.stringify({
        target,
        app_id: channel.app_id,
        client_secret: channel.client_secret,
        api_base: channel.api_base || "",
      }),
    });
    qqBindState = state;
    renderPushChannels();
    scheduleQqBindPoll();
  } catch (error) {
    qqBindState = { running: false, status: "error", message: error.message };
    qqBindTarget = "";
    renderPushChannels();
    showToast(error.message);
  }
}

async function cancelQqBind() {
  await api("/api/qqbot/bind/cancel", { method: "POST", body: "{}" });
  showToast("正在取消绑定");
}

function scheduleQqBindPoll() {
  clearTimeout(qqBindTimer);
  qqBindTimer = setTimeout(pollQqBind, 1200);
}

async function pollQqBind() {
  try {
    const state = await api("/api/qqbot/bind/status");
    qqBindState = state;
    if (state.running) {
      renderPushChannels();
      scheduleQqBindPoll();
      return;
    }
    finishQqBind(state);
  } catch (error) {
    qqBindState = { running: false, status: "error", message: error.message };
    finishQqBind(qqBindState);
  }
}

function finishQqBind(state) {
  clearTimeout(qqBindTimer);
  qqBindTimer = null;
  const target = state.target || qqBindTarget;
  qqBindTarget = "";
  if (state.status === "success") {
    // 服务端在绑定成功时已经把 OpenID 写进 config.yaml 了，这里重新拉一次配置，
    // 让页面显示的 AppID/AppSecret/OpenID 和磁盘上的保持一致
    loadConfig()
        .then(() => {
          renderPushChannels();
          showToast(`已绑定并保存${target === "group" ? "群聊" : "私聊"} OpenID`);
        })
        .catch((error) => {
          renderPushChannels();
          showToast(`已绑定，但刷新配置失败：${error.message}`);
        });
    return;
  }
  renderPushChannels();
  showToast(state.message || "绑定未完成");
}

function pushChannelHiddenFields(channel) {
  if (!channel) return "";
  return Object.entries(cleanPushChannel(channel))
    .filter(([key]) => key !== "provider" && key !== "enable")
    .map(
      ([key, value]) =>
        `<input data-push-field="${key}" type="hidden" value="${escapeAttr(value ?? "")}" />`,
    )
    .join("");
}

function emptyPushChannel(provider) {
  return cleanPushChannel({ provider, enable: true });
}

function findPushChannel(provider) {
  return (
    (config.push?.channels || []).find((item) => item.provider === provider) ||
    null
  );
}

function hasPushChannelConfig(channel) {
  if (!channel) return false;
  // 直接按该通道支持的字段判断，避免漏掉 sendkey 这类只在少数通道出现的键
  return pushChannelFieldNames(channel.provider).some((key) => {
    if (key === "smtp_port") return Number(channel[key] || 465) !== 465;
    if (key === "smtp_ssl") return channel[key] === false;
    if (key === "message_format") return channel[key] === "markdown";
    if (key === "plain_text") return Boolean(channel[key]);
    return String(channel[key] || "").trim();
  });
}

function pushChannelFieldNames(provider) {
  const fields = {
    pushplus: ["token", "topic"],
    serverchan: ["sendkey", "uid"],
    qq: ["push_url", "access_token", "send_id", "msg_type"],
    qqbot: ["app_id", "client_secret", "user_openid", "group_openid", "message_format", "api_base"],
    telegram: ["token", "chat_id", "api_url"],
    dingrobot: ["webhook", "secret"],
    feishubot: ["webhook", "secret"],
    wecombot: ["webhook", "plain_text"],
    email: [
      "smtp_host",
      "smtp_port",
      "smtp_user",
      "smtp_password",
      "mail_from",
      "mail_to",
      "smtp_ssl",
    ],
  };
  return fields[provider] || [];
}

function cleanPushChannel(channel) {
  const provider = channel.provider;
  const cleaned = {
    provider,
    enable: Boolean(channel.enable),
  };
  pushChannelFieldNames(provider).forEach((key) => {
    if (key === "smtp_port") {
      cleaned[key] = Number(channel[key] || 465);
    } else if (key === "smtp_ssl") {
      cleaned[key] = channel[key] === undefined ? true : Boolean(channel[key]);
    } else if (key === "plain_text") {
      cleaned[key] = Boolean(channel[key]);
    } else if (key === "message_format") {
      cleaned[key] = channel[key] === "markdown" ? "markdown" : "text";
    } else {
      cleaned[key] = String(channel[key] || "").trim();
    }
  });
  return cleaned;
}

function shouldSavePushChannel(channel) {
  if (channel.enable) return true;
  return pushChannelFieldNames(channel.provider).some((key) => {
    if (key === "smtp_ssl") return false;
    if (key === "smtp_port") return Number(channel[key] || 465) !== 465;
    // message_format 默认是 text，只有用户主动改成 markdown 才算配置过
    if (key === "message_format") return String(channel[key] || "") === "markdown";
    return String(channel[key] || "").trim();
  });
}

function renderCaptchaChannels() {
  const channels = config.captcha?.channels || [];
  const byProvider = new Map(
    channels.map((channel) => [channel.provider, channel]),
  );
  $("captchaChannels").innerHTML = captchaChannelOptions
    .map(([provider, label]) => {
      const channel = byProvider.get(provider);
      const enabled = Boolean(channel?.enable);
      const editing = editingCaptchaProviders.has(provider);
      const configured = hasCaptchaChannelConfig(channel);
      return `
        <div class="push-channel" data-captcha-provider="${provider}">
          <div class="push-channel-main">
            <label class="check-row push-channel-toggle">
              <input type="checkbox" data-captcha-toggle="${provider}" ${enabled ? "checked" : ""} />
              <span>${label}</span>
            </label>
            <div class="push-channel-actions">
              ${
                configured && !editing
                  ? `<button class="ghost icon-only" type="button" data-edit-captcha="${provider}" title="编辑${label}配置">
                      <svg><use href="#i-edit"></use></svg>
                    </button>`
                  : ""
              }
              ${
                editing
                  ? `<button class="primary" type="button" data-save-captcha="${provider}" title="保存${label}配置">
                      <svg><use href="#i-save"></use></svg>
                      <span>保存</span>
                    </button>`
                  : ""
              }
            </div>
          </div>
          ${editing ? captchaChannelFields(provider, channel || emptyCaptchaChannel(provider)) : captchaChannelHiddenFields(channel)}
          ${provider === "custom" && enabled ? customCaptchaTips() : ""}
        </div>
      `;
    })
    .join("");
  bindCaptchaChannelEvents();
}

function bindCaptchaChannelEvents() {
  document.querySelectorAll("[data-captcha-toggle]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) {
        // 同一时间只会使用一个打码渠道，选中当前渠道时取消其他渠道
        document.querySelectorAll("[data-captcha-toggle]").forEach((other) => {
          if (other !== input) other.checked = false;
        });
      }
      collectConfig();
      const provider = input.dataset.captchaToggle;
      const existingChannel = findCaptchaChannel(provider);
      if (input.checked) {
        upsertCaptchaChannel({
          ...emptyCaptchaChannel(provider),
          ...(existingChannel || {}),
          enable: true,
        });
        if (!hasCaptchaChannelConfig(existingChannel)) {
          editingCaptchaProviders.add(provider);
        } else {
          editingCaptchaProviders.delete(provider);
          autoSaveConfig()
            .then(() => showToast("验证码识别已启用"))
            .catch((error) => showToast(error.message));
        }
        renderCaptchaChannels();
        return;
      }
      upsertCaptchaChannel({
        ...emptyCaptchaChannel(provider),
        ...(existingChannel || {}),
        enable: false,
      });
      editingCaptchaProviders.delete(provider);
      renderCaptchaChannels();
      autoSaveConfig()
        .then(() => showToast("验证码识别已关闭"))
        .catch((error) => showToast(error.message));
    });
  });
  document.querySelectorAll("[data-edit-captcha]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      editingCaptchaProviders.add(button.dataset.editCaptcha);
      renderCaptchaChannels();
    });
  });
  document.querySelectorAll("[data-save-captcha]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        collectConfig();
        editingCaptchaProviders.delete(button.dataset.saveCaptcha);
        await saveConfig("验证码识别配置已保存");
      } catch (error) {
        showToast(error.message);
      }
    });
  });

  document.querySelectorAll("[data-captcha-doc-view]").forEach((button) => {
    button.addEventListener("click", () => {
      showCustomCaptchaDoc().catch((error) => showToast(error.message));
    });
  });
  document.querySelectorAll("[data-captcha-doc-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      copyCustomCaptchaDoc().catch((error) => showToast(error.message));
    });
  });
}

function customCaptchaTips() {
  return `
    <div class="captcha-tips">
      <span>自定义接口需遵循固定的请求与响应规范：GET 请求接口地址并附带 gt / challenge 参数，可选请求头 X-API-Key，统一 code / data 响应格式。</span>
      <div class="captcha-tips-actions">
        <button class="ghost" type="button" data-captcha-doc-view>查看规范</button>
        <button class="ghost" type="button" data-captcha-doc-copy>复制规范</button>
      </div>
    </div>
  `;
}

async function loadCustomCaptchaDoc() {
  if (customCaptchaDocText) return customCaptchaDocText;
  const response = await fetch(customCaptchaDocUrl, { cache: "no-cache" });
  if (!response.ok) throw new Error("规范文档加载失败");
  customCaptchaDocText = await response.text();
  return customCaptchaDocText;
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // 通过局域网 http 访问时 Clipboard API 不可用，回退到 execCommand
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;top:0;left:0;opacity:0;";
  document.body.appendChild(area);
  area.select();
  const copied = document.execCommand("copy");
  area.remove();
  if (!copied) throw new Error("复制失败，请在规范弹窗中手动选中复制");
}

async function copyCustomCaptchaDoc() {
  await copyText(await loadCustomCaptchaDoc());
  showToast("规范文档已复制");
}

async function showCustomCaptchaDoc() {
  const text = await loadCustomCaptchaDoc();
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-card captcha-doc-dialog" role="dialog" aria-modal="true" aria-labelledby="captchaDocTitle">
      <div class="modal-head">
        <div>
          <strong id="captchaDocTitle">自定义打码接口规范</strong>
          <p>对接的打码服务需按此规范提供请求与响应</p>
        </div>
        <button class="ghost icon-only" type="button" data-captcha-doc-close title="关闭">
          <svg><use href="#i-x"></use></svg>
        </button>
      </div>
      <pre class="captcha-doc-text"></pre>
      <div class="modal-actions">
        <button class="ghost" type="button" data-captcha-doc-dialog-copy>复制全文</button>
        <button class="primary" type="button" data-captcha-doc-close>关闭</button>
      </div>
    </div>
  `;
  overlay.querySelector(".captcha-doc-text").textContent = text;
  document.body.insertBefore(overlay, document.querySelector(".toast"));
  const onKeydown = (event) => {
    if (event.key === "Escape") close();
  };
  const close = () => {
    document.removeEventListener("keydown", onKeydown);
    overlay.remove();
  };
  document.addEventListener("keydown", onKeydown);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  overlay
      .querySelectorAll("[data-captcha-doc-close]")
      .forEach((button) => button.addEventListener("click", close));
  overlay
      .querySelector("[data-captcha-doc-dialog-copy]")
      .addEventListener("click", () => {
        copyCustomCaptchaDoc().catch((error) => showToast(error.message));
      });
}

function captchaChannelFields(provider, channel) {
  if (provider === "custom") {
    return `
      <div class="push-channel-fields form-grid compact">
        <label>
          <span>接口地址</span>
          <input data-captcha-field="url" type="text" placeholder="https://gt.example.com/nine" value="${escapeAttr(channel.url || "")}" autocomplete="off" />
        </label>
        <label>
          <span>API Key（选填）</span>
          <input data-captcha-field="api_key" type="password" value="${escapeAttr(channel.api_key || "")}" autocomplete="off" />
        </label>
        <input data-captcha-field="timeout" type="hidden" value="${escapeAttr(channel.timeout || 120)}" />
      </div>
    `;
  }
  if (provider !== "damagou") return "";
  return `
    <div class="push-channel-fields form-grid compact">
      <label>
        <span>UserKey</span>
        <input data-captcha-field="userkey" type="password" value="${escapeAttr(channel.userkey || "")}" autocomplete="off" />
      </label>
      <input data-captcha-field="type" type="hidden" value="${escapeAttr(channel.type || "")}" />
      <input data-captcha-field="timeout" type="hidden" value="${escapeAttr(channel.timeout || 60)}" />
    </div>
  `;
}

function captchaChannelHiddenFields(channel) {
  if (!channel) return "";
  return Object.entries(channel)
    .filter(([key]) => key !== "provider" && key !== "enable")
    .map(
      ([key, value]) =>
        `<input data-captcha-field="${key}" type="hidden" value="${escapeAttr(value ?? "")}" />`,
    )
    .join("");
}

function emptyCaptchaChannel(provider) {
  if (provider === "custom") {
    return {
      provider,
      enable: true,
      url: "",
      api_key: "",
      timeout: 120,
    };
  }
  return {
    provider,
    enable: true,
    userkey: "",
    type: "",
    timeout: 60,
  };
}

function upsertCaptchaChannel(channel) {
  config.captcha = config.captcha || {};
  config.captcha.channels = config.captcha.channels || [];
  const index = config.captcha.channels.findIndex(
    (item) => item.provider === channel.provider,
  );
  if (index === -1) {
    config.captcha.channels.push(channel);
  } else {
    config.captcha.channels[index] = {
      ...config.captcha.channels[index],
      ...channel,
    };
  }
}

function findCaptchaChannel(provider) {
  return (
    (config.captcha?.channels || []).find(
      (item) => item.provider === provider,
    ) || null
  );
}

function hasCaptchaChannelConfig(channel) {
  if (!channel) return false;
  if (channel.provider === "custom") {
    return Boolean(String(channel.url || "").trim());
  }
  return Boolean(String(channel.userkey || "").trim());
}

function renderAccounts() {
  const accounts = config.accounts || [];
  const cards = accounts
    .map((account, index) => accountCard(account, index))
    .join("");
  $("accounts").innerHTML = accounts.length
    ? `${cards}
       <button class="acc-add-card" type="button" data-add-account>
         <svg><use href="#i-plus"></use></svg>
         <span>添加账号</span>
       </button>`
    : `<div class="acc-empty">
        <svg><use href="#i-user"></use></svg>
        <strong>还没有账号</strong>
        <span>添加后可以选择扫码或验证码登录</span>
        <button class="primary" type="button" data-add-account>
          <svg><use href="#i-plus"></use></svg>
          <span>添加账号</span>
        </button>
      </div>`;

  document.querySelectorAll("[data-add-account]").forEach((button) => {
    button.addEventListener("click", addAccount);
  });
  document.querySelectorAll("[data-login]").forEach((button) => {
    button.addEventListener("click", () => {
      showLoginMethods(Number(button.dataset.login)).catch((error) =>
        showToast(error.message),
      );
    });
  });
  document.querySelectorAll("[data-edit-account]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      editingAccountIndex = Number(button.dataset.editAccount);
      renderAccounts();
      const row = document.querySelector(
        `.account-row[data-index="${editingAccountIndex}"]`,
      );
      row?.querySelector('[data-field="name"]')?.focus();
    });
  });
  document.querySelectorAll("[data-toggle-cloud]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      const index = Number(button.dataset.toggleCloud);
      if (expandedCloudAccounts.has(index)) {
        expandedCloudAccounts.delete(index);
      } else {
        expandedCloudAccounts.add(index);
      }
      renderAccounts();
    });
  });
  document.querySelectorAll("[data-cancel-account]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.cancelAccount);
      if (activeLoginIndex === index) {
        await api("/api/login/cancel", { method: "POST", body: "{}" }).catch(() => {});
        clearLoginCountdown();
        localLoginPanel = null;
        activeLoginIndex = null;
        renderLoginSlot({ running: false, status: "idle" });
      }
      if (config.accounts[index]?._draft) {
        config.accounts.splice(index, 1);
        editingAccountIndex = null;
        activeLoginIndex = null;
        clearLoginCountdown();
        localLoginPanel = null;
        expandedCloudAccounts = shiftExpandedCloudAccounts(index);
        renderAccounts();
        renderLoginSlot({ running: false, status: "idle" });
        return;
      }
      editingAccountIndex = null;
      await loadConfig();
    });
  });
  document.querySelectorAll("[data-save-account]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        editingAccountIndex = null;
        await saveConfig("账号已保存");
      } catch (error) {
        showToast(error.message);
      }
    });
  });
  document.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.remove);
      if (activeLoginIndex === index) {
        await api("/api/login/cancel", { method: "POST", body: "{}" }).catch(() => {});
        clearLoginCountdown();
        localLoginPanel = null;
        activeLoginIndex = null;
        renderLoginSlot({ running: false, status: "idle" });
      }
      const [removed] = config.accounts.splice(index, 1);
      if (editingAccountIndex === index) editingAccountIndex = null;
      if (editingAccountIndex !== null && editingAccountIndex > index)
        editingAccountIndex -= 1;
      expandedCloudAccounts = shiftExpandedCloudAccounts(index);
      renderAccounts();
      if (!removed?._draft) {
        autoSaveConfig()
          .then(refreshShopPlans)
          .then(() => showToast("账号已删除"))
          .catch((error) => showToast(error.message));
      }
    });
  });
  updateTaskDependencyState();
}

function getFilteredGoods() {
  if (shopFilterStatus === "sold_out") {
    return shopGoods.filter((good) => isShopGoodSoldOut(good));
  }
  if (shopFilterStatus === "available") {
    return shopGoods.filter(
        (good) => !isShopGoodSoldOut(good) && canShopGoodExchangeNow(good),
    );
  }
  return shopGoods;
}

function accountCard(account, index) {
  const editing = editingAccountIndex === index;
  const loggedIn = Boolean(account.stuid);
  const cloudCount = accountCloudCount(account);
  const cloudOpen = expandedCloudAccounts.has(index);
  const nameField = editing
    ? `<input class="acc-edit-input" data-field="name" type="text" maxlength="10" placeholder="最多 10 字" value="${escapeAttr(account.name || "")}" />`
    : `<span class="acc-name-text">${escapeHtml(accountLabel(account))}</span>
       <input data-field="name" type="hidden" value="${escapeAttr(account.name || "")}" />`;
  const meta = loggedIn
    ? `<span class="acc-uid">UID ${escapeHtml(account.stuid)}</span>
       <span class="acc-chip ${cloudCount ? "on" : ""}">
         <svg><use href="#i-cloud"></use></svg>${cloudCount ? `云游戏 ${cloudCount}/2` : "云游戏未配置"}
       </span>`
    : `<span>还没有登录，点「登录方式」扫码或验证码登录</span>`;
  const actions = editing
    ? `<span class="spacer"></span>
       <button class="ghost" type="button" data-cancel-account="${index}">
         <svg><use href="#i-x"></use></svg>
         <span>取消</span>
       </button>
       <button class="primary" type="button" data-save-account="${index}">
         <svg><use href="#i-save"></use></svg>
         <span>保存</span>
       </button>`
    : `<button class="${loggedIn ? "ghost" : "primary"}" type="button" data-login="${index}">
         <svg><use href="#i-phone"></use></svg>
         <span>${loggedIn ? "刷新登录" : "登录方式"}</span>
       </button>
       <button class="ghost ${cloudOpen || cloudCount ? "is-active" : ""}" type="button" data-toggle-cloud="${index}" title="云游戏签到凭证">
         <svg><use href="#i-cloud"></use></svg>
         <span>云游戏凭证</span>
       </button>
       <span class="spacer"></span>
       <button class="ghost icon-only" type="button" data-edit-account="${index}" title="编辑账号名">
         <svg><use href="#i-edit"></use></svg>
       </button>
       <button class="ghost icon-only danger" type="button" data-remove="${index}" title="删除账号">
         <svg><use href="#i-trash"></use></svg>
       </button>`;

  return `
    <article class="account-row acc-card ${editing ? "is-editing" : ""}" data-index="${index}" data-draft="${account._draft ? "1" : "0"}">
      <div class="acc-head">
        <span class="acc-avatar tone-${accountTone(account)} ${loggedIn ? "" : "is-empty"}">${escapeHtml(accountInitial(account))}</span>
        <div class="acc-body">
          <div class="acc-name">
            ${nameField}
            <span class="acc-pill ${loggedIn ? "ok" : "off"}">${loggedIn ? "已登录" : "未登录"}</span>
            ${account._draft ? `<span class="acc-pill draft">未保存</span>` : ""}
          </div>
          <div class="acc-meta">${meta}</div>
          ${editing ? `<div class="acc-hint">最多 10 个字，仅用于本地显示</div>` : ""}
        </div>
      </div>
      <div class="acc-actions">${actions}</div>
      <input data-field="stuid" type="hidden" value="${escapeAttr(account.stuid || "")}" />
      <input data-field="stoken" type="hidden" value="${escapeAttr(account.stoken || "")}" />
      <input data-field="mid" type="hidden" value="${escapeAttr(account.mid || "")}" />
      <textarea class="hidden-field" data-field="cookie">${escapeHtml(account.cookie || "")}</textarea>
      ${accountCloudGameFields(account, index)}
      <div class="account-login-slot" data-login-slot="${index}"></div>
    </article>
  `;
}

function accountInitial(account) {
  const chars = Array.from(accountLabel(account).trim());
  return (chars[0] || "?").toUpperCase();
}

function accountTone(account) {
  let hash = 0;
  for (const char of accountLabel(account)) {
    hash = (hash * 31 + char.codePointAt(0)) % 997;
  }
  return (hash % 5) + 1;
}

function accountCloudCount(account) {
  const tokens = account.cloud_games?.tokens || {};
  return ["genshin", "zzz"].filter((key) => String(tokens[key] || "").trim()).length;
}

function accountCloudGameFields(account, index) {
  const cloudGames = account.cloud_games || {};
  const tokens = cloudGames.tokens || {};
  if (!expandedCloudAccounts.has(index)) {
    return accountCloudGameHiddenFields(tokens);
  }
  const rows = cloudGameOptions
    .map(([key, label, disabled, reason]) => {
      const title = reason ? ` title="${escapeAttr(reason)}"` : "";
      const placeholder = disabled ? "不可配置" : "x-rpc-combo_token";
      return `
        <label class="cloud-token-row ${disabled ? "disabled" : ""}"${title}>
          <span>${label}</span>
          <input data-account-cloud-token="${key}" type="password" value="${escapeAttr(tokens[key] || "")}" placeholder="${placeholder}" autocomplete="off" data-autosave ${disabled ? "disabled" : ""} />
        </label>
      `;
    })
    .join("");
  return `
    <div class="account-cloud">
      <div class="account-subhead">
        <strong>云游戏签到</strong>
        <small>从云游戏网页请求头复制 X-Rpc-Combo_token</small>
      </div>
      <div class="cloud-token-list">${rows}</div>
    </div>
  `;
}

function accountCloudGameHiddenFields(tokens) {
  return `
    <input data-account-cloud-token="genshin" type="hidden" value="${escapeAttr(tokens.genshin || "")}" />
    <input data-account-cloud-token="zzz" type="hidden" value="${escapeAttr(tokens.zzz || "")}" />
  `;
}

function shiftExpandedCloudAccounts(removedIndex) {
  const shifted = new Set();
  expandedCloudAccounts.forEach((index) => {
    if (index < removedIndex) shifted.add(index);
    if (index > removedIndex) shifted.add(index - 1);
  });
  return shifted;
}

function collectConfig() {
  config.schedule = {
    enable: $("scheduleEnable").checked,
    time: $("scheduleTime").value || "09:00",
    jitter_minutes: Number($("scheduleJitter").value || 0),
    run_on_start: $("runOnStart").checked,
  };
  // 任务开关和游戏 / 版块选择都在「任务配置」弹窗里保存时写回，这里保持内存值
  config.features = config.features || {};
  config.games = config.games || {};
  config.cloud_games = config.cloud_games || {};
  config.bbs = {
    ...(config.bbs || {}),
    read: false,
    like: false,
    share: false,
  };
  // 「仅失败时推送」在通道弹窗里改，值直接维护在 config 上，不再从 DOM 读
  config.push = config.push || {};
  // 通道参数在弹窗里编辑、保存时写回内存，这里只做规整和过滤，
  // 不能从 DOM 重建，否则弹窗外的通道会被整条丢掉
  config.push.channels = (config.push.channels || [])
    .map((channel) => cleanPushChannel(channel))
    .filter((channel) => shouldSavePushChannel(channel));
  config.push.enable = config.push.channels.some((channel) => channel.enable);
  config.captcha = {
    ...(config.captcha || {}),
    max_retries: Number($("captchaMaxRetries").value || 3),
  };
  config.captcha.channels = Array.from(
    document.querySelectorAll("[data-captcha-provider]"),
  )
    .map((row) => collectCaptchaChannel(row))
    .filter(Boolean);
  config.captcha.enable = config.captcha.channels.some(
    (channel) => channel.enable,
  );
  config.shop_exchange = collectShopExchange();
  config.accounts = Array.from(document.querySelectorAll(".account-row")).map(
    (row) => {
      const item = {};
      row.querySelectorAll("[data-field]").forEach((field) => {
        item[field.dataset.field] = field.value.trim();
      });
      item.cloud_games = collectAccountCloudGames(row);
      item.name = (item.name || "").slice(0, 10);
      item._draft = row.dataset.draft === "1";
      return item;
    },
  );
  return config;
}

function collectPushChannel(row) {
  const toggle = row.querySelector("[data-push-toggle]");
  const provider = row.dataset.pushProvider;
  const channel = emptyPushChannel(provider);
  channel.enable = Boolean(toggle ?.checked);
  row.querySelectorAll("[data-push-field]").forEach((field) => {
    if (["smtp_ssl", "plain_text"].includes(field.dataset.pushField)) {
      channel[field.dataset.pushField] = field.type === "checkbox" ? field.checked: field.value === "true";
  } else if (field.type === "checkbox") {
    channel[field.dataset.pushField] = field.checked;
  } else if (field.tagName === "SELECT") {
    channel[field.dataset.pushField] = field.value;
  } else if (field.dataset.pushField === "smtp_port") {
    channel.smtp_port = Number(field.value || 465);
  } else {
    channel[field.dataset.pushField] = field.value.trim();
  }
});
  return channel;
}

function collectCaptchaChannel(row) {
  const toggle = row.querySelector("[data-captcha-toggle]");
  const provider = row.dataset.captchaProvider;
  const channel = emptyCaptchaChannel(provider);
  channel.enable = Boolean(toggle?.checked);
  row.querySelectorAll("[data-captcha-field]").forEach((field) => {
    if (field.dataset.captchaField === "timeout") {
      channel.timeout = Number(field.value || channel.timeout);
    } else {
      channel[field.dataset.captchaField] = field.value.trim();
    }
  });
  return channel;
}

function collectAccountCloudGames(row) {
  const tokens = {};
  row.querySelectorAll("[data-account-cloud-token]").forEach((field) => {
    tokens[field.dataset.accountCloudToken] = field.value.trim();
  });
  return {
    tokens: {
      genshin: tokens.genshin || "",
      zzz: tokens.zzz || "",
    },
  };
}

function renderShopConfig() {
  if (!$("shopEnable")) return;
  const shop = config.shop_exchange || {};
  $("shopEnable").checked = Boolean(shop.enable ?? false);
  $("shopRetrySeconds").value = shop.retry_seconds ?? 20;
  $("shopRetryInterval").value = shop.retry_interval ?? 0.4;
  $("shopPush").checked = Boolean(shop.push ?? false);
  if ($("shopGoodsMetric")) {
    const total = shopGoods.length;
    const totalPages = Math.max(1, Math.ceil(total / SHOP_PAGE_SIZE));
    $("shopGoodsMetric").textContent = shopGoodsLoading
        ? "加载中"
        : `${total} 件`;
  }
  if ($("shopPlansMetric"))
    $("shopPlansMetric").textContent = String((shop.plans || []).length);
  renderShopGameFilter();
  renderShopGoods();
  renderShopGoodsLoadingState();
  renderShopPlans();
}

function renderShopGameFilter() {
  const select = $("shopGameFilter");
  if (!select) return;
  select.innerHTML = shopGames
    .map(
      (game) =>
        `<option value="${escapeAttr(game.key)}" ${game.key === shopSelectedGame ? "selected" : ""}>${escapeHtml(game.name)}</option>`,
    )
    .join("");
}

function renderShopGoodsLoadingState() {
  const select = $("shopGameFilter");
  const button = $("shopRefreshBtn");
  if (select) select.disabled = shopGoodsLoading;
  if (!button) return;
  const label = button.querySelector("span");
  button.disabled = shopGoodsLoading;
  button.classList.toggle("is-loading", shopGoodsLoading);
  if (label) label.textContent = shopGoodsLoading ? "加载中" : "刷新商品";
}
function renderShopGoods() {
  const list = $("shopGoods");
  if (!list) return;

  if (shopGoodsLoading) {
    list.innerHTML = `<div class="empty-state shop-empty shop-loading">
        <span class="qr-loading" aria-hidden="true"></span>
        <strong>商品加载中</strong>
        <span>正在获取商品图片、兑换时间、库存和限购信息。</span>
      </div>`;
    renderShopPagination();
    return;
  }

  const filtered = getFilteredGoods();
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / SHOP_PAGE_SIZE));
  if (shopCurrentPage > totalPages) shopCurrentPage = totalPages;

  const start = (shopCurrentPage - 1) * SHOP_PAGE_SIZE;
  const pageGoods = filtered.slice(start, start + SHOP_PAGE_SIZE);

  if (pageGoods.length) {
    list.innerHTML = pageGoods
        .map((good) => shopGoodCard(good, shopGoods.indexOf(good)))  // 全局索引
        .join("");
  } else {
    list.innerHTML = `<div class="empty-state shop-empty">
        <strong>暂无商品数据</strong>
        <span>${shopFilterStatus ? "当前筛选条件下没有商品。" : "点击刷新商品后，会显示兑换时间、库存、价格和图片。"}</span>
      </div>`;
  }

  bindShopGoodsEvents();
  renderShopPagination();
}
function renderShopPagination(){
  let container = $("shopPagination");
  const list = $("shopGoods");

  if (!container && list) {
    container = document.createElement("div");
    container.id = "shopPagination";
    container.className = "shop-pagination";
    list.parentNode.insertBefore(container, list.nextSibling);
  }
  if (!container) return;

  // 加载中或筛选后不足一页 / 无数据 → 隐藏分页
  const filtered = shopGoodsLoading ? [] : getFilteredGoods();
  if (filtered.length <= SHOP_PAGE_SIZE) {
    container.innerHTML = "";
    container.style.display = "none";
    return;
  }
  container.style.display = "flex";

  const total = Math.max(1, Math.ceil(filtered.length / SHOP_PAGE_SIZE));
  if (shopCurrentPage > total) shopCurrentPage = total;
  if (shopCurrentPage < 1) shopCurrentPage = 1;
  const current = shopCurrentPage;

  let html = `
    <button class="ghost page-btn" data-page="prev" ${current <= 1 ? 'disabled' : ''}>
      <svg width="10" height="10" viewBox="0 0 10 10"><path d="M7 1L3 5l4 4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>
    </button>
  `;

  const pages = getVisiblePages(current, total);
  for (const p of pages) {
    if (p === "...") {
      html += `<span class="page-ellipsis">…</span>`;
    } else {
      html += `<button class="ghost page-btn ${p === current ? 'is-active' : ''}" data-page="${p}">${p}</button>`;
    }
  }

  html += `
    <button class="ghost page-btn" data-page="next" ${current >= total ? 'disabled' : ''}>
      <svg width="10" height="10" viewBox="0 0 10 10"><path d="M3 1l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>
    </button>
    <span class="page-info">${current} / ${total}</span>
  `;

  container.innerHTML = html;

  container.querySelectorAll("[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const page = btn.dataset.page;
      if (page === "prev" && current > 1) {
        shopCurrentPage = current - 1;
      } else if (page === "next" && current < total) {
        shopCurrentPage = current + 1;
      } else if (page !== "prev" && page !== "next") {
        shopCurrentPage = Number(page);
      } else {
        return;
      }
      renderShopGoods();
      const listEl = $("shopGoods");
      if (listEl) listEl.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}
// 辅助函数：计算可见页码列表
function getVisiblePages(current, total) {
  const maxVisible = 7;  // 最多显示7个页码
  const pages = [];

  if (total <= maxVisible) {
    for (let i = 1; i <= total; i++) pages.push(i);
    return pages;
  }

  pages.push(1);
  let left = Math.max(2, current - 2);
  let right = Math.min(total - 1, current + 2);

  if (left > 2) pages.push("...");
  for (let i = left; i <= right; i++) pages.push(i);
  if (right < total - 1) pages.push("...");
  pages.push(total);

  return pages;
}

function shopGoodCard(good, index) {
  const soldOut = isShopGoodSoldOut(good);
  const canAddPlan = canShopGoodAddPlan(good);
  const exchangeNow = canShopGoodExchangeNow(good);
  const exchanging = shopExchangeNowGoodsId === String(good.goods_id || "");
  const exchangeLabel =
    good.display_status === "sold_out_with_next" ? "下次兑换" : "兑换";
  const exchangeButtonText = exchanging
    ? "兑换中"
    : soldOut
      ? "已售罄"
      : exchangeNow
        ? "兑换"
        : "即将开启";
  const exchangeButtonTitle = exchanging
    ? "正在发送兑换请求"
    : soldOut
      ? "商品已售罄"
      : exchangeNow
        ? "立即发送兑换请求"
        : "商品还未开启兑换";
  const image = good.icon
    ? `<img src="${escapeAttr(good.icon)}" alt="${escapeAttr(good.goods_name)}" loading="lazy" />`
    : `<div class="shop-image-fallback">无图</div>`;
  return `
    <article class="shop-good ${soldOut ? "is-sold-out" : ""}" data-shop-good="${index}">
      <div class="shop-good-image">${image}</div>
      <div class="shop-good-main">
        <div class="shop-good-title">
          <strong>${escapeHtml(good.goods_name)}</strong>
          ${soldOut ? "<span>已售罄</span>" : ""}
        </div>
        <div class="shop-good-meta">
          <span>${exchangeLabel} ${escapeHtml(good.exchange_time || "-")}</span>
          <span class="${soldOut ? "sold-out" : ""}">${soldOut ? "已售罄" : `库存 ${escapeHtml(good.stock || "-")}`}</span>
          <span>${escapeHtml(String(good.price ?? 0))} 米游币</span>
          <span>${escapeHtml(good.limit || "-")}</span>
        </div>
      </div>
      <div class="shop-good-actions">
        <button class="ghost" type="button" data-shop-add="${index}" title="${canAddPlan ? "加入兑换计划" : "商品已售罄"}" ${canAddPlan ? "" : "disabled"}>
          <svg><use href="#i-plus"></use></svg>
          <span>计划</span>
        </button>
        <button class="primary ${exchanging ? "is-loading" : ""}" type="button" data-shop-now="${index}" title="${exchangeButtonTitle}" ${exchangeNow && !exchanging ? "" : "disabled"}>
          <svg><use href="#i-play"></use></svg>
          <span>${exchangeButtonText}</span>
        </button>
      </div>
    </article>
  `;
}

function renderShopPlans() {
  const list = $("shopPlans");
  if (!list) return;
  document
    .querySelectorAll("details.shop-plan[open]")
    .forEach((plan) => shopOpenPlans.add(plan.dataset.shopPlan));
  const plans = config.shop_exchange?.plans || [];
  list.innerHTML = plans.length
    ? plans.map((plan, index) => shopPlanRow(plan, index)).join("")
    : `<div class="empty-state">
        <strong>暂无兑换计划</strong>
        <span>从商品列表加入计划后，可设置账号、时间和可选的收货地址或游戏角色。</span>
      </div>`;
  bindShopPlanEvents();
}
// 计划绑定的是账号的 stuid，下标只是当前列表里的位置；找不到绑定账号时返回 -1
function shopPlanAccountIndex(plan, accounts) {
  const stuid = String(plan.account_stuid || "");
  if (!stuid) return Number(plan.account_index || 0);
  return accounts.findIndex((account) => String(account.stuid || "") === stuid);
}
function shopPlanRow(plan, index) {
  const accounts = config.accounts || [];
  const paused = plan.enable === false;
  const running = Boolean(shopRunningProgress[String(index)]);
  const open = shopOpenPlans.has(String(index)) ? "open" : "";
  const roleDisplay = shopRoleDisplay(plan);
  const serverDisplay = shopServerDisplay(plan);
  const selectedAccount = shopPlanAccountIndex(plan, accounts);
  // 计划绑定的账号已不在列表里时单独占一项，不能让下拉框悄悄落到第一个账号上
  const missingOption =
      selectedAccount < 0
          ? `<option value="" data-stuid="${escapeAttr(plan.account_stuid || "")}" selected>账号已删除，请重新选择</option>`
          : "";
  const accountOptions =
      accounts.length || missingOption
          ? missingOption +
          accounts
              .map((account, accountIndex) => {
                const selected = accountIndex === selectedAccount ? "selected" : "";
                return `<option value="${accountIndex}" data-stuid="${escapeAttr(account.stuid || "")}" ${selected}>${escapeHtml(accountLabel(account))}</option>`;
              })
              .join("")
          : `<option value="0">暂无账号</option>`;
  return `
    <details class="shop-plan ${paused ? "is-paused" : ""}" data-shop-plan="${index}" ${open}>
      <summary class="shop-plan-summary">
        <span class="shop-plan-title">
          <strong>${escapeHtml(plan.goods_name || plan.goods_id)}</strong>
          <small>${escapeHtml(shopPlanStatus(plan, index))}</small>
        </span>
        <span class="shop-plan-badges">
          <span class="plan-badge ${running ? "running" : paused ? "paused" : "active"}">${running ? "兑换中" : paused ? "已暂停" : "自动"}</span>
          <span class="disclosure" aria-hidden="true"></span>
        </span>
      </summary>
      <div class="shop-plan-body">
        <div class="shop-plan-head">
          <label class="check-row">
            <input data-shop-plan-field="enable" type="checkbox" ${plan.enable !== false ? "checked" : ""} data-autosave />
            <span>启用该计划</span>
          </label>
          <button class="ghost icon-only" type="button" data-shop-remove="${index}" title="删除计划">
            <svg><use href="#i-trash"></use></svg>
          </button>
        </div>
      <div class="form-grid two compact">
        <label>
          <span>执行账号</span>
          <div class="select-wrapper">
             <select data-shop-plan-field="account_index" data-autosave>${accountOptions}</select>
             <svg class="select-arrow" width="12" height="8" aria-hidden="true">
                 <use href="#arrow-down"/>
             </svg>
          </div>
        </label>
        <label>
          <span>兑换时间</span>
          <input data-shop-plan-field="exchange_at" type="datetime-local" value="${escapeAttr(timestampToLocalInput(plan.exchange_at))}" data-autosave />
        </label>
        ${Number(plan.type || 0) !== 2 ? `
        <label>
          <span>收货地址</span>
          <div class="select-wrapper">
            <select data-shop-plan-field="address_id" data-autosave data-address-select>
                ${shopPlanAddressSelectHtml(plan)}
            </select>
             <svg class="select-arrow" width="12" height="8" aria-hidden="true">
                 <use href="#arrow-down"/>
             </svg>
          </div>
        </label>` : ""}
        <div class="readonly-field">
          <span>游戏角色</span>
          <strong>${escapeHtml(roleDisplay)}</strong>
        </div>
        <div class="readonly-field">
          <span>服务器</span>
          <strong>${escapeHtml(serverDisplay)}</strong>
        </div>
      </div>
      <input data-shop-plan-field="auto" type="hidden" value="${plan.auto === false ? "false" : "true"}" />
      <input data-shop-plan-field="goods_id" type="hidden" value="${escapeAttr(plan.goods_id || "")}" />
      <input data-shop-plan-field="goods_name" type="hidden" value="${escapeAttr(plan.goods_name || "")}" />
      <input data-shop-plan-field="icon" type="hidden" value="${escapeAttr(plan.icon || "")}" />
      <input data-shop-plan-field="price" type="hidden" value="${escapeAttr(plan.price ?? 0)}" />
      <input data-shop-plan-field="stock" type="hidden" value="${escapeAttr(plan.stock || "")}" />
      <input data-shop-plan-field="type" type="hidden" value="${escapeAttr(plan.type ?? 0)}" />
      <input data-shop-plan-field="game" type="hidden" value="${escapeAttr(plan.game || "")}" />
      <input data-shop-plan-field="device_fp" type="hidden" value="${escapeAttr(plan.device_fp || "")}" />
      <input data-shop-plan-field="uid" type="hidden" value="${escapeAttr(plan.uid || "")}" />
      <input data-shop-plan-field="region" type="hidden" value="${escapeAttr(plan.region || "")}" />
      <input data-shop-plan-field="game_biz" type="hidden" value="${escapeAttr(plan.game_biz || "")}" />
      <input data-shop-plan-field="role_name" type="hidden" value="${escapeAttr(plan.role_name || "")}" />
      <input data-shop-plan-field="region_name" type="hidden" value="${escapeAttr(plan.region_name || "")}" />
      <input data-shop-plan-field="last_result" type="hidden" value="${escapeAttr(plan.last_result || "")}" />
      <input data-shop-plan-field="last_attempt_key" type="hidden" value="${escapeAttr(plan.last_attempt_key || "")}" />
      <input data-shop-plan-field="last_run" type="hidden" value="${escapeAttr(plan.last_run || "")}" />
      <div class="shop-plan-foot">
        <span>${escapeHtml(shopPlanStatus(plan, index))}</span>
        <button class="ghost" type="button" data-shop-plan-now="${index}" title="立即执行该兑换计划">
          <svg><use href="#i-play"></use></svg>
          <span>立即兑换</span>
        </button>
      </div>
      </div>
    </details>
  `;
}

function bindShopGoodsEvents() {
  document.querySelectorAll("[data-shop-add]").forEach((button) => {
    button.addEventListener("click", () =>
      withButtonLoading(button, "添加中", () =>
        addShopPlan(shopGoods[Number(button.dataset.shopAdd)]),
      ),
    );
  });
  document.querySelectorAll("[data-shop-now]").forEach((button) => {
    button.addEventListener("click", () =>
      exchangeGoodNow(shopGoods[Number(button.dataset.shopNow)]).catch(
        (error) => showToast(error.message),
      ),
    );
  });
}

function bindShopPlanEvents() {
  document.querySelectorAll("details.shop-plan").forEach((details) => {
    details.addEventListener("toggle", () => {
      if (details.open) shopOpenPlans.add(details.dataset.shopPlan);
      else shopOpenPlans.delete(details.dataset.shopPlan);
    });
  });
  document.querySelectorAll("[data-shop-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      config.shop_exchange.plans.splice(Number(button.dataset.shopRemove), 1);
      renderShopPlans();
      autoSaveConfig()
        .then(() => showToast("兑换计划已删除"))
        .catch((error) => showToast(error.message));
    });
  });
  document.querySelectorAll("[data-shop-plan-now]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      withButtonLoading(button, "兑换中", () =>
        exchangePlanNow(Number(button.dataset.shopPlanNow)),
      );
    });
  });
  document
    .querySelectorAll('[data-shop-plan-field="account_index"]')
    .forEach((select) => {
      select.addEventListener("change", () => {
        const row = select.closest("[data-shop-plan]");
        const index = Number(row?.dataset.shopPlan);
        collectConfig();
        refreshShopPlanRole(index)
          .catch((error) => showToast(error.message))
          .then(() => refreshShopPlanAddresses(index))
          .catch((error) => showToast(error.message));
      });
    });
}

function collectShopExchange() {
  const existing = config?.shop_exchange || {};
  const shop = {
    ...(existing || {}),
    enable: Boolean($("shopEnable")?.checked ?? existing.enable ?? false),
    retry_seconds: Number(
      $("shopRetrySeconds")?.value || existing.retry_seconds || 20,
    ),
    retry_interval: Number(
      $("shopRetryInterval")?.value || existing.retry_interval || 0.4,
    ),
    push: Boolean($("shopPush")?.checked ?? existing.push ?? false),
    plans: [],
  };
  document.querySelectorAll("[data-shop-plan]").forEach((row) => {
    const plan = {};
    row.querySelectorAll("[data-shop-plan-field]").forEach((field) => {
      const key = field.dataset.shopPlanField;
      if (key === "enable") plan[key] = field.checked;
      else if (key === "account_index") {
        plan[key] = Number(field.value || 0);
        // 身份取自选项本身：下拉框渲染后账号列表可能已经变动，只看下标会指向别的账号
        plan.account_stuid = field.selectedOptions?.[0]?.dataset.stuid || "";
      } else if (key === "price") plan[key] = Number(field.value || 0);
      else if (key === "exchange_at")
        plan[key] = localInputToTimestamp(field.value);
      else if (key === "auto") plan[key] = field.value !== "false";
      else plan[key] = field.value.trim();
    });
    const accountIndex = shopPlanAccountIndex(plan, config?.accounts || []);
    if (accountIndex >= 0) plan.account_index = accountIndex;
    if (plan.goods_id) shop.plans.push(plan);
  });
  return shop;
}

async function addShopPlan(good) {
  if (!good) return;
  if (!canShopGoodAddPlan(good))
    throw new Error("商品已售罄，不能加入兑换计划");

  const accountIndex = await chooseShopPlanAccount(good);
  if (accountIndex === null) return;

  collectConfig();
  config.shop_exchange = config.shop_exchange || {
    enable: true,
    retry_seconds: 20,
    retry_interval: 0.4,
    plans: [],
  };

  if (!(config.accounts || [])[accountIndex]?.stuid) {
    throw new Error("请先添加并登录账号");
  }

  const existingIndex = config.shop_exchange.plans.findIndex(
    (p) => p.goods_id === good.goods_id && p.account_index === accountIndex,
  );

  if (existingIndex >= 0) {
    showToast("同账号已有相同计划");
    return;
  }

  const accountName = accountLabel(config.accounts[accountIndex]);
  const checkError = await checkShopAccountLogin(accountIndex);
  if (checkError) {
    showToast(`${accountName} 登录已过期，请重新登录`);
    return;
  }

  const plan = await buildShopPlan(good, accountIndex);
  config.shop_exchange.plans.push(plan);
  const planIndex = config.shop_exchange.plans.length - 1;
  renderShopPlans();
  // 只为新添加的计划加载地址并自动填充
  await refreshShopPlanAddresses(planIndex, true);
  saveConfig("已加入兑换计划").catch((error) => showToast(error.message));
}

async function loadShopGoods() {
  const game = $("shopGameFilter")?.value ?? shopSelectedGame;
  const loadSeq = ++shopGoodsLoadSeq;
  shopSelectedGame = game;
  shopGoodsLoading = true;
  shopFilterStatus = "";
  if ($("shopStatusFilter")) $("shopStatusFilter").value = "";
  renderShopConfig();
  try {
    const data = await api(`/api/shop/goods?game=${encodeURIComponent(game)}`);
    if (loadSeq !== shopGoodsLoadSeq) return;
    shopGoods = data.goods || [];
    shopCurrentPage = 1;  // ← 新增：重置页码
    if (Array.isArray(data.games) && data.games.length) {
      shopGames = data.games;
    }
    showToast("商品列表已刷新");
  } finally {
    if (loadSeq === shopGoodsLoadSeq) {
      shopGoodsLoading = false;
      renderShopConfig();
    }
  }
}

async function exchangeGoodNow(good) {
  if (!good) return;
  if (isShopGoodSoldOut(good)) throw new Error("商品已售罄，不能兑换");
  if (!canShopGoodExchangeNow(good)) throw new Error("商品还未开启兑换");
  collectConfig();
  const accountIndex = await chooseShopExchangeAccount(good);
  if (accountIndex === null) return;
  if (!(config.accounts || [])[accountIndex]?.stuid) {
    throw new Error("请先添加并登录账号");
  }
  shopRequestInFlight = true;
  shopExchangeNowGoodsId = String(good.goods_id || "");
  renderShopGoods();
  try {
    const plan = await buildShopPlan(good, accountIndex);
    await exchangePlanNow(plan);
  } finally {
    shopExchangeNowGoodsId = "";
    shopRequestInFlight = false;
    renderShopGoods();
  }
}

async function exchangePlanNow(planOrIndex) {
  const body =
    typeof planOrIndex === "number"
      ? { plan_index: planOrIndex }
      : { plan: planOrIndex };
  if (body.plan === null || body.plan === undefined)
    throw new Error("兑换计划不存在");
  const response = await api("/api/shop/exchange", {
    method: "POST",
    body: JSON.stringify(body),
  });
  const result = response.result || {};
  if (response.config) {
    config = response.config;
    config.accounts = (config.accounts || []).map((account) => ({
      ...account,
      _draft: false,
    }));
    renderConfig();
  }
  showToast(`兑换请求完成：${result.message || "未知结果"}`);
  await refreshStatus();
}

async function buildShopPlan(good, accountIndex) {
  const fpData = await api("/api/shop/device-fp");
  const detail = await api(
    `/api/shop/good-detail?goods_id=${encodeURIComponent(good.goods_id)}`,
  );
  const base = { ...good, ...detail };
  const plan = {
    enable: true,
    auto: true,
    account_index: accountIndex,
    account_stuid: String((config.accounts || [])[accountIndex]?.stuid || ""),
    goods_id: base.goods_id,
    goods_name: base.goods_name,
    icon: base.icon,
    price: base.price,
    stock: base.stock,
    type: Number(base.type || 0),
    exchange_at: base.exchange_timestamp || Math.floor(Date.now() / 1000),
    game: base.game || "",
    game_biz: base.game_biz || "",
    device_fp: fpData.device_fp || "",
    uid: "",
    region: "",
    role_name: "",
    region_name: "",
    address_id: "",
    last_result: "",
    last_attempt_key: "",
    last_run: "",
  };
  if (Number(base.type || 0) === 2) {
    if (!plan.game_biz) {
      throw new Error("商品详情缺少 game_biz，无法自动匹配游戏角色");
    }
    const meta = await api(
      `/api/shop/account-meta?account_index=${accountIndex}&game_biz=${encodeURIComponent(plan.game_biz)}`,
    );
    const role = (meta.roles || [])[0];
    if (!role) {
      throw new Error("未找到该商品对应的绑定游戏角色");
    }
    plan.uid = role.uid || "";
    plan.region = role.region || "";
    plan.role_name = role.nickname || "";
    plan.region_name = role.region_name || "";
  }
  return plan;
}

async function refreshShopPlanRole(index) {
  collectConfig();
  const plan = config.shop_exchange?.plans?.[index];
  if (!plan || !plan.game_biz) return;
  const meta = await api(
    `/api/shop/account-meta?account_index=${plan.account_index}&game_biz=${encodeURIComponent(plan.game_biz)}`,
  );
  const role = (meta.roles || [])[0];
  if (!role) {
    plan.uid = "";
    plan.region = "";
    plan.role_name = "";
    plan.region_name = "";
    renderShopPlans();
    throw new Error("当前账号未找到对应游戏角色");
  }
  plan.uid = role.uid || "";
  plan.region = role.region || "";
  plan.role_name = role.nickname || "";
  plan.region_name = role.region_name || "";
  renderShopPlans();
  await autoSaveConfig();
  showToast("游戏角色已更新");
}

async function refreshShopPlanAddresses(index, autoFill = false) {
  const plan = config.shop_exchange?.plans?.[index];
  if (!plan || Number(plan.type || 0) === 2) return;
  const accountIndex = Number(plan.account_index || 0);
  const select = document.querySelector(
    `[data-shop-plan="${index}"] [data-address-select]`,
  );
  if (!select) return;
  const currentValue = plan.address_id || "";
  select.innerHTML = `<option value="">加载中...</option>`;
  select.disabled = true;
  try {
    const meta = await api(
      `/api/shop/account-meta?account_index=${accountIndex}`,
    );
    const addresses = meta.addresses || [];
    shopPlanAddressCache.set(accountIndex, addresses);
    select.innerHTML = buildAddressOptions(addresses, currentValue);
    // 只在 autoFill=true 时自动填充第一个地址
    if (autoFill && !currentValue && addresses.length) {
      const firstId = String(addresses[0].id || "");
      select.value = firstId;
      plan.address_id = firstId;
    } else if (!autoFill && !currentValue && addresses.length) {
      // 不自动填充时，只在UI上选择第一个作为默认显示
      const firstId = String(addresses[0].id || "");
      select.value = firstId;
    } else if (currentValue && !addresses.some((a) => String(a.id) === currentValue)) {
      select.innerHTML =
        `<option value="${escapeAttr(currentValue)}">${escapeHtml(currentValue)}（已失效）</option>` +
        select.innerHTML;
      select.value = currentValue;
    }
  } catch {
    select.innerHTML = `<option value="${escapeAttr(currentValue)}">${currentValue ? escapeHtml(currentValue) : "获取地址失败"}</option>`;
  } finally {
    select.disabled = false;
  }
}

function shopPlanAddressSelectHtml(plan) {
  const accountIndex = Number(plan.account_index || 0);
  const cached = shopPlanAddressCache.get(accountIndex);
  if (!cached) return `<option value="">加载中...</option>`;
  // 不再自动修改 plan.address_id
  // 如果 plan.address_id 为空，UI上可以选择第一个，但不写入配置
  // if (!plan.address_id && cached.length) {
  //   plan.address_id = String(cached[0].id || "");
  // }
  return buildAddressOptions(cached, plan.address_id || "");
}

function buildAddressOptions(addresses, selectedId) {
  const options = [];
  for (const addr of addresses) {
    const id = String(addr.id || "");
    const label = [addr.name, addr.address].filter(Boolean).join(" - ");
    const sel = id === selectedId ? "selected" : "";
    options.push(
      `<option value="${escapeAttr(id)}" ${sel}>${escapeHtml(label || id)}</option>`,
    );
  }
  return options.join("");
}

async function loadAllPlanAddresses({ autoFill = false } = {}) {
  const plans = config.shop_exchange?.plans || [];
  const tasks = [];
  for (let i = 0; i < plans.length; i++) {
    tasks.push(refreshShopPlanAddresses(i, autoFill).catch(() => {}));
  }
  await Promise.all(tasks);
  // 只在需要自动填充时才保存配置
  if (autoFill) {
    autoSaveConfig().catch(() => {});
  }
}

function shopRoleDisplay(plan) {
  if (!plan.uid) return "不需要";
  return [plan.role_name, plan.uid].filter(Boolean).join(" / ") || plan.uid;
}

function shopServerDisplay(plan) {
  if (!plan.region && !plan.game_biz) return "不需要";
  const readable = plan.region_name
    ? `${plan.region_name}${plan.region ? ` (${plan.region})` : ""}`
    : plan.region;
  return [readable, plan.game_biz].filter(Boolean).join(" / ");
}

function isShopGoodSoldOut(good) {
  return Boolean(good?.sold_out);
}

function canShopGoodAddPlan(good) {
  if (!isShopGoodSoldOut(good)) return true;
  return good?.display_status === "sold_out_with_next";
}

function canShopGoodExchangeNow(good) {
  if (isShopGoodSoldOut(good)) return false;
  return good?.display_status === "online" || good?.display_status === "always";
}

function loggedInAccountChoices() {
  return (config.accounts || [])
    .map((account, index) => ({ account, index }))
    .filter(({ account }) => account?.stuid && account?.cookie);
}

function chooseShopExchangeAccount(good) {
  const choices = loggedInAccountChoices();
  if (!choices.length) {
    throw new Error("请先添加并登录账号");
  }
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card shop-account-dialog" role="dialog" aria-modal="true" aria-labelledby="shopAccountDialogTitle">
        <div class="modal-head">
          <div>
            <h2 id="shopAccountDialogTitle">选择兑换账号</h2>
            <p>${escapeHtml(good.goods_name || "商品兑换")}</p>
          </div>
          <button class="ghost icon-only" type="button" data-modal-cancel title="关闭">
            <svg><use href="#i-x"></use></svg>
          </button>
        </div>
        <label>
          <span>执行账号</span>
          <div class="select-wrapper">
              <select id="shopExchangeAccountSelect">
                    ${choices
              .map(
                  ({ account, index }) =>
                    `<option value="${index}">${escapeHtml(accountLabel(account))}</option>`,
              )
              .join("")}
              </select>
              <svg class="select-arrow" width="12" height="8" aria-hidden="true">
                <use href="#arrow-down"/>
              </svg>
          </div>
        </label>
        <div class="modal-actions">
          <button class="ghost" type="button" data-modal-cancel>取消</button>
          <button class="primary" type="button" data-modal-confirm>
            <svg><use href="#i-play"></use></svg>
            <span>确认兑换</span>
          </button>
        </div>
      </div>
    `;
    document.body.insertBefore(overlay, document.querySelector(".toast"));
    const select = overlay.querySelector("#shopExchangeAccountSelect");
    const finish = (value) => {
      overlay.remove();
      resolve(value);
    };
    overlay.querySelectorAll("[data-modal-cancel]").forEach((control) => {
      control.addEventListener("click", () => finish(null));
    });
    overlay
      .querySelector("[data-modal-confirm]")
      ?.addEventListener("click", () => finish(Number(select.value)));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) finish(null);
    });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(null);
      if (event.key === "Enter") finish(Number(select.value));
    });
    select.focus();
  });
}

function chooseShopPlanAccount(good) {
  const choices = loggedInAccountChoices();
  if (!choices.length) {
    throw new Error("请先添加并登录账号");
  }
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card shop-account-dialog" role="dialog" aria-modal="true" aria-labelledby="shopPlanDialogTitle">
        <div class="modal-head">
          <div>
            <h2 id="shopPlanDialogTitle">选择计划账号</h2>
            <p>${escapeHtml(good.goods_name || "商品兑换计划")}</p>
          </div>
          <button class="ghost icon-only" type="button" data-modal-cancel title="关闭">
            <svg><use href="#i-x"></use></svg>
          </button>
        </div>
        <label>
          <span>执行账号</span>
          <div class="select-wrapper">
          <select id="shopPlanAccountSelect">
            ${choices
              .map(
                ({ account, index }) =>
                `<option value="${index}">${escapeHtml(accountLabel(account))}</option>`,
                )
              .join("")}
            </select>
            <svg class="select-arrow" width="12" height="8" aria-hidden="true">
                <use href="#arrow-down"/>
            </svg>
          </div>
        </label>
        <div class="modal-actions">
          <button class="ghost" type="button" data-modal-cancel>取消</button>
          <button class="primary" type="button" data-modal-confirm>
            <svg><use href="#i-plus"></use></svg>
            <span>添加计划</span>
          </button>
        </div>
      </div>
    `;
    document.body.insertBefore(overlay, document.querySelector(".toast"));
    const select = overlay.querySelector("#shopPlanAccountSelect");
    const finish = (value) => {
      overlay.remove();
      resolve(value);
    };
    overlay.querySelectorAll("[data-modal-cancel]").forEach((control) => {
      control.addEventListener("click", () => finish(null));
    });
    overlay
      .querySelector("[data-modal-confirm]")
      ?.addEventListener("click", () => finish(Number(select.value)));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) finish(null);
    });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(null);
      if (event.key === "Enter") finish(Number(select.value));
    });
    select.focus();
  });
}

async function checkShopAccountLogin(accountIndex) {
  try {
    const meta = await api(
      `/api/shop/account-meta?account_index=${accountIndex}`,
    );
    const errors = [
      meta.points_error || "",
      meta.addresses_error || "",
    ];
    for (const err of errors) {
      if (/未登录|登录失效|cookie.*过期|expired/i.test(err)) {
        return err;
      }
    }
    return null;
  } catch (error) {
    if (/未登录|登录失效|cookie.*过期|expired/i.test(error.message)) {
      return error.message;
    }
    return null;
  }
}

async function withButtonLoading(button, loadingText, task) {
  if (!button) {
    shopRequestInFlight = true;
    try {
      await task();
    } finally {
      shopRequestInFlight = false;
    }
    return;
  }
  if (button.disabled) return;
  const label = button.querySelector("span");
  const originalText = label?.textContent || "";
  shopRequestInFlight = true;
  button.disabled = true;
  button.classList.add("is-loading");
  if (label) label.textContent = loadingText;
  try {
    await task();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.classList.remove("is-loading");
    button.disabled = false;
    if (label) label.textContent = originalText;
    shopRequestInFlight = false;
  }
}

function shopPlanStatus(plan, index) {
  const progress = shopRunningProgress[String(index)];
  if (progress) {
    const attempt = Number(progress.attempt || 0);
    const message = progress.message || "兑换中";
    return attempt > 0
        ? `兑换中 · 第 ${attempt} 次尝试 · ${message}`
        : `兑换中 · ${message}`;
  }
  if (plan.last_result) {
    return `${plan.enable === false ? "已暂停，" : ""}最近结果：${plan.last_result}`;
  }
  if (plan.enable === false) return "已暂停";
  if (plan.exchange_at) {
    return `等待 ${formatTime(timestampToIso(plan.exchange_at))}`;
  }
  return "未设置兑换时间";
}

function timestampToLocalInput(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "";
  const date = new Date((timestamp + 8 * 60 * 60) * 1000);
  const pad = (item) => String(item).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

function localInputToTimestamp(value) {
  if (!value) return 0;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return 0;
  const [, year, month, day, hour, minute] = match;
  const timestamp = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour) - 8,
    Number(minute),
    0,
  );
  return Number.isFinite(timestamp) ? Math.floor(timestamp / 1000) : 0;
}

function timestampToIso(value) {
  const timestamp = Number(value || 0);
  return timestamp ? timestampToBeijingText(timestamp) : "";
}

function timestampToBeijingText(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "";
  const date = new Date((timestamp + 8 * 60 * 60) * 1000);
  const pad = (item) => String(item).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
}

function serverConfig({ includeDrafts = true } = {}) {
  collectConfig();
  const payload = JSON.parse(JSON.stringify(config));
  payload.accounts = (payload.accounts || [])
    .filter((account) => includeDrafts || !account._draft)
    .map(({ _draft, ...account }) => account);

  const pushChannels = payload.push?.channels || [];
  for (const channel of pushChannels) {
    if (channel.provider === 'qq' && channel.push_url && typeof channel.push_url === 'string') {
      const url = channel.push_url.trim();
      if (url && !url.includes('http://')) {
        throw new Error('QQ 推送的 HTTP API 地址必须包含 "http://"');
      }
    }
  }

  return payload;
}

function validateUniqueAccountUids(accounts) {
  const seen = new Map();
  accounts.forEach((account, index) => {
    const uid = String(account.stuid || "").trim();
    if (!uid) return;
    if (seen.has(uid)) {
      throw new Error(`UID ${uid} 已存在，不能重复添加同一账号`);
    }
    seen.set(uid, index);
  });
}

async function saveConfig(message = "配置已保存") {
  const payload = serverConfig({ includeDrafts: true });
  validateUniqueAccountUids(payload.accounts || []);
  isSavingConfig = true;
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast(message);
    await loadConfig();
  } finally {
    isSavingConfig = false;
  }
}

// 账号变动后服务端会重新绑定兑换计划（下标重算、账号已删除的计划停用），这里把结果同步回界面
async function refreshShopPlans() {
  const latest = await api("/api/config");
  config.shop_exchange = latest.shop_exchange;
  renderShopConfig();
}

async function autoSaveConfig() {
  const payload = serverConfig({ includeDrafts: false });
  validateUniqueAccountUids(payload.accounts || []);
  isSavingConfig = true;
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } finally {
    isSavingConfig = false;
  }
}

function scheduleAutoSave() {
  if (!config || isSavingConfig) return;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {
    autoSaveConfig()
      .then(() => showToast("配置已更新"))
      .catch((error) => showToast(error.message));
  }, 450);
}

async function refreshStatus() {
  const status = await api("/api/status");
  const scheduler = status.scheduler || {};
  const exchangeScheduler = status.exchange_scheduler || {};
  const shopExchange = status.shop_exchange || null;
  const login = status.login || {};
  const logs = status.logs || [];
  const accounts = config?.accounts || [];
  const loggedIn = accounts.filter((account) => account.stuid).length;
  $("accountMetric").textContent = `${loggedIn}/${accounts.length}`;
  $("scheduleMetric").textContent = scheduler.running
    ? "执行中"
    : scheduler.enabled
      ? "已启用"
      : "已关闭";
  $("nextRun").textContent = formatTime(scheduler.next_run);
  $("lastResult").textContent = latestResultText(scheduler, login, logs);

  const runningPlans = new Set(exchangeScheduler.running_plans || []);
  const runningCount = exchangeScheduler.running_count ?? runningPlans.size;
  shopRunningProgress = exchangeScheduler.running_progress || {};


  if ($("shopScheduleMetric")) {
    $("shopScheduleMetric").textContent = runningCount > 0
      ? "兑换中"
      : exchangeScheduler.enabled
        ? "已启用"
        : "已关闭";
  }
  if ($("shopNextRun")) {
    $("shopNextRun").textContent = formatTime(exchangeScheduler.next_run);
  }
  if (
    shopExchange &&
    config &&
    !shopRequestInFlight &&
    !isEditingShopConfig()
  ) {
    config.shop_exchange = shopExchange;
    renderShopConfig();
  }
  updateLogs(logs);

  if (login.running) {
    clearLoginCountdown();
    localLoginPanel = null;
    activeLoginIndex = login.account_index ?? activeLoginIndex;
  }
  renderLoginSlot(login);
  $("runBtn").disabled = Boolean(scheduler.running);
  document.querySelectorAll("[data-login]").forEach((button) => {
    button.disabled = Boolean(login.running);
  });
  if (login.status === "success" && lastLoginStatus !== "success") {
    clearLoginCountdown();
    localLoginPanel = null;
    showToast(login.message || "登录成功");
    if (login.draft) {
      applyDraftLogin(login);
      activeLoginIndex = null;
    } else {
      activeLoginIndex = null;
      await loadConfig();
    }
  }
  lastLoginStatus = login.status || "";
}

function isEditingShopConfig() {
  const active = document.activeElement;
  return Boolean(
    active?.matches?.(
      "[data-shop-plan-field], #shopEnable, #shopRetrySeconds, #shopRetryInterval",
    ),
  );
}

function renderLoginSlot(login, options = {}) {
  const hasServerPanel = Boolean(login.running || login.qr || login.status === "error");
  if (!hasServerPanel && localLoginPanel && !options.forceLocal) {
    const existingSlot = document.querySelector(
      `[data-login-slot="${localLoginPanel.account_index}"]`,
    );
    if (existingSlot?.dataset.localLoginPanel === "1") {
      return;
    }
  }
  document.querySelectorAll("[data-login-slot]").forEach((slot) => {
    slot.innerHTML = "";
    slot.classList.remove("active");
    delete slot.dataset.localLoginPanel;
    delete slot.dataset.localLoginMode;
  });
  if (!hasServerPanel && localLoginPanel) {
    const slot = document.querySelector(
      `[data-login-slot="${localLoginPanel.account_index}"]`,
    );
    if (slot) renderLocalLoginPanel(slot, localLoginPanel);
    return;
  }
  if (!hasServerPanel) {
    return;
  }
  const index = login.account_index ?? activeLoginIndex ?? -1;
  const slot = document.querySelector(`[data-login-slot="${index}"]`);
  if (!slot) return;

  // 当登录失败且不在运行状态时，5秒后自动折叠
  if (login.status === "error" && !login.running) {
    if (loginErrorCollapseTimer) clearTimeout(loginErrorCollapseTimer);
    loginErrorCollapseTimer = setTimeout(() => {
      activeLoginIndex = null;
      renderLoginSlot({ running: false, status: "idle" });
      loginErrorCollapseTimer = null;
    }, 5000);
  } else if (loginErrorCollapseTimer) {
    clearTimeout(loginErrorCollapseTimer);
    loginErrorCollapseTimer = null;
  }

  slot.classList.add("active");
  if (login.qr) {
    slot.innerHTML = `
      <div class="inline-login">
        <button type="button" class="qr-refresh-btn" title="点击刷新二维码">
          <img src="${login.qr}" alt="米游社扫码登录二维码" />
          <span class="qr-refresh-hint">点击刷新</span>
        </button>
        <p>${escapeHtml(login.message || "等待扫码确认")}</p>
      </div>
    `;
    slot.querySelector(".qr-refresh-btn")?.addEventListener("click", refreshLoginQr);
  } else {
    slot.innerHTML = `
      <div class="inline-login pending">
        <div class="qr-loading"></div>
        <p>${escapeHtml(login.message || loginStatusText(login.status || "starting"))}</p>
      </div>
    `;
  }
}

function renderLocalLoginPanel(slot, panel) {
  slot.classList.add("active");
  slot.dataset.localLoginPanel = "1";
  slot.dataset.localLoginMode = panel.mode || "";
  if (panel.mode === "methods") {
    slot.innerHTML = `
      <div class="inline-login login-method-panel">
        <div class="login-method-actions">
          <button class="ghost" type="button" data-login-method-captcha>
            <svg><use href="#i-phone"></use></svg>
            <span>验证码登录</span>
          </button>
          <button class="ghost" type="button" data-login-method-scan>
            <svg><use href="#i-qr"></use></svg>
            <span>扫码登录</span>
          </button>
          <button class="ghost" type="button" data-login-panel-close>取消</button>
        </div>
      </div>
    `;
    slot
      .querySelector("[data-login-method-captcha]")
      ?.addEventListener("click", () => showCaptchaLogin(panel.account_index));
    slot
      .querySelector("[data-login-method-scan]")
      ?.addEventListener("click", () =>
        confirmScanLogin(panel.account_index).catch((error) =>
          showToast(error.message),
        ),
      );
    slot
      .querySelector("[data-login-panel-close]")
      ?.addEventListener("click", resetLoginPanel);
    return;
  }

  const busy = Boolean(panel.sending || panel.verifying);
  const countdown = Number(panel.countdown || 0);
  const canVerify = Boolean(panel.action_type && !busy);
  const sendDisabled = busy || countdown > 0;
  const message = panel.message
    ? `<p class="login-panel-message ${panel.error ? "error" : ""}" data-login-panel-message>${escapeHtml(panel.message)}</p>`
    : "";
  slot.innerHTML = `
    <div class="inline-login captcha-login-panel">
      <div class="captcha-login-fields">
        <input data-login-phone="${panel.account_index}" type="tel" inputmode="numeric" placeholder="手机号" value="${escapeAttr(panel.phone || "")}" autocomplete="tel" ${busy || panel.action_type ? "disabled" : ""} />
        <div class="captcha-code-row">
          <input data-login-captcha="${panel.account_index}" type="text" inputmode="numeric" placeholder="验证码" value="${escapeAttr(panel.captcha || "")}" autocomplete="one-time-code" ${panel.action_type && !busy ? "" : "disabled"} />
          <button class="ghost" type="button" data-login-send-captcha="${panel.account_index}" ${sendDisabled ? "disabled" : ""}>
            <svg><use href="#i-phone"></use></svg>
            <span>${loginSendButtonText(panel)}</span>
          </button>
        </div>
      </div>
      <div class="captcha-login-actions">
        <button class="primary" type="button" data-login-submit-captcha="${panel.account_index}" ${canVerify ? "" : "disabled"}>
          <svg><use href="#i-save"></use></svg>
          <span>${panel.verifying ? "登录中" : "登录"}</span>
        </button>
        <button class="ghost" type="button" data-login-panel-close ${busy ? "disabled" : ""}>取消</button>
      </div>
      ${message}
    </div>
  `;
  slot
    .querySelector("[data-login-phone]")
    ?.addEventListener("input", (event) => {
      if (!localLoginPanel) return;
      localLoginPanel.phone = event.target.value;
      if (localLoginPanel.action_type) {
        localLoginPanel.action_type = "";
        localLoginPanel.message = "";
      }
    });
  slot
    .querySelector("[data-login-captcha]")
    ?.addEventListener("input", (event) => {
      if (localLoginPanel) localLoginPanel.captcha = event.target.value;
    });
  slot
    .querySelector("[data-login-captcha]")
    ?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submitCaptchaLogin(panel.account_index).catch((error) =>
          showToast(error.message),
        );
      }
    });
  slot
    .querySelector("[data-login-send-captcha]")
    ?.addEventListener("click", () =>
      sendCaptchaLogin(panel.account_index).catch((error) =>
        showToast(error.message),
      ),
    );
  slot
    .querySelector("[data-login-submit-captcha]")
    ?.addEventListener("click", () =>
      submitCaptchaLogin(panel.account_index).catch((error) =>
        showToast(error.message),
      ),
    );
  slot
    .querySelector("[data-login-panel-close]")
    ?.addEventListener("click", resetLoginPanel);
}

function updateLogs(logs) {
  const logBox = $("logs");
  const wasPinned = logsPinnedToBottom || isScrolledNearBottom(logBox);
  const nextText = logs.join("\n");
  if (logBox.textContent !== nextText) {
    logBox.textContent = nextText;
    if (wasPinned) {
      requestAnimationFrame(() => scrollLogsToBottom());
    }
  }
}

function scrollLogsToBottom() {
  const logBox = $("logs");
  logBox.scrollTop = logBox.scrollHeight;
  logsPinnedToBottom = true;
}

function isScrolledNearBottom(element) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= 24;
}

async function showLoginMethods(accountIndex) {
  collectConfig();
  const account = config.accounts[accountIndex];
  if (!account) {
    throw new Error("请先添加账号");
  }
  clearLoginCountdown();
  lastLoginStatus = "";
  activeLoginIndex = accountIndex;
  localLoginPanel = { account_index: accountIndex, mode: "methods" };
  renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
}

function showCaptchaLogin(accountIndex) {
  clearLoginCountdown();
  localLoginPanel = {
    account_index: accountIndex,
    mode: "captcha",
    phone: "",
    captcha: "",
    action_type: "",
    countdown: 0,
    message: "",
    error: false,
  };
  activeLoginIndex = accountIndex;
  renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
  document.querySelector(`[data-login-phone="${accountIndex}"]`)?.focus();
}

function resetLoginPanel() {
  clearLoginCountdown();
  localLoginPanel = null;
  activeLoginIndex = null;
  renderLoginSlot({ running: false, status: "idle" });
}

function loginSendButtonText(panel) {
  const countdown = Number(panel.countdown || 0);
  if (panel.sending) return "发送中";
  if (countdown > 0) return `${countdown}s`;
  return panel.action_type ? "重发" : "发送验证码";
}

function parseLoginCountdown(value) {
  const seconds = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
}

function clearLoginCountdown() {
  if (loginCountdownTimer) {
    clearInterval(loginCountdownTimer);
    loginCountdownTimer = null;
  }
}

function startLoginCountdown(accountIndex, seconds) {
  clearLoginCountdown();
  const panel = localLoginPanel;
  if (!panel || panel.account_index !== accountIndex) return;
  panel.countdown = Math.max(Number(seconds || 0), 0);
  updateLoginCountdownView(panel);
  if (panel.countdown <= 0) return;
  loginCountdownTimer = setInterval(() => {
    const activePanel = localLoginPanel;
    if (!activePanel || activePanel.account_index !== accountIndex) {
      clearLoginCountdown();
      return;
    }
    activePanel.countdown = Math.max(Number(activePanel.countdown || 0) - 1, 0);
    if (activePanel.countdown <= 0) {
      activePanel.message = "验证码已发送，可重新发送";
      updateLoginCountdownView(activePanel);
      clearLoginCountdown();
      return;
    }
    updateLoginCountdownView(activePanel);
  }, 1000);
}

function updateLoginCountdownView(panel) {
  const button = document.querySelector(
    `[data-login-send-captcha="${panel.account_index}"]`,
  );
  if (button) {
    button.disabled =
      Boolean(panel.sending || panel.verifying) || Number(panel.countdown || 0) > 0;
    const label = button.querySelector("span");
    if (label) label.textContent = loginSendButtonText(panel);
  }
  const message = document.querySelector("[data-login-panel-message]");
  if (message && !panel.error) {
    message.textContent =
      Number(panel.countdown || 0) > 0
        ? `验证码已发送，${panel.countdown}s 后可重发`
        : panel.message || "";
  }
}

async function confirmScanLogin(accountIndex) {
  clearLoginCountdown();
  localLoginPanel = null;
  await startLogin(accountIndex);
}

function isAigisRequired(error) {
  return error?.code === "aigis_required" && error.aigis;
}

const loadedScripts = new Map();

function loadScriptOnce(src) {
  if (loadedScripts.has(src)) return loadedScripts.get(src);
  const promise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("安全验证脚本加载失败"));
    document.head.appendChild(script);
  });
  loadedScripts.set(src, promise);
  return promise;
}

async function completeAigisChallenge(rawAigis) {
  const aigis =
    typeof rawAigis === "string" ? JSON.parse(rawAigis) : rawAigis || {};
  const data =
    typeof aigis.data === "string" ? JSON.parse(aigis.data) : aigis.data || {};
  await loadScriptOnce("https://static.geetest.com/static/js/gt.0.4.9.js");
  await loadScriptOnce("https://static.geetest.com/v4/gt4.js");
  const validate = await showGeetestDialog(data, aigis);
  return `${aigis.session_id};${base64Json(validate)}`;
}

function base64Json(value) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(value))));
}

function showGeetestDialog(data, aigis) {
  return new Promise((resolve, reject) => {
    const boxId = `geetestBox${Date.now()}`;
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card geetest-dialog" role="dialog" aria-modal="true" aria-labelledby="geetestDialogTitle">
        <div class="modal-head">
          <div>
            <strong id="geetestDialogTitle">安全验证</strong>
            <p>请完成验证后继续登录</p>
          </div>
          <button class="ghost icon-only" type="button" data-geetest-cancel title="关闭">
            <svg><use href="#i-x"></use></svg>
          </button>
        </div>
        <div class="geetest-box" id="${boxId}"></div>
      </div>
    `;
    document.body.insertBefore(overlay, document.querySelector(".toast"));
    const cleanup = () => overlay.remove();
    const cancel = () => {
      cleanup();
      reject(new Error("安全验证已取消"));
    };
    overlay
      .querySelector("[data-geetest-cancel]")
      ?.addEventListener("click", cancel);

    if ("challenge" in data) {
      if (typeof window.initGeetest !== "function") {
        cancel();
        return;
      }
      window.initGeetest(
        {
          gt: data.gt,
          challenge: data.challenge,
          offline: false,
          new_captcha: true,
          product: "custom",
          area: `#${boxId}`,
          width: "250px",
          https: true,
        },
        (captchaObj) => {
          captchaObj.appendTo(`#${boxId}`);
          captchaObj.onClose(() => {
            const validate = captchaObj.getValidate();
            cleanup();
            if (!validate) {
              reject(new Error("安全验证已取消"));
              return;
            }
            resolve(validate);
          });
        },
      );
      return;
    }

    if (typeof window.initGeetest4 !== "function") {
      cancel();
      return;
    }
    window.initGeetest4(
      {
        captchaId: data.gt,
        riskType: data.risk_type,
        product: "popup",
        nextWidth: "250px",
        lang: "zho",
        userInfo: JSON.stringify({ session_id: aigis.session_id }),
        https: true,
        protocol: "https",
      },
      (captchaObj) => {
        captchaObj.appendTo(`#${boxId}`);
        captchaObj.onClose(cancel);
        captchaObj.onSuccess(() => {
          const validate = captchaObj.getValidate();
          cleanup();
          if (!validate) {
            reject(new Error("安全验证失败"));
            return;
          }
          resolve(validate);
        });
      },
    );
  });
}

async function sendCaptchaLogin(accountIndex) {
  collectConfig();
  const account = config.accounts[accountIndex];
  const panel = localLoginPanel;
  if (!account || !panel || panel.account_index !== accountIndex) {
    throw new Error("请先选择验证码登录");
  }
  panel.phone = String(
    document.querySelector(`[data-login-phone="${accountIndex}"]`)?.value ||
      panel.phone ||
      "",
  ).trim();
  panel.sending = true;
  panel.error = false;
  panel.message = "正在发送验证码";
  renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
  try {
    const response = await api("/api/login/captcha/send", {
      method: "POST",
      body: JSON.stringify({
        account_index: accountIndex,
        phone: panel.phone,
        draft: Boolean(account._draft),
        account: stripClientAccount(account),
        aigis: panel.aigis || "",
      }),
    });
    panel.sending = false;
    panel.action_type = response.action_type || "";
    panel.captcha = "";
    panel.aigis = "";
    const countdown = parseLoginCountdown(response.countdown) || 60;
    panel.countdown = countdown;
    panel.message = `验证码已发送，${countdown}s 后可重发`;
    panel.error = false;
    renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
    startLoginCountdown(accountIndex, countdown);
    document.querySelector(`[data-login-captcha="${accountIndex}"]`)?.focus();
    showToast("验证码已发送");
  } catch (error) {
    if (isAigisRequired(error)) {
      panel.sending = false;
      panel.error = false;
      panel.message = "请完成安全验证";
      renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
      panel.aigis = await completeAigisChallenge(error.aigis);
      return sendCaptchaLogin(accountIndex);
    }
    panel.sending = false;
    panel.countdown = 0;
    panel.error = true;
    panel.message = error.message || "发送验证码失败";
    renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
    throw error;
  }
}

async function submitCaptchaLogin(accountIndex) {
  collectConfig();
  const account = config.accounts[accountIndex];
  const panel = localLoginPanel;
  if (!account || !panel || panel.account_index !== accountIndex) {
    throw new Error("请先选择验证码登录");
  }
  panel.phone = String(
    document.querySelector(`[data-login-phone="${accountIndex}"]`)?.value ||
      panel.phone ||
      "",
  ).trim();
  panel.captcha = String(
    document.querySelector(`[data-login-captcha="${accountIndex}"]`)?.value ||
      panel.captcha ||
      "",
  ).trim();
  if (!panel.action_type) {
    throw new Error("请先发送短信验证码");
  }
  if (!panel.captcha) {
    throw new Error("请输入短信验证码");
  }
  panel.verifying = true;
  panel.error = false;
  panel.message = "正在登录";
  renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
  try {
    const response = await api("/api/login/captcha/verify", {
      method: "POST",
      body: JSON.stringify({
        account_index: accountIndex,
        phone: panel.phone,
        captcha: panel.captcha,
        action_type: panel.action_type,
        draft: Boolean(account._draft),
        account: stripClientAccount(account),
        aigis: panel.aigis || "",
      }),
    });
    panel.aigis = "";
    clearLoginCountdown();
    localLoginPanel = null;
    activeLoginIndex = null;
    showToast(response.message || "登录成功");
    if (response.draft) {
      applyDraftLogin(response);
    } else {
      await loadConfig();
    }
    renderLoginSlot({ running: false, status: "idle" });
  } catch (error) {
    if (isAigisRequired(error)) {
      panel.verifying = false;
      panel.error = false;
      panel.message = "请完成安全验证";
      renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
      panel.aigis = await completeAigisChallenge(error.aigis);
      return submitCaptchaLogin(accountIndex);
    }
    panel.verifying = false;
    panel.error = true;
    panel.message = error.message || "验证码登录失败";
    renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
    throw error;
  }
}

async function startLogin(accountIndex) {
  collectConfig();
  const account = config.accounts[accountIndex];
  if (!account) {
    throw new Error("请先添加账号");
  }
  lastLoginStatus = "";
  activeLoginIndex = accountIndex;
  clearLoginCountdown();
  localLoginPanel = null;
  renderLoginSlot({
    running: true,
    account_index: accountIndex,
    status: "starting",
    message: "正在生成二维码",
  });
  try {
    await api("/api/login/start", {
      method: "POST",
      body: JSON.stringify({
        account_index: accountIndex,
        timeout: 180,
        draft: Boolean(account._draft),
        account: stripClientAccount(account),
      }),
    });
    showToast("登录流程已启动");
    await refreshStatus();
  } catch (error) {
    activeLoginIndex = null;
    renderLoginSlot({});
    throw error;
  }
}

async function refreshLoginQr() {
  const btn = document.querySelector(".qr-refresh-btn");
  if (!btn || btn.classList.contains("is-refreshing")) return;
  btn.classList.add("is-refreshing");
  btn.innerHTML = `<div class="qr-loading"></div><span class="qr-refresh-hint">刷新中…</span>`;
  btn.disabled = true;
  try {
    await api("/api/login/refresh", { method: "POST", body: "{}" });
  } catch (error) {
    showToast("刷新失败: " + error.message);
  }
}

async function runNow() {
  await autoSaveConfig();
  await api("/api/run", { method: "POST", body: "{}" });
  showToast("任务已启动");
  await refreshStatus();
}

function addAccount() {
  collectConfig();
  config.accounts.push(emptyAccount(nextAccountName()));
  editingAccountIndex = config.accounts.length - 1;
  renderAccounts();
  const row = document.querySelector(
    `.account-row[data-index="${editingAccountIndex}"]`,
  );
  row?.querySelector('[data-field="name"]')?.focus();
}

function emptyAccount(name) {
  return {
    name,
    cookie: "",
    stuid: "",
    stoken: "",
    mid: "",
    cloud_games: emptyAccountCloudGames(),
    _draft: true,
  };
}

function emptyAccountCloudGames() {
  return { tokens: { genshin: "", zzz: "" } };
}

function nextAccountName() {
  const names = new Set(
    (config.accounts || []).map((account) => account.name).filter(Boolean),
  );
  for (let index = 1; index < 1000; index += 1) {
    const name = `账号${index}`;
    if (!names.has(name)) return name;
  }
  return "账号";
}

function stripClientAccount(account) {
  const { _draft, ...payload } = account || {};
  return payload;
}

function applyDraftLogin(login) {
  collectConfig();
  const index = login.account_index ?? activeLoginIndex;
  const account = config.accounts[index];
  const accountData = login.account_data || {};
  if (!account || !account._draft || !accountData.stuid) {
    return;
  }
  Object.assign(account, {
    cookie: accountData.cookie || "",
    stuid: accountData.stuid || "",
    stoken: accountData.stoken || "",
    mid: accountData.mid || "",
    _draft: true,
  });
  editingAccountIndex = index;
  renderAccounts();
  const row = document.querySelector(`.account-row[data-index="${index}"]`);
  row?.querySelector('[data-field="name"]')?.focus();
}

function accountLabel(account) {
  return account.name || account.stuid || "未命名账号";
}

function latestResultText(scheduler, login, logs) {
  if (scheduler.running) return "正在签到";
  if (scheduler.last_error) return "任务失败";
  const latest = [...logs].reverse().find((line) => {
    return /任务汇总|签到汇总|签到成功|社区任务结束|获得|任务执行完成|登录成功|失败|触发验证码/.test(
      line,
    );
  });
  if (latest) {
    if (latest.includes("云游戏成功项")) return "云游戏成功";
    if (latest.includes("云游戏失败项")) return "云游戏部分失败";
    if (latest.includes("游戏社区成功项") || latest.includes("游戏成功项"))
      return "社区签到成功";
    if (latest.includes("游戏社区失败项") || latest.includes("游戏失败项"))
      return "社区部分失败";
    if (latest.includes("米游币任务汇总")) {
      const points = latest.match(/实际已获得\s*([^，\s]+)/);
      return points ? `米游币 ${points[1]}` : "米游币完成";
    }
    if (latest.includes("云游戏签到汇总"))
      return latest.includes("失败 0") ? "云游戏成功" : "云游戏部分失败";
    if (
      latest.includes("游戏社区签到汇总") ||
      latest.includes("游戏签到汇总")
    ) {
      return latest.includes("失败 0") ? "社区签到成功" : "社区部分失败";
    }
    if (latest.includes("社区任务结束")) {
      const points = latest.match(/今日已得\s*([^，\s]+)/);
      return points ? `米游币 ${points[1]}` : "米游币完成";
    }
    if (latest.includes("签到成功")) return "签到成功";
    if (latest.includes("任务执行完成")) return "任务完成";
    if (latest.includes("登录成功")) return "登录成功";
    if (latest.includes("触发验证码")) return "需要验证";
    if (latest.includes("失败")) return "任务失败";
    if (latest.includes("获得")) return "奖励已获取";
  }
  if (login.status && login.status !== "idle")
    return loginStatusText(login.status);
  if (scheduler.last_run) return "任务完成";
  return "-";
}

function loginStatusText(status) {
  const labels = {
    starting: "生成二维码",
    waiting: "等待扫码",
    exchanging: "换取凭证",
    success: "登录成功",
    error: "登录失败",
  };
  return labels[status] || status;
}

function formatTime(value) {
  if (!value) return "-";
  return value.replace("T", " ");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function switchView(view) {
  activeView = view || "dashboard";
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === activeView);
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("is-hidden", panel.dataset.viewPanel !== activeView);
  });
  document.querySelectorAll("[data-view-actions]").forEach((actions) => {
    actions.classList.toggle(
      "is-hidden",
      actions.dataset.viewActions !== activeView,
    );
  });
  if (activeView === "shop" && !shopGoods.length) {
    loadShopGoods().catch((error) => showToast(error.message));
  }
}
function initSelectArrows() {
  // 使用 mousedown 切换旋转状态（比 click 更早触发，且不会干扰下拉展开）
  document.addEventListener('mousedown', function(e) {
    const select = e.target.closest('select');
    if (!select) return;
    const wrapper = select.closest('.select-wrapper');
    if (!wrapper) return;
    // 阻止冒泡，避免外部点击监听误判
    e.stopPropagation();
    // 切换旋转状态
    wrapper.classList.toggle('arrow-rotated');
  });

  // 选择选项后关闭下拉 → 恢复旋转状态
  document.addEventListener('change', function(e) {
    const select = e.target.closest('select');
    if (!select) return;
    const wrapper = select.closest('.select-wrapper');
    if (!wrapper) return;
    wrapper.classList.remove('arrow-rotated');
  });

  // 失去焦点时恢复（键盘操作或点击外部）
  document.addEventListener('blur', function(e) {
    const select = e.target.closest('select');
    if (!select) return;
    const wrapper = select.closest('.select-wrapper');
    if (!wrapper) return;
    // 延迟检查，让浏览器先完成焦点切换
    setTimeout(() => {
      if (!select.matches(':focus')) {
        wrapper.classList.remove('arrow-rotated');
      }
    }, 10);
  }, true); // 捕获阶段

  // 点击页面空白处（非 select 区域）移除所有旋转状态
  document.addEventListener('click', function(e) {
    // 如果点击发生在 .select-wrapper 内部，则不处理（避免干扰）
    if (e.target.closest('.select-wrapper')) return;
    // 移除所有旋转类
    document.querySelectorAll('.select-wrapper.arrow-rotated').forEach(w => {
      w.classList.remove('arrow-rotated');
    });
  });
}

function injectArrowSymbol() {
  if (document.querySelector('#arrow-down')) return;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.style.display = 'none';
  const symbol = document.createElementNS('http://www.w3.org/2000/svg', 'symbol');
  symbol.id = 'arrow-down';
  symbol.setAttribute('viewBox', '0 0 10 6');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M1 1l4 4 4-4');
  path.setAttribute('stroke', 'currentColor');
  path.setAttribute('stroke-width', '1.5');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke-linecap', 'round');
  symbol.appendChild(path);
  svg.appendChild(symbol);
  document.body.prepend(svg);
}

function bindEvents() {
  document.querySelectorAll("summary button, summary input")
      .forEach((control) => {
        control.addEventListener("click", (event) => event.stopPropagation());
      });
  $("shopStatusFilter")?.addEventListener("change", (event) => {
    shopFilterStatus = event.target.value;
    shopCurrentPage = 1;
    renderShopGoods();
  });
  document.addEventListener("change", (event) => {
    if (event.target?.matches?.("[data-autosave]")) {
      scheduleAutoSave();
    }
  });
  document.addEventListener("input", (event) => {
    if (
        event.target?.matches?.(
            'input[type="time"][data-autosave], input[type="datetime-local"][data-autosave], input[type="number"][data-autosave], input[type="text"][data-autosave], select[data-autosave], [data-account-cloud-token][data-autosave]',
        )
    ) {
      scheduleAutoSave();
    }
  });
  $("refreshBtn").addEventListener("click", () => {
    Promise.all([loadConfig(), refreshStatus()]).catch((error) =>
        showToast(error.message),
    );
  });
  $("runBtn").addEventListener("click", () =>
      runNow().catch((error) => showToast(error.message)),
  );
  $("logs").addEventListener("scroll", () => {
    logsPinnedToBottom = isScrolledNearBottom($("logs"));
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  $("shopRefreshBtn")?.addEventListener("click", () =>
      loadShopGoods().catch((error) => showToast(error.message)),
  );
  $("shopGameFilter")?.addEventListener("change", () =>
      loadShopGoods().catch((error) => showToast(error.message)),
  );
}

bindEvents();
switchView(activeView);

// ---------------------------------------------------------------------------
// 认证流程
// ---------------------------------------------------------------------------
function isAuthError(error) {
  return error?.message === "未登录" || error?.status === 401;
}

async function checkAuthAndInit() {
  try {
    const authStatus = await api("/api/auth/status");
    if (!authStatus.need_auth) {
      startApp();
      return;
    }
    // 需要认证时，先试探一个受保护接口判断 session 是否仍然有效
    try {
      await api("/api/config");
      startApp();
    } catch {
      showAuthPage(authStatus.password_set);
    }
  } catch {
    startApp();
  }
}

function showAuthPage(passwordSet) {
  const shell = document.querySelector(".shell");
  shell.style.display = "none";

  const subtitle = passwordSet ? "请输入访问密码" : "首次使用，请设置外网访问密码";
  const buttonText = passwordSet ? "登录" : "设置密码";
  const inputPlaceholder = passwordSet ? "输入密码" : "设置密码（至少 8 位）";

  const overlay = document.createElement("div");
  overlay.className = "auth-overlay";
  overlay.id = "authOverlay";
  overlay.innerHTML = `
    <div class="auth-card">
      <span class="brand-mark">
        <img src="/assets/myq_logo_clip.png" alt="米游签" />
      </span>
      <h2>米游签</h2>
      <p class="auth-subtitle">${subtitle}</p>
      <input id="authPassword" type="password" placeholder="${inputPlaceholder}" autocomplete="current-password" />
      <button class="primary" id="authSubmit" type="button">${buttonText}</button>
      <p class="auth-error" id="authError"></p>
    </div>
  `;
  document.body.insertBefore(overlay, document.querySelector(".toast"));

  const passwordInput = document.getElementById("authPassword");
  const submitBtn = document.getElementById("authSubmit");
  const errorEl = document.getElementById("authError");

  const submit = async () => {
    const password = passwordInput.value.trim();
    if (!password) {
      errorEl.textContent = "请输入密码";
      return;
    }
    if (!passwordSet && password.length < 8) {
      errorEl.textContent = "密码至少 8 位";
      return;
    }
    submitBtn.disabled = true;
    errorEl.textContent = "";
    try {
      const endpoint = passwordSet ? "/api/auth/login" : "/api/auth/setup";
      await api(endpoint, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      overlay.remove();
      shell.style.display = "";
      startApp();
    } catch (error) {
      errorEl.textContent = error.message || "操作失败";
      submitBtn.disabled = false;
    }
  };

  submitBtn.addEventListener("click", submit);
  passwordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
  passwordInput.focus();
}

function startApp() {
  initSelectArrows()
  injectArrowSymbol()
  loadConfig()
    .then(refreshStatus)
    .catch((error) => {
      if (isAuthError(error)) {
        checkAuthAndInit();
        return;
      }
      showToast(error.message);
    });
  setInterval(() => {
    refreshStatus().catch((error) => {
      if (isAuthError(error)) {
        checkAuthAndInit();
      }
    });
  }, 3000);
}

checkAuthAndInit();
