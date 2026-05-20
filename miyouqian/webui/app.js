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
  ["starrail", "云星穹铁道", true, "云星穹铁道是版本更新赠送 600 分钟，不需要每日签到获取时长"],
];

const pushChannelOptions = [
  ["pushplus", "pushplus"],
  ["telegram", "Telegram"],
  ["dingrobot", "钉钉机器人"],
  ["feishubot", "飞书机器人"],
  ["email", "邮箱"],
];

const captchaChannelOptions = [
  ["damagou", "打码狗(成本≈0.01元/次)"],
];

let config = null;
let toastTimer = null;
let autoSaveTimer = null;
let isSavingConfig = false;
let lastLoginStatus = "";
let activeLoginIndex = null;
let editingAccountIndex = null;
let expandedCloudAccounts = new Set();
let editingPushProviders = new Set();
let editingCaptchaProviders = new Set();
let logsPinnedToBottom = true;
let activeView = "dashboard";
let shopGoods = [];
let shopGames = [{ key: "", name: "全部分区" }];
let shopSelectedGame = "";
let shopOpenPlans = new Set();
let shopRequestInFlight = false;
let shopGoodsLoading = false;
let shopGoodsLoadSeq = 0;
let shopExchangeNowGoodsId = "";

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
  config.accounts = (config.accounts || []).map((account) => ({ ...account, _draft: false }));
  renderConfig();
}

function renderConfig() {
  $("scheduleEnable").checked = Boolean(config.schedule?.enable ?? true);
  $("scheduleTime").value = config.schedule?.time || "09:00";
  $("scheduleJitter").value = config.schedule?.jitter_minutes ?? 45;
  $("runOnStart").checked = Boolean(config.schedule?.run_on_start ?? false);

  $("gameCheckin").checked = Boolean(config.features?.game_checkin ?? true);
  $("cloudGameCheckin").checked = Boolean(config.features?.cloud_game_checkin ?? false);
  $("bbsTasks").checked = Boolean(config.features?.bbs_tasks ?? false);
  $("bbsCheckin").checked = Boolean(config.bbs?.checkin ?? true);
  $("bbsRead").checked = Boolean(config.bbs?.read ?? true);
  $("bbsLike").checked = Boolean(config.bbs?.like ?? true);
  $("bbsShare").checked = Boolean(config.bbs?.share ?? true);

  $("pushErrorOnly").checked = Boolean(config.push?.error_only ?? false);
  $("captchaMaxRetries").value = config.captcha?.max_retries ?? 3;
  renderGames();
  renderCloudGames();
  renderPushChannels();
  renderCaptchaChannels();
  updateTaskDependencyState();
  renderAccounts();
  renderShopConfig();
}

function renderGames() {
  const enabled = new Set(config.games?.enabled || []);
  $("gameChips").innerHTML = gameOptions
    .map(
      ([key, label]) => `
        <label class="chip">
          <input type="checkbox" data-game="${key}" data-autosave ${enabled.has(key) ? "checked" : ""} />
          <span>${label}</span>
        </label>
      `
    )
    .join("");
  updateTaskDependencyState();
}

function renderCloudGames() {
  const enabled = new Set(config.cloud_games?.enabled || []);
  $("cloudGameChips").innerHTML = cloudGameOptions
    .map(([key, label, disabled, reason]) => {
      const title = reason ? ` title="${escapeAttr(reason)}"` : "";
      return `
        <label class="chip ${disabled ? "disabled" : ""}"${title}>
          <input type="checkbox" data-cloud-game="${key}" data-autosave ${enabled.has(key) ? "checked" : ""} ${disabled ? 'data-cloud-game-disabled="1" disabled' : ""} />
          <span>${label}</span>
        </label>
      `;
    })
    .join("");
  updateTaskDependencyState();
}

function updateTaskDependencyState() {
  const gameEnabled = $("gameCheckin").checked;
  const cloudEnabled = $("cloudGameCheckin").checked;
  const bbsEnabled = $("bbsTasks").checked;
  setTaskGroupDisabled("gameTaskGroup", "[data-game]", !gameEnabled);
  setTaskGroupDisabled("cloudGameTaskGroup", "[data-cloud-game]:not([data-cloud-game-disabled])", !cloudEnabled);
  updateAccountCloudGameInputs();
  setTaskGroupDisabled("bbsTaskGroup", "#bbsCheckin, #bbsRead, #bbsLike, #bbsShare", !bbsEnabled);
}

