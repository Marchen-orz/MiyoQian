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
  ["gotify", "Gotify"],
];

// 通道图标放在 /assets/push/，文件名和通道 provider 一一对应
const pushChannelIconFiles = {
  pushplus: "pushplus.png",
  serverchan: "serverchan.png",
  telegram: "telegram.svg",
  dingrobot: "dingtalk.png",
  feishubot: "feishu.png",
  wecombot: "wecom.png",
  email: "email.svg",
  qq: "qq.svg",
  qqbot: "qqbot.svg",
  gotify: "gotify.png",
};

// 通道字段的默认值：取值等于默认值不算「已配置」。
// 和后端 config.py 的 PUSH_CHANNEL_DEFAULTS 一一对应（这里的值统一是字符串），测试会校验两边一致
const pushChannelDefaults = {
  qqbot: { message_format: "text" },
  gotify: { priority: "5" },
};

// 取值非空且不等于默认值，才算用户配置过这个字段。
// 数字 0 是有效取值；布尔 false（如 plain_text 的默认值）当作没填
function pushFieldConfigured(channel, key) {
  const raw = channel[key];
  const value = raw === false ? "" : String(raw ?? "").trim();
  return value !== "" && value !== pushChannelDefaults[channel.provider]?.[key];
}

// 供测试断言渠道清单和默认值；应用自身不读这些导出
if (typeof globalThis !== "undefined") {
  globalThis.__myqPushChannelOptions = pushChannelOptions;
  globalThis.__myqPushChannelDefaults = pushChannelDefaults;
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
let pushModalDraft = null;    // 弹窗里还没保存的输入；点「保存」前不写进 config
let taskModalKind = null;     // 当前在弹窗里配置的任务（game / cloud / bbs）
let taskModalEl = null;
let qqBindState = null;
let qqBindTimer = null;
let qqBindTarget = "";
let qqBindRestored = false;
let editingCaptchaProviders = new Set();
let logsPinnedToBottom = true;
let activeView = "dashboard";
const ACCOUNTS_VISIBLE = 3;      // 账号栏最多同时露出几个账号，其余在列表里滚动
const PANEL_STATE_KEY = "miyouqian.panels";
const LOG_PANEL_GAP = 24;        // 日志栏贴着窗口底部时留的边距
const LOG_PANEL_TOP = 16;        // 同 CSS 里 .side-column 的 sticky top
let logFitQueued = false;
const DEFAULT_AVATAR = "/assets/paimon-avatar-192.webp";
let accountAvatars = {};         // 账号 UID -> 米游社头像地址，取到才有
const avatarRequested = new Set(); // 已经问过后端的 UID，一次打开页面只问一次
let deviceInfo = null;           // GET /api/device 的结果，没取到是 null
let deviceError = "";            // 读取设备信息失败的原因
let deviceBusy = "";             // 正在进行的操作（fp / import / reset），空表示空闲
let deviceImportDraft = "";      // 导入框里还没提交的文字，面板重绘时保留


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

function showToast(message, tone = "info") {
  const toast = $("toast");
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), Math.min(15000, Math.max(2600, String(message).length * 90)));
}