function setTaskGroupDisabled(groupId, selector, disabled) {
  const group = $(groupId);
  if (!group) return;
  group.classList.toggle("is-disabled", disabled);
  group.querySelectorAll(selector).forEach((input) => {
    input.disabled = disabled;
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

function renderPushChannels() {
  const channels = config.push?.channels || [];
  const byProvider = new Map(channels.map((channel) => [channel.provider, channel]));
  $("pushChannels").innerHTML = pushChannelOptions
    .map(([provider, label]) => {
      const channel = byProvider.get(provider);
      const enabled = Boolean(channel?.enable);
      const editing = editingPushProviders.has(provider);
      const configured = hasPushChannelConfig(channel);
      return `
        <div class="push-channel" data-push-provider="${provider}">
          <div class="push-channel-main">
            <label class="check-row push-channel-toggle">
              <input type="checkbox" data-push-toggle="${provider}" ${enabled ? "checked" : ""} />
              <span>${label}</span>
            </label>
            <div class="push-channel-actions">
              ${
                configured && !editing
                  ? `<button class="ghost icon-only" type="button" data-edit-push="${provider}" title="编辑${label}配置">
                      <svg><use href="#i-edit"></use></svg>
                    </button>`
                  : ""
              }
              ${
                editing
                  ? `<button class="primary" type="button" data-save-push="${provider}" title="保存${label}配置">
                      <svg><use href="#i-save"></use></svg>
                      <span>保存</span>
                    </button>`
                  : ""
              }
            </div>
          </div>
          ${editing ? pushChannelFields(provider, channel || emptyPushChannel(provider)) : pushChannelHiddenFields(channel)}
        </div>
      `;
    })
    .join("");
  bindPushChannelEvents();
}

function bindPushChannelEvents() {
  document.querySelectorAll("[data-push-toggle]").forEach((input) => {
    input.addEventListener("change", () => {
      collectConfig();
      const provider = input.dataset.pushToggle;
      if (input.checked) {
        const existingChannel = findPushChannel(provider);
        upsertPushChannel({ ...emptyPushChannel(provider), ...(existingChannel || {}), enable: true });
        if (!hasPushChannelConfig(existingChannel)) {
          editingPushProviders.add(provider);
        } else {
          editingPushProviders.delete(provider);
          autoSaveConfig()
            .then(() => showToast("推送通道已启用"))
            .catch((error) => showToast(error.message));
        }
        renderPushChannels();
        return;
      }
      upsertPushChannel({ ...emptyPushChannel(provider), ...(findPushChannel(provider) || {}), enable: false });
      editingPushProviders.delete(provider);
      renderPushChannels();
      autoSaveConfig()
        .then(() => showToast("推送通道已关闭"))
        .catch((error) => showToast(error.message));
    });
  });
  document.querySelectorAll("[data-edit-push]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      editingPushProviders.add(button.dataset.editPush);
      renderPushChannels();
    });
  });
  document.querySelectorAll("[data-save-push]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        collectConfig();
        editingPushProviders.delete(button.dataset.savePush);
        await saveConfig("推送通道已保存");
      } catch (error) {
        showToast(error.message);
      }
    });
  });
}

function pushChannelFields(provider, channel) {
  const common = {
    token: channel.token || "",
    webhook: channel.webhook || "",
    api_url: channel.api_url || "",
    topic: channel.topic || "",
    chat_id: channel.chat_id || "",
    secret: channel.secret || "",
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
  const checkbox = (name, label) => `
    <label class="check-row">
      <input data-push-field="${name}" type="checkbox" ${common[name] ? "checked" : ""} />
      <span>${label}</span>
    </label>
  `;
  const fields = {
    pushplus: [
      field("token", "Token", "password"),
      field("topic", "群组编码"),
      field("api_url", "自定义 API 地址"),
    ],
    telegram: [
      field("token", "Bot Token", "password"),
      field("chat_id", "Chat ID"),
      field("api_url", "自定义 API 地址"),
    ],
    dingrobot: [
      field("webhook", "Webhook", "password"),
      field("secret", "加签 Secret", "password"),
    ],
    feishubot: [
      field("webhook", "Webhook", "password"),
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
  return `<div class="push-channel-fields form-grid two compact">${(fields[provider] || []).join("")}</div>`;
}

function pushChannelHiddenFields(channel) {
  if (!channel) return "";
  return Object.entries(cleanPushChannel(channel))
    .filter(([key]) => key !== "provider" && key !== "enable")
    .map(([key, value]) => `<input data-push-field="${key}" type="hidden" value="${escapeAttr(value ?? "")}" />`)
    .join("");
}

function emptyPushChannel(provider) {
  return cleanPushChannel({ provider, enable: true });
}

function upsertPushChannel(channel) {
  config.push = config.push || {};
  config.push.channels = config.push.channels || [];
  const index = config.push.channels.findIndex((item) => item.provider === channel.provider);
  if (index === -1) {
    config.push.channels.push(channel);
  } else {
    config.push.channels[index] = { ...config.push.channels[index], ...channel };
  }
}

function findPushChannel(provider) {
  return (config.push?.channels || []).find((item) => item.provider === provider) || null;
}

function hasPushChannelConfig(channel) {
  if (!channel) return false;
  const configKeys = [
    "token",
    "webhook",
    "api_url",
    "topic",
    "chat_id",
    "secret",
    "smtp_host",
    "smtp_user",
    "smtp_password",
    "mail_from",
    "mail_to",
  ];
  return configKeys.some((key) => String(channel[key] || "").trim());
}

function pushChannelFieldNames(provider) {
  const fields = {
    pushplus: ["token", "topic", "api_url"],
    telegram: ["token", "chat_id", "api_url"],
    dingrobot: ["webhook", "secret"],
    feishubot: ["webhook"],
    email: ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "mail_from", "mail_to", "smtp_ssl"],
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
    return String(channel[key] || "").trim();
  });
}

function renderCaptchaChannels() {
  const channels = config.captcha?.channels || [];
  const byProvider = new Map(channels.map((channel) => [channel.provider, channel]));
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
        </div>
      `;
    })
    .join("");
  bindCaptchaChannelEvents();
}

function bindCaptchaChannelEvents() {
  document.querySelectorAll("[data-captcha-toggle]").forEach((input) => {
    input.addEventListener("change", () => {
      collectConfig();
      const provider = input.dataset.captchaToggle;
      const existingChannel = findCaptchaChannel(provider);
      if (input.checked) {
        upsertCaptchaChannel({ ...emptyCaptchaChannel(provider), ...(existingChannel || {}), enable: true });
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
      upsertCaptchaChannel({ ...emptyCaptchaChannel(provider), ...(existingChannel || {}), enable: false });
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
}

function captchaChannelFields(provider, channel) {
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
    .map(([key, value]) => `<input data-captcha-field="${key}" type="hidden" value="${escapeAttr(value ?? "")}" />`)
    .join("");
}

function emptyCaptchaChannel(provider) {
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
  const index = config.captcha.channels.findIndex((item) => item.provider === channel.provider);
  if (index === -1) {
    config.captcha.channels.push(channel);
  } else {
    config.captcha.channels[index] = { ...config.captcha.channels[index], ...channel };
  }
}

function findCaptchaChannel(provider) {
  return (config.captcha?.channels || []).find((item) => item.provider === provider) || null;
}

function hasCaptchaChannelConfig(channel) {
  return Boolean(channel && String(channel.userkey || "").trim());
}

function renderAccounts() {
  const accounts = config.accounts || [];
  $("accounts").innerHTML = accounts.length
    ? accounts
    .map(
      (account, index) => `
        <div class="account-row" data-index="${index}" data-draft="${account._draft ? "1" : "0"}">
          <div class="account-main">
            <div class="account-title">
              <strong>
                <span class="status-dot ${account.stuid ? "ok" : ""}"></span>
                ${
                  editingAccountIndex === index
                    ? `<input class="inline-name-input" data-field="name" type="text" maxlength="10" placeholder="最多 10 字" value="${escapeAttr(account.name || "")}" />`
                    : `<span class="account-name-text">${escapeHtml(accountLabel(account))}</span><input data-field="name" type="hidden" value="${escapeAttr(account.name || "")}" />`
                }
              </strong>
              <small>${account.stuid ? `UID ${escapeHtml(account.stuid)}` : "未登录"}</small>
            </div>
            <div class="account-actions">
              ${
                editingAccountIndex === index
                  ? `
                    <button class="primary" type="button" data-save-account="${index}" title="保存账号名">
                      <svg><use href="#i-save"></use></svg>
                      <span>保存</span>
                    </button>
                    <button class="ghost icon-only" type="button" data-cancel-account="${index}" title="取消编辑">
                      <svg><use href="#i-x"></use></svg>
                    </button>
                  `
                  : `
                    <button class="ghost icon-only" type="button" data-edit-account="${index}" title="编辑账号名">
                      <svg><use href="#i-edit"></use></svg>
                    </button>
                  `
              }
              <button class="ghost" type="button" data-login="${index}" title="扫码登录">
                <svg><use href="#i-qr"></use></svg>
                <span>${account.stuid ? "刷新" : "登录"}</span>
              </button>
              <button class="ghost icon-only ${hasAccountCloudToken(account) || expandedCloudAccounts.has(index) ? "is-active" : ""}" type="button" data-toggle-cloud="${index}" title="云游戏签到凭证">
                <svg><use href="#i-cloud"></use></svg>
              </button>
              <button class="ghost icon-only" type="button" data-remove="${index}" title="删除账号">
                <svg><use href="#i-trash"></use></svg>
              </button>
            </div>
          </div>
          <input data-field="stuid" type="hidden" value="${escapeAttr(account.stuid || "")}" />
          <input data-field="stoken" type="hidden" value="${escapeAttr(account.stoken || "")}" />
          <input data-field="mid" type="hidden" value="${escapeAttr(account.mid || "")}" />
          <textarea class="hidden-field" data-field="cookie">${escapeHtml(account.cookie || "")}</textarea>
          ${accountCloudGameFields(account, index)}
          <div class="account-login-slot" data-login-slot="${index}"></div>
        </div>
      `
    )
    .join("")
    : `<div class="empty-state">
        <strong>暂无账号</strong>
        <span>添加账号后，可在账号卡片内扫码登录。</span>
      </div>`;
  document.querySelectorAll("[data-login]").forEach((button) => {
    button.addEventListener("click", () => {
      startLogin(Number(button.dataset.login)).catch((error) => showToast(error.message));
    });
  });
  document.querySelectorAll("[data-edit-account]").forEach((button) => {
    button.addEventListener("click", () => {
      collectConfig();
      editingAccountIndex = Number(button.dataset.editAccount);
      renderAccounts();
      const row = document.querySelector(`.account-row[data-index="${editingAccountIndex}"]`);
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
      if (config.accounts[index]?._draft) {
        config.accounts.splice(index, 1);
        editingAccountIndex = null;
        expandedCloudAccounts = shiftExpandedCloudAccounts(index);
        renderAccounts();
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
    button.addEventListener("click", () => {
      const index = Number(button.dataset.remove);
      const [removed] = config.accounts.splice(index, 1);
      if (editingAccountIndex === index) editingAccountIndex = null;
      if (editingAccountIndex !== null && editingAccountIndex > index) editingAccountIndex -= 1;
      expandedCloudAccounts = shiftExpandedCloudAccounts(index);
      renderAccounts();
      if (!removed?._draft) {
        autoSaveConfig()
          .then(() => showToast("账号已删除"))
          .catch((error) => showToast(error.message));
      }
    });
  });
  updateTaskDependencyState();
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

function hasAccountCloudToken(account) {
  const tokens = account.cloud_games?.tokens || {};
  return Boolean(String(tokens.genshin || "").trim() || String(tokens.zzz || "").trim());
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
  config.features = {
    game_checkin: $("gameCheckin").checked,
    cloud_game_checkin: $("cloudGameCheckin").checked,
    bbs_tasks: $("bbsTasks").checked,
  };
  config.games = config.games || {};
  config.games.enabled = Array.from(document.querySelectorAll("[data-game]:checked")).map((input) => input.dataset.game);
  config.cloud_games = config.cloud_games || {};
  config.cloud_games.enabled = Array.from(document.querySelectorAll("[data-cloud-game]:checked")).map((input) => input.dataset.cloudGame);
  config.bbs = {
    ...(config.bbs || {}),
    checkin: $("bbsCheckin").checked,
    read: $("bbsRead").checked,
    like: $("bbsLike").checked,
    share: $("bbsShare").checked,
  };
  config.push = {
    ...(config.push || {}),
    error_only: $("pushErrorOnly").checked,
  };
  config.push.channels = Array.from(document.querySelectorAll("[data-push-provider]"))
    .map((row) => collectPushChannel(row))
    .map((channel) => cleanPushChannel(channel))
    .filter((channel) => shouldSavePushChannel(channel));
  config.push.enable = config.push.channels.some((channel) => channel.enable);
  config.captcha = {
    ...(config.captcha || {}),
    max_retries: Number($("captchaMaxRetries").value || 3),
  };
  config.captcha.channels = Array.from(document.querySelectorAll("[data-captcha-provider]"))
    .map((row) => collectCaptchaChannel(row))
    .filter(Boolean);
  config.captcha.enable = config.captcha.channels.some((channel) => channel.enable);
  config.shop_exchange = collectShopExchange();
  config.accounts = Array.from(document.querySelectorAll(".account-row")).map((row) => {
    const item = {};
    row.querySelectorAll("[data-field]").forEach((field) => {
      item[field.dataset.field] = field.value.trim();
    });
    item.cloud_games = collectAccountCloudGames(row);
    item.name = (item.name || "").slice(0, 10);
    item._draft = row.dataset.draft === "1";
    return item;
  });
  return config;
}

function collectPushChannel(row) {
  const toggle = row.querySelector("[data-push-toggle]");
  const provider = row.dataset.pushProvider;
  const channel = emptyPushChannel(provider);
  channel.enable = Boolean(toggle?.checked);
  row.querySelectorAll("[data-push-field]").forEach((field) => {
    if (field.dataset.pushField === "smtp_ssl") {
      channel.smtp_ssl = field.type === "checkbox" ? field.checked : field.value === "true";
    } else if (field.type === "checkbox") {
      channel[field.dataset.pushField] = field.checked;
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
      channel.timeout = Number(field.value || 60);
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
  $("shopRetrySeconds").value = shop.retry_seconds ?? 5;
  $("shopRetryInterval").value = shop.retry_interval ?? 0.4;
  if ($("shopGoodsMetric")) $("shopGoodsMetric").textContent = shopGoodsLoading ? "加载中" : String(shopGoods.length);
  if ($("shopPlansMetric")) $("shopPlansMetric").textContent = String((shop.plans || []).length);
  renderShopGameFilter();
  renderShopGoods();
  renderShopGoodsLoadingState();
  renderShopPlans();
}

function renderShopGameFilter() {
  const select = $("shopGameFilter");
  if (!select) return;
  select.innerHTML = shopGames
    .map((game) => `<option value="${escapeAttr(game.key)}" ${game.key === shopSelectedGame ? "selected" : ""}>${escapeHtml(game.name)}</option>`)
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
    return;
  }
  list.innerHTML = shopGoods.length
    ? shopGoods.map((good, index) => shopGoodCard(good, index)).join("")
    : `<div class="empty-state shop-empty">
        <strong>暂无商品数据</strong>
        <span>点击刷新商品后，会显示兑换时间、库存、价格和图片。</span>
      </div>`;
  bindShopGoodsEvents();
}

function shopGoodCard(good, index) {
  const soldOut = isShopGoodSoldOut(good);
  const exchangeNow = canShopGoodExchangeNow(good);
  const exchanging = shopExchangeNowGoodsId === String(good.goods_id || "");
  const exchangeLabel = good.display_status === "sold_out_with_next" ? "下次兑换" : "兑换";
  const exchangeButtonText = exchanging ? "兑换中" : soldOut ? "已售罄" : exchangeNow ? "兑换" : "即将开启";
  const exchangeButtonTitle = exchanging ? "正在发送兑换请求" : soldOut ? "商品已售罄" : exchangeNow ? "立即发送兑换请求" : "商品还未开启兑换";
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
        <button class="ghost" type="button" data-shop-add="${index}" title="${soldOut ? "商品已售罄" : "加入兑换计划"}" ${soldOut ? "disabled" : ""}>
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
  document.querySelectorAll("details.shop-plan[open]").forEach((plan) => shopOpenPlans.add(plan.dataset.shopPlan));
  const plans = config.shop_exchange?.plans || [];
  list.innerHTML = plans.length
    ? plans.map((plan, index) => shopPlanRow(plan, index)).join("")
    : `<div class="empty-state">
        <strong>暂无兑换计划</strong>
        <span>从商品列表加入计划后，可设置账号、时间和可选的收货地址或游戏角色。</span>
      </div>`;
  bindShopPlanEvents();
}

function shopPlanRow(plan, index) {
  const accounts = config.accounts || [];
  const paused = plan.enable === false;
  const open = shopOpenPlans.has(String(index)) ? "open" : "";
  const roleDisplay = shopRoleDisplay(plan);
  const serverDisplay = shopServerDisplay(plan);
  const accountOptions = accounts.length
    ? accounts
        .map((account, accountIndex) => {
          const selected = Number(plan.account_index || 0) === accountIndex ? "selected" : "";
          return `<option value="${accountIndex}" ${selected}>${escapeHtml(accountLabel(account))}</option>`;
        })
        .join("")
    : `<option value="0">暂无账号</option>`;
  return `
    <details class="shop-plan ${paused ? "is-paused" : ""}" data-shop-plan="${index}" ${open}>
      <summary class="shop-plan-summary">
        <span class="shop-plan-title">
          <strong>${escapeHtml(plan.goods_name || plan.goods_id)}</strong>
          <small>${escapeHtml(shopPlanStatus(plan))}</small>
        </span>
        <span class="shop-plan-badges">
          <span class="plan-badge ${paused ? "paused" : "active"}">${paused ? "已暂停" : "自动"}</span>
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
          <select data-shop-plan-field="account_index" data-autosave>${accountOptions}</select>
        </label>
        <label>
          <span>兑换时间</span>
          <input data-shop-plan-field="exchange_at" type="datetime-local" value="${escapeAttr(timestampToLocalInput(plan.exchange_at))}" data-autosave />
        </label>
        <label>
          <span>收货地址 ID</span>
          <input data-shop-plan-field="address_id" type="text" value="${escapeAttr(plan.address_id || "")}" placeholder="实体商品可填" data-autosave />
        </label>
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
      <input data-shop-plan-field="uid" type="hidden" value="${escapeAttr(plan.uid || "")}" />
      <input data-shop-plan-field="region" type="hidden" value="${escapeAttr(plan.region || "")}" />
      <input data-shop-plan-field="game_biz" type="hidden" value="${escapeAttr(plan.game_biz || "")}" />
      <input data-shop-plan-field="role_name" type="hidden" value="${escapeAttr(plan.role_name || "")}" />
      <input data-shop-plan-field="region_name" type="hidden" value="${escapeAttr(plan.region_name || "")}" />
      <input data-shop-plan-field="last_result" type="hidden" value="${escapeAttr(plan.last_result || "")}" />
      <input data-shop-plan-field="last_attempt_key" type="hidden" value="${escapeAttr(plan.last_attempt_key || "")}" />
      <input data-shop-plan-field="last_run" type="hidden" value="${escapeAttr(plan.last_run || "")}" />
      <div class="shop-plan-foot">
        <span>${escapeHtml(shopPlanStatus(plan))}</span>
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
      withButtonLoading(button, "添加中", () => addShopPlan(shopGoods[Number(button.dataset.shopAdd)]))
    );
  });
  document.querySelectorAll("[data-shop-now]").forEach((button) => {
    button.addEventListener("click", () => exchangeGoodNow(shopGoods[Number(button.dataset.shopNow)]).catch((error) => showToast(error.message)));
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
      withButtonLoading(button, "兑换中", () => exchangePlanNow(Number(button.dataset.shopPlanNow)));
    });
  });
  document.querySelectorAll('[data-shop-plan-field="account_index"]').forEach((select) => {
    select.addEventListener("change", () => {
      const row = select.closest("[data-shop-plan]");
      refreshShopPlanRole(Number(row?.dataset.shopPlan)).catch((error) => showToast(error.message));
    });
  });
}