async function loadConfig() {
  config = await api("/api/config");
  config.accounts = (config.accounts || []).map((account) => ({
    ...account,
    _draft: false,
  }));
  shopMetaCache.clear();
  renderConfig();
  loadAllPlanAddresses();
  loadDevice();
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
        <label class="choice-toggle ${disabled ? "is-disabled" : ""}"${title}>
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

// 图标只是装饰，名字已经写在旁边，所以 alt 留空
function pushChannelIcon(provider) {
  const file = pushChannelIconFiles[provider];
  if (!file) return "";
  return `<img class="channel-icon" src="/assets/push/${file}" alt="" width="24" height="24" />`;
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
      const icon = pushChannelIcon(provider);
      const classes = ["choice-button"];
      if (icon) classes.push("has-icon");
      if (channel?.enable) {
        classes.push("is-on");
      } else if (hasPushChannelConfig(channel)) {
        classes.push("is-configured");
      }
      return `
        <button class="${classes.join(" ")}" type="button" data-open-push="${provider}" title="配置${escapeAttr(label)}">
          ${icon}
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
  pushModalDraft = channel ? { ...channel } : null;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-card choice-dialog" data-push-provider="${escapeAttr(provider)}" role="dialog" aria-modal="true" aria-labelledby="pushChannelModalTitle">
      <div class="modal-head">
        <div>
          <strong class="channel-title" id="pushChannelModalTitle">${pushChannelIcon(provider)}<span>${escapeHtml(label)}</span></strong>
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
  closeOnBackdropClick(overlay, closePushChannelModal);
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
  pushModalDraft = null;
}

// 只有点遮罩本身才关：在输入框里按下、拖到遮罩上松手也会触发 click，那样会丢掉已填的内容
function closeOnBackdropClick(overlay, close) {
  let pressedOnBackdrop = false;
  overlay.addEventListener("mousedown", (event) => {
    pressedOnBackdrop = event.target === overlay;
  });
  overlay.addEventListener("click", (event) => {
    if (pressedOnBackdrop && event.target === overlay) close();
  });
}

// 把弹窗当前填的内容收进草稿。轮询绑定进度、重新拉配置都会重画弹窗，
// 重画前先收一次，没保存的输入和「启用此通道」才不会被配置里的旧值冲掉
function captureModalDraft() {
  if (!pushModalProvider || !pushModalEl) return pushModalDraft;
  const card = pushModalEl.querySelector("[data-push-provider]");
  if (!card || !card.querySelector("[data-push-field]")) return pushModalDraft;
  pushModalDraft = cleanPushChannel(collectPushChannel(card));
  return pushModalDraft;
}

function renderPushChannelModal() {
  if (!pushModalProvider || !pushModalEl) return;
  const provider = pushModalProvider;
  const body = pushModalEl.querySelector("[data-push-modal-body]");
  if (!body) return;
  captureModalDraft();
  const saved = findPushChannel(provider);
  const channel = pushModalDraft || saved;
  const toggle = pushModalEl.querySelector("[data-push-toggle]");
  if (toggle) toggle.checked = Boolean(channel?.enable);
  const errorOnly = pushModalEl.querySelector("[data-push-error-only]");
  if (errorOnly) errorOnly.checked = Boolean(config.push?.error_only);
  const state = pushModalEl.querySelector("[data-push-modal-state]");
  if (state) state.textContent = pushChannelStateText(saved);
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
  closeOnBackdropClick(overlay, closeTaskModal);
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
      <p class="task-note">国服和国际服账号共用这份游戏列表；国际服没有的游戏（如崩坏学园2）会自动跳过。</p>
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
        <div class="choice-toggles cols-3" id="cloudGameChips"></div>
      </div>
      <p class="task-note">仅对国服账号生效，国际服账号会自动跳过。</p>
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
    <p class="task-note">仅对国服账号生效，国际服账号会自动跳过。</p>
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
    message_format: channel.message_format || pushChannelDefaults.qqbot.message_format,
    api_base: channel.api_base || "",
    smtp_host: channel.smtp_host || "",
    smtp_port: channel.smtp_port || 465,
    smtp_user: channel.smtp_user || "",
    smtp_password: channel.smtp_password || "",
    mail_from: channel.mail_from || "",
    mail_to: channel.mail_to || "",
    smtp_ssl: channel.smtp_ssl ?? true,
    server: channel.server || "",
    // 0 是合法的最低优先级，不能用 || 回退到默认值
    priority: String(channel.priority ?? "").trim() || pushChannelDefaults.gotify.priority,
  };
  const field = (name, label, type = "text", attrs = "") => `
    <label>
      <span>${label}</span>
      <input data-push-field="${name}" type="${type}" value="${escapeAttr(common[name] || "")}" ${attrs} autocomplete="off" />
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
    gotify: [
      field("server", "服务器地址"),
      field("token", "App Token", "password"),
      field("priority", "优先级（0-10，默认 5）", "number", 'min="0" max="10" step="1"'),
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
  // 弹窗里刚填的 AppID/AppSecret 还没保存，只收进弹窗草稿用来校验，
  // 不写进 config，这样绑定途中点「取消」不会被之后的自动保存带上磁盘
  captureModalDraft();
  collectConfig();
  const channel = cleanPushChannel(
      pushModalDraft || findPushChannel("qqbot") || emptyPushChannel("qqbot"),
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
          // 服务端已把 AppID/AppSecret/OpenID 写盘，弹窗改回显示磁盘上的值
          if (pushModalProvider === "qqbot") pushModalDraft = null;
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
    // 推送方式是下拉框，没填别的参数时也总有值，不能算「已配置」
    if (key === "msg_type") return false;
    if (key === "smtp_port") return Number(channel[key] || 465) !== 465;
    if (key === "smtp_ssl") return channel[key] === false;
    if (key === "plain_text") return Boolean(channel[key]);
    return pushFieldConfigured(channel, key);
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
    gotify: ["server", "token", "priority"],
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
      // 用 ?? 而不是 ||：数字 0（如 Gotify 优先级）不能被当成空值丢掉；留空的字段补上默认值
      cleaned[key] = String(channel[key] ?? "").trim() || String(pushChannelDefaults[provider]?.[key] ?? "");
    }
  });
  return cleaned;
}