function collectShopExchange() {
  const existing = config?.shop_exchange || {};
  const shop = {
    ...(existing || {}),
    enable: Boolean($("shopEnable")?.checked ?? existing.enable ?? false),
    retry_seconds: Number($("shopRetrySeconds")?.value || existing.retry_seconds || 5),
    retry_interval: Number($("shopRetryInterval")?.value || existing.retry_interval || 0.4),
    plans: [],
  };
  document.querySelectorAll("[data-shop-plan]").forEach((row) => {
    const plan = {};
    row.querySelectorAll("[data-shop-plan-field]").forEach((field) => {
      const key = field.dataset.shopPlanField;
      if (key === "enable") plan[key] = field.checked;
      else if (key === "account_index" || key === "price") plan[key] = Number(field.value || 0);
      else if (key === "exchange_at") plan[key] = localInputToTimestamp(field.value);
      else if (key === "auto") plan[key] = field.value !== "false";
      else plan[key] = field.value.trim();
    });
    if (plan.goods_id) shop.plans.push(plan);
  });
  return shop;
}

async function addShopPlan(good) {
  if (!good) return;
  if (isShopGoodSoldOut(good)) throw new Error("商品已售罄，不能加入兑换计划");
  collectConfig();
  config.shop_exchange = config.shop_exchange || { enable: false, retry_seconds: 5, retry_interval: 0.4, plans: [] };
  const firstAccountIndex = Math.max((config.accounts || []).findIndex((account) => account.stuid), 0);
  if (!(config.accounts || [])[firstAccountIndex]?.stuid) {
    throw new Error("请先添加并登录账号");
  }
  const plan = await buildShopPlan(good, firstAccountIndex);
  const existingIndex = config.shop_exchange.plans.findIndex((plan) => plan.goods_id === good.goods_id);
  if (existingIndex >= 0) {
    config.shop_exchange.plans[existingIndex] = { ...config.shop_exchange.plans[existingIndex], ...plan };
  } else {
    config.shop_exchange.plans.push(plan);
  }
  renderShopPlans();
  saveConfig("已加入兑换计划").catch((error) => showToast(error.message));
}

async function loadShopGoods() {
  const game = $("shopGameFilter")?.value ?? shopSelectedGame;
  const loadSeq = ++shopGoodsLoadSeq;
  shopSelectedGame = game;
  shopGoodsLoading = true;
  renderShopConfig();
  try {
    const data = await api(`/api/shop/goods?game=${encodeURIComponent(game)}`);
    if (loadSeq !== shopGoodsLoadSeq) return;
    shopGoods = data.goods || [];
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
  const body = typeof planOrIndex === "number" ? { plan_index: planOrIndex } : { plan: planOrIndex };
  if (body.plan === null || body.plan === undefined) throw new Error("兑换计划不存在");
  const response = await api("/api/shop/exchange", { method: "POST", body: JSON.stringify(body) });
  const result = response.result || {};
  if (response.config) {
    config = response.config;
    config.accounts = (config.accounts || []).map((account) => ({ ...account, _draft: false }));
    renderConfig();
  }
  showToast(`兑换请求完成：${result.message || "未知结果"}`);
  await refreshStatus();
}

async function buildShopPlan(good, accountIndex) {
  await api("/api/shop/device-fp");
  const detail = await api(`/api/shop/good-detail?goods_id=${encodeURIComponent(good.goods_id)}`);
  const base = { ...good, ...detail };
  const plan = {
    enable: true,
    auto: true,
    account_index: accountIndex,
    goods_id: base.goods_id,
    goods_name: base.goods_name,
    icon: base.icon,
    price: base.price,
    stock: base.stock,
    exchange_at: base.exchange_timestamp || Math.floor(Date.now() / 1000),
    game_biz: base.game_biz || "",
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
    const meta = await api(`/api/shop/account-meta?account_index=${accountIndex}&game_biz=${encodeURIComponent(plan.game_biz)}`);
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
  const meta = await api(`/api/shop/account-meta?account_index=${plan.account_index}&game_biz=${encodeURIComponent(plan.game_biz)}`);
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

function shopRoleDisplay(plan) {
  if (!plan.uid) return "不需要";
  return [plan.role_name, plan.uid].filter(Boolean).join(" / ") || plan.uid;
}

function shopServerDisplay(plan) {
  if (!plan.region && !plan.game_biz) return "不需要";
  const readable = plan.region_name ? `${plan.region_name}${plan.region ? ` (${plan.region})` : ""}` : plan.region;
  return [readable, plan.game_biz].filter(Boolean).join(" / ");
}

function isShopGoodSoldOut(good) {
  return Boolean(good?.sold_out);
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
          <select id="shopExchangeAccountSelect">
            ${choices
              .map(({ account, index }) => `<option value="${index}">${escapeHtml(accountLabel(account))}</option>`)
              .join("")}
          </select>
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
    overlay.querySelector("[data-modal-confirm]")?.addEventListener("click", () => finish(Number(select.value)));
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

function shopPlanStatus(plan) {
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
  const timestamp = Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour) - 8, Number(minute), 0);
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
  $("scheduleMetric").textContent = scheduler.running ? "执行中" : scheduler.enabled ? "已启用" : "已关闭";
  $("nextRun").textContent = formatTime(scheduler.next_run);
  $("lastResult").textContent = latestResultText(scheduler, login, logs);
  if ($("shopScheduleMetric")) {
    $("shopScheduleMetric").textContent = exchangeScheduler.running
      ? "兑换中"
      : exchangeScheduler.enabled
        ? "已启用"
        : "已关闭";
  }
  if ($("shopNextRun")) {
    $("shopNextRun").textContent = formatTime(exchangeScheduler.next_run);
  }
  if (shopExchange && config && !shopRequestInFlight && !isEditingShopConfig()) {
    config.shop_exchange = shopExchange;
    renderShopConfig();
  }
  updateLogs(logs);

  if (login.running || login.status === "error") {
    activeLoginIndex = login.account_index ?? activeLoginIndex;
  }
  renderLoginSlot(login);
  $("runBtn").disabled = Boolean(scheduler.running);
  document.querySelectorAll("[data-login]").forEach((button) => {
    button.disabled = Boolean(login.running);
  });
  if (login.status === "success" && lastLoginStatus !== "success") {
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
  return Boolean(active?.matches?.("[data-shop-plan-field], #shopEnable, #shopRetrySeconds, #shopRetryInterval"));
}

function renderLoginSlot(login) {
  document.querySelectorAll("[data-login-slot]").forEach((slot) => {
    slot.innerHTML = "";
    slot.classList.remove("active");
  });
  if (!login.running && !login.qr && login.status !== "error" && activeLoginIndex === null) {
    return;
  }
  const index = login.account_index ?? activeLoginIndex ?? -1;
  const slot = document.querySelector(`[data-login-slot="${index}"]`);
  if (!slot) return;
  slot.classList.add("active");
  if (login.qr) {
    slot.innerHTML = `
      <div class="inline-login">
        <img src="${login.qr}" alt="米游社扫码登录二维码" />
        <p>${escapeHtml(login.message || "等待扫码确认")}</p>
      </div>
    `;
  } else {
    slot.innerHTML = `
      <div class="inline-login pending">
        <div class="qr-loading"></div>
        <p>${escapeHtml(login.message || loginStatusText(login.status || "starting"))}</p>
      </div>
    `;
  }
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

async function startLogin(accountIndex) {
  collectConfig();
  const account = config.accounts[accountIndex];
  if (!account) {
    throw new Error("请先添加账号");
  }
  lastLoginStatus = "";
  activeLoginIndex = accountIndex;
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
  const row = document.querySelector(`.account-row[data-index="${editingAccountIndex}"]`);
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
  const names = new Set((config.accounts || []).map((account) => account.name).filter(Boolean));
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
    return /任务汇总|签到汇总|签到成功|社区任务结束|获得|任务执行完成|登录成功|失败|触发验证码/.test(line);
  });
  if (latest) {
    if (latest.includes("云游戏成功项")) return "云游戏成功";
    if (latest.includes("云游戏失败项")) return "云游戏部分失败";
    if (latest.includes("游戏社区成功项") || latest.includes("游戏成功项")) return "社区签到成功";
    if (latest.includes("游戏社区失败项") || latest.includes("游戏失败项")) return "社区部分失败";
    if (latest.includes("米游币任务汇总")) {
      const points = latest.match(/实际已获得\s*([^，\s]+)/);
      return points ? `米游币 ${points[1]}` : "米游币完成";
    }
    if (latest.includes("云游戏签到汇总")) return latest.includes("失败 0") ? "云游戏成功" : "云游戏部分失败";
    if (latest.includes("游戏社区签到汇总") || latest.includes("游戏签到汇总")) {
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
  if (login.status && login.status !== "idle") return loginStatusText(login.status);
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
    actions.classList.toggle("is-hidden", actions.dataset.viewActions !== activeView);
  });
  if (activeView === "shop" && !shopGoods.length) {
    loadShopGoods().catch((error) => showToast(error.message));
  }
}

function bindEvents() {
  document.querySelectorAll("summary button, summary input").forEach((control) => {
    control.addEventListener("click", (event) => event.stopPropagation());
  });
  document.addEventListener("change", (event) => {
    if (event.target?.matches?.("[data-autosave]")) {
      if (event.target.id === "gameCheckin" || event.target.id === "cloudGameCheckin" || event.target.id === "bbsTasks") {
        updateTaskDependencyState();
      }
      scheduleAutoSave();
    }
  });
  document.addEventListener("input", (event) => {
    if (
      event.target?.matches?.(
        'input[type="time"][data-autosave], input[type="datetime-local"][data-autosave], input[type="number"][data-autosave], input[type="text"][data-autosave], select[data-autosave], [data-account-cloud-token][data-autosave]'
      )
    ) {
      scheduleAutoSave();
    }
  });
  $("refreshBtn").addEventListener("click", () => {
    Promise.all([loadConfig(), refreshStatus()]).catch((error) => showToast(error.message));
  });
  $("runBtn").addEventListener("click", () => runNow().catch((error) => showToast(error.message)));
  $("logs").addEventListener("scroll", () => {
    logsPinnedToBottom = isScrolledNearBottom($("logs"));
  });
  $("addAccountBtn").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    addAccount();
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  $("shopRefreshBtn")?.addEventListener("click", () => loadShopGoods().catch((error) => showToast(error.message)));
  $("shopGameFilter")?.addEventListener("change", () => loadShopGoods().catch((error) => showToast(error.message)));
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

  const subtitle = passwordSet ? "请输入访问密码" : "首次使用，请设置访问密码";
  const buttonText = passwordSet ? "登录" : "设置密码";
  const inputPlaceholder = passwordSet ? "输入密码" : "设置密码（至少 4 位）";

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
    if (!passwordSet && password.length < 4) {
      errorEl.textContent = "密码至少 4 位";
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