function shouldSavePushChannel(channel) {
  if (channel.enable) return true;
  return pushChannelFieldNames(channel.provider).some((key) => {
    if (key === "smtp_ssl" || key === "msg_type") return false;
    if (key === "smtp_port") return Number(channel[key] || 465) !== 465;
    return pushFieldConfigured(channel, key);
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

// 账号列表有高度上限，展开或编辑的卡片可能被截断，这里把它滚到完整可见
function revealAccount(index) {
  const row = document.querySelector(`.account-row[data-index="${index}"]`);
  const list = row?.closest(".acc-list");
  if (!list) return;
  const rowRect = row.getBoundingClientRect();
  const listRect = list.getBoundingClientRect();
  const inset = 3; // 与 .acc-list 的内边距一致，别让卡片阴影贴边被裁
  const above = rowRect.top - listRect.top - inset;
  const below = rowRect.bottom - listRect.bottom + inset;
  // 卡片比列表还高时，以顶边为准
  if (above < 0 || rowRect.height + inset * 2 > listRect.height) list.scrollTop += above;
  else if (below > 0) list.scrollTop += below;
}

function renderAccounts() {
  const accounts = config.accounts || [];
  const cards = accounts
    .map((account, index) => accountCard(account, index))
    .join("");
  // 账号多了只在列表里滚动，「添加账号」放在列表外面，始终固定在底部
  const scrollable = accounts.length > ACCOUNTS_VISIBLE ? " is-scrollable" : "";
  // 重绘会重置列表的滚动位置，先记下来，操作某个账号后不要跳回顶部
  const previousScroll = document.querySelector("#accounts .acc-list")?.scrollTop || 0;
  $("accounts").innerHTML = accounts.length
    ? `<div class="acc-list${scrollable}">${cards}</div>
       <button class="acc-add-card" type="button" data-add-account>
         <svg><use href="#i-plus"></use></svg>
         <span>添加账号</span>
       </button>`
    : `<div class="acc-empty">
        <svg><use href="#i-user"></use></svg>
        <strong>还没有账号</strong>
        <span>国服可扫码或验证码登录，国际服粘贴 HoYoLAB cookie</span>
        <button class="primary" type="button" data-add-account>
          <svg><use href="#i-plus"></use></svg>
          <span>添加账号</span>
        </button>
      </div>`;
  const list = document.querySelector("#accounts .acc-list");
  if (list && previousScroll) list.scrollTop = previousScroll;

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
  document.querySelectorAll("[data-region-select]").forEach((select) => {
    // 换服务器会改变这张卡片上的按钮和提示，先把已填的内容收回来再重画
    select.addEventListener("change", () => {
      collectConfig();
      renderAccounts();
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
      revealAccount(editingAccountIndex);
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
      revealAccount(index);
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
  document.querySelectorAll(".acc-avatar.is-remote").forEach(bindAvatarFallback);
  loadAccountAvatars();
}

// 米游社头像加载失败（被拦、链接失效）就退回默认头像，下次重绘也不再用这个地址
function bindAvatarFallback(img) {
  img.addEventListener(
    "error",
    () => {
      delete accountAvatars[img.dataset.avatarUid];
      img.classList.remove("is-remote");
      img.src = DEFAULT_AVATAR;
    },
    { once: true },
  );
}

// 头像只是装饰：取不到就一直用默认头像，不提示、不重试
async function loadAccountAvatars() {
  try {
    const keys = (config?.accounts || [])
      .filter((account) => account.stuid)
      .map(avatarKey)
      .filter((key) => /^(?:\d+|os:\d+)$/.test(key) && !(key in accountAvatars) && !avatarRequested.has(key));
    if (!keys.length) return;
    keys.forEach((key) => avatarRequested.add(key));
    const data = await api(`/api/account/avatars?uids=${keys.join(",")}`);
    Object.assign(accountAvatars, data.avatars || {});
    applyAccountAvatars();
  } catch {
    // 保持默认头像
  }
}

// 异步取回头像后就地换图，不重绘账号列表，免得打断正在进行的编辑或登录
function applyAccountAvatars() {
  (config.accounts || []).forEach((account, index) => {
    const key = avatarKey(account);
    const url = accountAvatars[key];
    const img = document.querySelector(`.account-row[data-index="${index}"] .acc-avatar`);
    if (!url || !img || img.classList.contains("is-remote")) return;
    img.dataset.avatarUid = key;
    img.classList.add("is-remote");
    img.src = url;
    bindAvatarFallback(img);
  });
}

// 国服 / 国际服共用同一份账号列表，账号上的 region 只决定登录方式和哪些功能适用
function isOverseas(account) {
  return account?.region === "os";
}

// 两边的 UID 可能撞号，头像缓存按服务器分开存
function avatarKey(account) {
  const uid = String(account?.stuid || "");
  return isOverseas(account) ? `os:${uid}` : uid;
}

// 登录成功后清掉这张卡片记住的头像，随后的重绘会重新取一次
// （换了账号、上次没取到、或者之前根本没登录）
function forgetAccountAvatar(account) {
  const key = avatarKey(account);
  if (!key) return;
  delete accountAvatars[key];
  avatarRequested.delete(key);
}

// 服务器只能在还没登录时选；登录之后凭证属于哪一边就固定了
function accountRegionControl(account, index, editing, loggedIn) {
  const overseas = isOverseas(account);
  if (!editing || loggedIn) {
    return `<input data-field="region" type="hidden" value="${overseas ? "os" : "cn"}" />`;
  }
  return `
    <label class="acc-region">
      <span>服务器</span>
      <div class="select-wrapper">
        <select data-field="region" data-region-select="${index}">
          <option value="cn" ${overseas ? "" : "selected"}>国服（米游社）</option>
          <option value="os" ${overseas ? "selected" : ""}>国际服（HoYoLAB）</option>
        </select>
        <svg class="select-arrow" width="12" height="8" aria-hidden="true"><use href="#arrow-down"/></svg>
      </div>
    </label>
  `;
}

function accountCard(account, index) {
  const editing = editingAccountIndex === index;
  const loggedIn = Boolean(account.stuid);
  const overseas = isOverseas(account);
  // 头像走各自服务器的公开资料接口，国际服取 HoYoLAB 的头像
  const avatarUrl = loggedIn ? accountAvatars[avatarKey(account)] || "" : "";
  const cloudCount = overseas ? 0 : accountCloudCount(account);
  const cloudOpen = !overseas && expandedCloudAccounts.has(index);
  const regionControl = accountRegionControl(account, index, editing, loggedIn);
  const nameField = editing
    ? `<input class="acc-edit-input" data-field="name" type="text" maxlength="10" placeholder="最多 10 字" value="${escapeAttr(account.name || "")}" />`
    : `<span class="acc-name-text">${escapeHtml(accountLabel(account))}</span>
       <input data-field="name" type="hidden" value="${escapeAttr(account.name || "")}" />`;
  const cloudChip = overseas
    ? ""
    : `<span class="acc-chip ${cloudCount ? "on" : ""}">
         <svg><use href="#i-cloud"></use></svg>${cloudCount ? `云游戏 ${cloudCount}/2` : "云游戏未配置"}
       </span>`;
  const loginHint = overseas
    ? "点「粘贴 Cookie」填入 HoYoLAB 的 cookie"
    : "点「登录方式」扫码或验证码登录";
  // 编辑态还没有登录按钮，只留名字长度提示；登录引导等保存后再出现
  const meta = loggedIn
    ? `<span class="acc-uid">UID ${escapeHtml(account.stuid)}</span>${cloudChip}`
    : editing
      ? ""
      : `<span>还没有登录，${loginHint}</span>`;
  const loginLabel = overseas
    ? loggedIn ? "更新 Cookie" : "粘贴 Cookie"
    : loggedIn ? "刷新登录" : "登录方式";
  const cloudButton = overseas
    ? ""
    : `<button class="ghost ${cloudOpen || cloudCount ? "is-active" : ""}" type="button" data-toggle-cloud="${index}" title="云游戏签到凭证">
         <svg><use href="#i-cloud"></use></svg>
         <span>云游戏凭证</span>
       </button>`;
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
         <svg><use href="#${overseas ? "i-edit" : "i-phone"}"></use></svg>
         <span>${loginLabel}</span>
       </button>
       ${cloudButton}
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
        <img class="acc-avatar${loggedIn ? "" : " is-empty"}${avatarUrl ? " is-remote" : ""}" src="${escapeAttr(avatarUrl || DEFAULT_AVATAR)}" ${avatarUrl ? `data-avatar-uid="${escapeAttr(avatarKey(account))}" ` : ""}referrerpolicy="no-referrer" alt="" width="44" height="44" />
        <div class="acc-body">
          <div class="acc-name">
            ${nameField}
            <span class="acc-pill ${loggedIn ? "ok" : "off"}">${loggedIn ? "已登录" : "未登录"}</span>
            ${overseas ? `<span class="acc-pill os">国际服</span>` : ""}
            ${account._draft ? `<span class="acc-pill draft">未保存</span>` : ""}
          </div>
          ${meta ? `<div class="acc-meta">${meta}</div>` : ""}
          ${editing ? `<div class="acc-hint">最多 10 个字，仅用于本地显示</div>` : ""}
          ${editing && !loggedIn ? regionControl : ""}
        </div>
      </div>
      <div class="acc-actions">${actions}</div>
      ${editing && !loggedIn ? "" : regionControl}
      <input data-field="stuid" type="hidden" value="${escapeAttr(account.stuid || "")}" />
      <input data-field="stoken" type="hidden" value="${escapeAttr(account.stoken || "")}" />
      <input data-field="mid" type="hidden" value="${escapeAttr(account.mid || "")}" />
      <textarea class="hidden-field" data-field="cookie">${escapeHtml(account.cookie || "")}</textarea>
      ${overseas ? accountCloudGameHiddenFields(account.cloud_games?.tokens || {}) : accountCloudGameFields(account, index)}
      <div class="account-login-slot" data-login-slot="${index}"></div>
    </article>
  `;
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

function timestampToLocalInput(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "";
  const date = new Date((timestamp + 8 * 60 * 60) * 1000);
  const pad = (item) => String(item).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
}

function localInputToTimestamp(value) {
  if (!value) return 0;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) return 0;
  const [, year, month, day, hour, minute, second] = match;
  const timestamp = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour) - 8,
    Number(minute),
    Number(second || 0),
  );
  if (!Number.isFinite(timestamp)) return 0;
  const result = Math.floor(timestamp / 1000);
  const expected = `${year}-${month}-${day}T${hour}:${minute}:${second || "00"}`;
  return timestampToLocalInput(result) === expected ? result : 0;
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
  // 国服和国际服是两套账号体系，UID 只在同一服务器内要求唯一
  const seen = new Map();
  accounts.forEach((account, index) => {
    const uid = String(account.stuid || "").trim();
    if (!uid) return;
    const key = `${isOverseas(account) ? "os" : "cn"}:${uid}`;
    if (seen.has(key)) {
      throw new Error(`UID ${uid} 已存在，不能重复添加同一账号`);
    }
    seen.set(key, index);
  });
}

async function saveConfig(message = "配置已保存") {
  const payload = serverConfig({ includeDrafts: true });
  validateUniqueAccountUids(payload.accounts || []);
  await enqueueConfigSave(payload);
  showToast(message);
  if (!isSavingConfig) await loadConfig();
}

// 账号变动后服务端会重新绑定兑换计划（下标重算、账号已删除的计划停用），这里把结果同步回界面
async function refreshShopPlans() {
  const latest = await api("/api/config");
  config.shop_exchange = latest.shop_exchange;
  renderShopConfig();
}

let configSaveQueue = Promise.resolve();
let configSavePending = 0;
function autoSaveConfig() {
  const payload = serverConfig({ includeDrafts: false });
  validateUniqueAccountUids(payload.accounts || []);
  return enqueueConfigSave(payload);
}
function enqueueConfigSave(payload) {
  const revision = shopRevision;
  configSavePending += 1;
  isSavingConfig = true;
  // 按页面操作顺序保存，防止较早的请求晚到，把后一次编辑覆盖掉。
  const request = configSaveQueue.catch(() => {}).then(() => api("/api/config", {
    method: "POST",
    body: JSON.stringify(payload),
  })).then(() => { shopSavedRevision = Math.max(shopSavedRevision, revision); });
  configSaveQueue = request;
  return request.finally(() => {
    configSavePending -= 1;
    isSavingConfig = configSavePending > 0;
    updateShopSelection();
  });
}

function scheduleAutoSave() {
  if (!config) return;
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

  receiveShopStatus(exchangeScheduler, shopExchange);
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
    // 扫码登录也走同一条路：先让这张卡片的头像失效，重绘时重新取
    const loginIndex = login.account_index ?? activeLoginIndex;
    forgetAccountAvatar({
      stuid: login.account_data?.stuid || accounts[loginIndex]?.stuid,
      region: login.account_data?.region || accounts[loginIndex]?.region,
    });
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
      "#shopEnable, #shopRetrySeconds, #shopRetryInterval, #shopPush",
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
  if (panel.mode === "cookie") {
    renderCookieLoginPanel(slot, panel);
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

// 国际服（HoYoLAB）没有扫码 / 验证码登录，凭证是用户从浏览器里复制的 cookie
function renderCookieLoginPanel(slot, panel) {
  const busy = Boolean(panel.verifying);
  const message = panel.message
    ? `<p class="login-panel-message ${panel.error ? "error" : ""}" data-login-panel-message>${escapeHtml(panel.message)}</p>`
    : "";
  slot.innerHTML = `
    <div class="inline-login captcha-login-panel cookie-login-panel">
      <div class="captcha-login-fields">
        <textarea data-login-cookie="${panel.account_index}" rows="3" spellcheck="false" autocomplete="off" placeholder="ltuid_v2=…; ltoken_v2=…" ${busy ? "disabled" : ""}>${escapeHtml(panel.cookie || "")}</textarea>
        <p class="login-panel-hint">在浏览器里登录 hoyolab.com，按 F12 打开开发者工具，到「应用（Application）→ Cookie」里找到 ltuid_v2 和 ltoken_v2，连同行头一起复制也可以；复制后点「从剪贴板粘贴」，或直接在输入框里按 Ctrl+V。</p>
        <p class="login-panel-detect" data-login-detect></p>
      </div>
      <div class="captcha-login-actions">
        <button class="primary" type="button" data-login-submit-cookie="${panel.account_index}" ${busy ? "disabled" : ""}>
          <svg><use href="#i-save"></use></svg>
          <span>${busy ? "登录中" : "登录"}</span>
        </button>
        <button class="ghost" type="button" data-login-paste-clipboard ${busy ? "disabled" : ""}>从剪贴板粘贴</button>
        <button class="ghost" type="button" data-login-panel-close ${busy ? "disabled" : ""}>取消</button>
      </div>
      ${message}
    </div>
  `;
  slot
    .querySelector("[data-login-cookie]")
    ?.addEventListener("input", (event) => {
      if (localLoginPanel) localLoginPanel.cookie = event.target.value;
      updateCookieDetect();
    });
  slot
    .querySelector("[data-login-paste-clipboard]")
    ?.addEventListener("click", () => {
      readClipboardCookie(panel);
    });
  slot
    .querySelector("[data-login-submit-cookie]")
    ?.addEventListener("click", () =>
      submitCookieLogin(panel.account_index).catch((error) =>
        showToast(error.message),
      ),
    );
  slot
    .querySelector("[data-login-panel-close]")
    ?.addEventListener("click", resetLoginPanel);
  updateCookieDetect();
}

// 和海外模块的 cookie 解析保持一致：整段请求头、开发者工具表格、JSON、手拼的 name=value
const HOYOLAB_UID_FIELDS = ["ltuid_v2", "ltuid", "account_id_v2", "account_id"];
const HOYOLAB_TOKEN_FIELDS = ["ltoken_v2", "ltoken", "cookie_token_v2", "cookie_token"];

function hoyolabCookiePairs(text) {
  const pairs = new Map();
  const source = String(text || "").trim();
  if (!source) return pairs;
  if (source.startsWith("[") || source.startsWith("{")) {
    try {
      const data = JSON.parse(source);
      const items = Array.isArray(data) ? data : [data];
      for (const item of items) {
        if (!item || typeof item !== "object") continue;
        if ("name" in item) pairs.set(String(item.name), String(item.value ?? ""));
        else if (!Array.isArray(data)) {
          for (const [name, value] of Object.entries(item)) pairs.set(name, String(value ?? ""));
        }
      }
      if (pairs.size) return pairs;
    } catch {
      // 不是 JSON，按普通 cookie 文本继续解析
    }
  }
  const header = source.match(/^\s*cookie\s*[:：]\s*(.+)$/im);
  for (const line of (header ? header[1] : source).split(/[;\r\n]+/)) {
    const row = line.trim();
    if (!row) continue;
    // 开发者工具里框选 cookie 表格复制出来是「名称\t值\t域\t路径…」
    const cells = row.split("\t");
    const pair = cells.length > 1 ? `${cells[0].trim()}=${cells[1].trim()}` : row;
    const index = pair.indexOf("=");
    if (index <= 0) continue;
    const name = pair.slice(0, index).trim();
    const value = pair.slice(index + 1).trim().replace(/^"(.*)"$/, "$1").trim();
    if (value && /^[A-Za-z0-9_.-]+$/.test(name)) pairs.set(name, value);
  }
  return pairs;
}

function describeHoyolabCookie(text) {
  const pairs = hoyolabCookiePairs(text);
  const uidField = HOYOLAB_UID_FIELDS.find((name) => pairs.get(name)) || "";
  // 只回报命中的字段名，不把 token 的值显示到页面上
  return {
    uid: uidField ? pairs.get(uidField) : "",
    token: HOYOLAB_TOKEN_FIELDS.find((name) => pairs.get(name)) || "",
  };
}

function setCookieDetect(text, state) {
  const node = document.querySelector("[data-login-detect]");
  if (!node) return;
  node.textContent = text;
  if (state) node.dataset.state = state;
  else delete node.dataset.state;
}

// 粘贴后立刻告诉用户解析到了什么，不用等签到才发现 cookie 少了一项
function updateCookieDetect() {
  const textarea = document.querySelector("[data-login-cookie]");
  if (!textarea) return;
  if (!textarea.value.trim()) {
    setCookieDetect("");
    return;
  }
  const { uid, token } = describeHoyolabCookie(textarea.value);
  if (uid && token) {
    setCookieDetect(`已识别 UID ${uid}，凭证 ${token}`, "ok");
  } else if (uid) {
    setCookieDetect(`已识别 UID ${uid}，但没有找到 ltoken_v2`, "warn");
  } else if (token) {
    setCookieDetect("已找到 token，但没有找到 ltuid_v2", "warn");
  } else {
    setCookieDetect("还没有识别到 ltuid_v2 / ltoken_v2", "warn");
  }
}

async function readClipboardCookie(panel) {
  let text = "";
  try {
    // 本地控制台（127.0.0.1 / localhost）属于安全上下文，浏览器会放行；换域名访问时可能被拒
    text = await navigator.clipboard.readText();
  } catch {
    setCookieDetect("浏览器不允许读取剪贴板，请点一下输入框再按 Ctrl+V 粘贴", "error");
    return;
  }
  if (!text.trim()) {
    setCookieDetect("剪贴板是空的，请先在浏览器里复制 HoYoLAB 的 cookie", "error");
    return;
  }
  const textarea = document.querySelector(`[data-login-cookie="${panel.account_index}"]`);
  if (!textarea) return;
  textarea.value = text.trim();
  panel.cookie = textarea.value;
  if (localLoginPanel) localLoginPanel.cookie = panel.cookie;
  textarea.focus();
  updateCookieDetect();
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
  // 国际服只有粘贴 cookie 一种登录方式，不需要先选
  if (isOverseas(account)) {
    showCookieLogin(accountIndex);
    return;
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

function showCookieLogin(accountIndex) {
  clearLoginCountdown();
  lastLoginStatus = "";
  localLoginPanel = {
    account_index: accountIndex,
    mode: "cookie",
    cookie: "",
    message: "",
    error: false,
  };
  activeLoginIndex = accountIndex;
  renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
  document.querySelector(`[data-login-cookie="${accountIndex}"]`)?.focus();
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
    forgetAccountAvatar({
      stuid: response.account_data?.stuid || account.stuid,
      region: account.region,
    });
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

async function submitCookieLogin(accountIndex) {
  collectConfig();
  const account = config.accounts[accountIndex];
  const panel = localLoginPanel;
  if (!account || !panel || panel.account_index !== accountIndex) {
    throw new Error("请先选择登录方式");
  }
  panel.cookie = String(
    document.querySelector(`[data-login-cookie="${accountIndex}"]`)?.value ??
      panel.cookie ??
      "",
  ).trim();
  if (!panel.cookie) {
    throw new Error("请粘贴 HoYoLAB 的 cookie");
  }
  panel.verifying = true;
  panel.error = false;
  panel.message = "正在登录";
  renderLoginSlot({ running: false, status: "idle" }, { forceLocal: true });
  try {
    const response = await api("/api/login/cookie", {
      method: "POST",
      body: JSON.stringify({
        account_index: accountIndex,
        cookie: panel.cookie,
        draft: Boolean(account._draft),
        account: stripClientAccount(account),
      }),
    });
    localLoginPanel = null;
    activeLoginIndex = null;
    showToast(response.message || "登录成功");
    // 先清掉旧头像，下面的重绘会把新账号的头像重新取回来
    forgetAccountAvatar({
      stuid: response.account_data?.stuid || account.stuid,
      region: response.account_data?.region || account.region,
    });
    if (response.draft) {
      applyDraftLogin(response);
    } else {
      await loadConfig();
    }
    renderLoginSlot({ running: false, status: "idle" });
  } catch (error) {
    panel.verifying = false;
    panel.error = true;
    panel.message = error.message || "Cookie 登录失败";
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
  revealAccount(editingAccountIndex);
}

function emptyAccount(name) {
  return {
    name,
    region: "cn",
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
    region: accountData.region || account.region || "cn",
    _draft: true,
  });
  editingAccountIndex = index;
  renderAccounts();
  const row = document.querySelector(`.account-row[data-index="${index}"]`);
  row?.querySelector('[data-field="name"]')?.focus();
  revealAccount(index);
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
  if (activeView === "shop") renderShopPlans(false);
  if (activeView === "shop" && !shopGoods.length && !shopGoodsLoading) {
    loadShopGoods().catch((error) => showToast(error.message));
  }
  scheduleLogFit();
}

// 左侧各栏的展开状态记在浏览器里；从没记过就保持 HTML 里默认展开的前两栏
function readPanelState() {
  try {
    const saved = JSON.parse(localStorage.getItem(PANEL_STATE_KEY) || "null");
    return saved && typeof saved === "object" ? saved : null;
  } catch {
    return null;
  }
}

function savePanelState(panels) {
  const state = {};
  panels.forEach((panel) => {
    state[panel.dataset.panel] = panel.open;
  });
  try {
    localStorage.setItem(PANEL_STATE_KEY, JSON.stringify(state));
  } catch {
    // 隐私模式等拿不到存储时，只是不记忆
  }
}

function initPanelState() {
  const panels = Array.from(document.querySelectorAll("details.panel[data-panel]"));
  const saved = readPanelState();
  panels.forEach((panel) => {
    const open = saved?.[panel.dataset.panel];
    if (typeof open === "boolean") panel.open = open;
    // 每次都按页面上所有栏的当前状态整体写入，恢复时触发的 toggle 也只会写回同样的值
    panel.addEventListener("toggle", () => savePanelState(panels));
  });
}

// 日志栏：页面滚动时贴在可视区右侧，高度补满到窗口底部（窄屏不处理）
function fitLogPanel() {
  const side = document.querySelector(".side-column");
  if (!side) return;
  if (window.innerWidth <= 860 || side.offsetParent === null) {
    side.classList.remove("is-fitted");
    side.style.removeProperty("height");
    return;
  }
  const top = Math.max(side.getBoundingClientRect().top, LOG_PANEL_TOP);
  side.style.height = `${Math.max(window.innerHeight - top - LOG_PANEL_GAP, 320)}px`;
  side.classList.add("is-fitted");
}

function scheduleLogFit() {
  if (logFitQueued || typeof requestAnimationFrame !== "function") return;
  logFitQueued = true;
  requestAnimationFrame(() => {
    logFitQueued = false;
    fitLogPanel();
  });
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

// ---------------------------------------------------------------------------
// 设备信息
// ---------------------------------------------------------------------------
const DEVICE_FP_TAGS = {
  server: { tone: "ok", label: "服务器签发" },
  imported: { tone: "ok", label: "真机导入" },
};

async function loadDevice() {
  try {
    deviceInfo = await api("/api/device");
    deviceError = "";
  } catch (error) {
    deviceError = `设备信息读取失败：${error.message}`;
  }
  renderDevicePanel();
}

function deviceFpTag(info) {
  if (!info.fp) return { tone: "warn", label: "未获取" };
  return DEVICE_FP_TAGS[info.fp_source] || { tone: "warn", label: "来源不明" };
}

function formatDeviceTime(seconds) {
  const value = Number(seconds);
  if (!value) return "";
  const date = new Date(value * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function deviceFpNote(info) {
  if (!info.fp) {
    return "还没有 device_fp：请求里不会带 x-rpc-device_fp（不会拿随机值冒充），可点「向服务器申请」，或在下方导入真机的。";
  }
  if (!info.trusted_fp) {
    return "这枚 device_fp 来源不明（多半是旧版本随机生成的），下次任务会向服务器重新申请并替换；如果它是你自己填的真机值，请改用下方「导入」保留。";
  }
  const when = formatDeviceTime(info.fp_time);
  return when ? `device_fp 取得于 ${when}。` : "";
}

function renderDevicePanel() {
  const host = $("devicePanel");
  if (!host) return;
  const info = deviceInfo;
  if (!info) {
    host.innerHTML = `<p class="task-note">${escapeHtml(deviceError || "正在读取设备信息…")}</p>`;
    return;
  }
  const tag = deviceFpTag(info);
  const disabled = deviceBusy ? "disabled" : "";
  const label = (task, idle, busy) => (deviceBusy === task ? busy : idle);
  const system = info.os_version
    ? `Android ${escapeHtml(info.os_version)}${info.sdk ? ` · SDK ${escapeHtml(info.sdk)}` : ""}`
    : "-";
  host.innerHTML = `
    <div class="device-facts">
      <div class="device-fact">
        <span>设备</span>
        <div>
          <strong>${escapeHtml(info.name || info.model || "-")}</strong>
          <em class="device-tag">${info.source === "imported" ? "真机导入" : "预设机型"}</em>
          ${info.has_ua ? '<em class="device-tag ok">含真机 UA</em>' : ""}
        </div>
      </div>
      <div class="device-fact"><span>系统</span><div>${system}</div></div>
      <div class="device-fact"><span>device_id</span><code>${escapeHtml(info.id || "-")}</code></div>
      <div class="device-fact">
        <span>device_fp</span>
        <div>
          <code>${escapeHtml(info.fp || "-")}</code>
          <em class="device-tag ${tag.tone}">${tag.label}</em>
        </div>
      </div>
    </div>
    <p class="task-note">${escapeHtml(deviceFpNote(info))}</p>
    <div class="device-actions">
      <button class="ghost" type="button" data-device-action="fp" ${disabled}>
        <svg><use href="#i-refresh"></use></svg>
        <span>${label("fp", "向服务器申请 fp", "申请中…")}</span>
      </button>
      <button class="ghost" type="button" data-device-action="reset" ${disabled}>
        <svg><use href="#i-phone"></use></svg>
        <span>${label("reset", "换一台虚拟设备", "生成中…")}</span>
      </button>
    </div>
    <label class="device-import">
      <span>导入真机信息</span>
      <textarea
        id="deviceImportText"
        autocomplete="off"
        spellcheck="false"
        placeholder="粘贴米游社 App 请求的整段请求头、Copy as cURL，或含 device_id / device_fp 的 JSON"
      >${escapeHtml(deviceImportDraft)}</textarea>
    </label>
    <p class="task-note">导入的 device_id、机型、系统版本、UA 会优先于预设使用；其中的 device_fp 视为可信，不会被覆盖。</p>
    <div class="device-actions">
      <button class="primary" type="button" data-device-action="import" ${disabled}>
        <svg><use href="#i-save"></use></svg>
        <span>${label("import", "导入", "导入中…")}</span>
      </button>
    </div>
  `;
}

// 同一时间只做一件事；面板整块重绘，导入框里没提交的文字存在 deviceImportDraft 里
async function runDeviceAction(task, work) {
  if (deviceBusy) return;
  deviceBusy = task;
  renderDevicePanel();
  try {
    await work();
  } catch (error) {
    showToast(error.message);
  } finally {
    deviceBusy = "";
    renderDevicePanel();
  }
}

function requestDeviceFp() {
  return runDeviceAction("fp", async () => {
    const data = await api("/api/device/fp", { method: "POST", body: "{}" });
    deviceInfo = data.device;
    showToast("已向服务器申请到新的 device_fp");
  });
}

function importDeviceInfo() {
  const text = deviceImportDraft.trim();
  if (!text) {
    showToast("先粘贴要导入的内容");
    return Promise.resolve();
  }
  return runDeviceAction("import", async () => {
    const data = await api("/api/device/import", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    deviceInfo = data.device;
    deviceImportDraft = "";
    const changed = data.changed || [];
    showToast(changed.length ? `已导入：${changed.join("、")}` : "导入的内容与当前设备一致，没有变化");
  });
}

async function resetDevice() {
  const model = await chooseDeviceResetModel();
  if (model === null) return;
  await runDeviceAction("reset", async () => {
    const data = await api("/api/device/reset", {
      method: "POST",
      body: JSON.stringify({ model }),
    });
    deviceInfo = data.device;
    renderDevicePanel();
    // 新设备没有 fp，顺手申请；失败也不回滚，下次任务会再试
    try {
      const issued = await api("/api/device/fp", { method: "POST", body: "{}" });
      deviceInfo = issued.device;
      showToast(`已换成 ${deviceInfo.name}，并取得新的 device_fp`);
    } catch (error) {
      showToast(`已换成 ${deviceInfo.name}，但 device_fp 申请失败：${error.message}`);
    }
  });
}

// 选一台预设机型（空字符串 = 随机）；取消返回 null
function chooseDeviceResetModel() {
  const presets = deviceInfo?.presets || [];
  const current = deviceInfo?.model || "";
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="deviceResetTitle">
        <div class="modal-head">
          <div>
            <h2 id="deviceResetTitle">换一台虚拟设备</h2>
            <p>会生成新的 device_id，旧的 device_fp 作废并重新申请；账号凭证不会被清除。</p>
          </div>
          <button class="ghost icon-only" type="button" data-modal-cancel title="关闭">
            <svg><use href="#i-x"></use></svg>
          </button>
        </div>
        <label>
          <span>机型</span>
          <div class="select-wrapper">
            <select id="deviceResetModel">
              <option value="">随机（从预设中任选）</option>
              ${presets
                .map(
                  (preset) =>
                    `<option value="${escapeAttr(preset.model)}">${escapeHtml(preset.label)}（Android ${escapeHtml(preset.os_version)}）${preset.model === current ? " · 当前" : ""}</option>`,
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
            <svg><use href="#i-phone"></use></svg>
            <span>确认更换</span>
          </button>
        </div>
      </div>
    `;
    document.body.insertBefore(overlay, document.querySelector(".toast"));
    const select = overlay.querySelector("#deviceResetModel");
    const finish = (value) => {
      overlay.remove();
      resolve(value);
    };
    overlay.querySelectorAll("[data-modal-cancel]").forEach((control) => {
      control.addEventListener("click", () => finish(null));
    });
    overlay
      .querySelector("[data-modal-confirm]")
      ?.addEventListener("click", () => finish(select.value));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) finish(null);
    });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(null);
    });
    select.focus();
  });
}

function bindDeviceEvents() {
  document.addEventListener("click", (event) => {
    const button = event.target?.closest?.("[data-device-action]");
    if (!button || button.disabled) return;
    const action = button.dataset.deviceAction;
    if (action === "fp") requestDeviceFp();
    else if (action === "import") importDeviceInfo();
    else if (action === "reset") resetDevice();
  });
  document.addEventListener("input", (event) => {
    if (event.target?.id === "deviceImportText") deviceImportDraft = event.target.value;
  });
}

function bindEvents() {
  bindDeviceEvents();
  document.querySelectorAll("summary button, summary input")
      .forEach((control) => {
        control.addEventListener("click", (event) => event.stopPropagation());
      });
  bindShopEvents();
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

}

bindEvents();
initPanelState();
if (typeof window !== "undefined") {
  window.addEventListener("scroll", scheduleLogFit, { passive: true });
  window.addEventListener("resize", scheduleLogFit);
}
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
  setInterval(updateShopCountdowns, 1000);
  setInterval(() => {
    refreshStatus().catch((error) => {
      if (isAuthError(error)) {
        checkAuthAndInit();
      }
    });
  }, 3000);
}

checkAuthAndInit();
