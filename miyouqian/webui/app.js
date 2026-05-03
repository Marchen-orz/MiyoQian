const gameOptions = [
  ["genshin", "原神"],
  ["starrail", "星穹铁道"],
  ["zzz", "绝区零"],
  ["honkai3rd", "崩坏3"],
  ["tears", "未定事件簿"],
  ["honkai2", "崩坏学园2"],
];

const pushChannelOptions = [
  ["pushplus", "pushplus"],
  ["telegram", "Telegram"],
  ["dingrobot", "钉钉机器人"],
  ["feishubot", "飞书机器人"],
  ["email", "邮箱"],
];

let config = null;
let toastTimer = null;
let autoSaveTimer = null;
let isSavingConfig = false;
let lastLoginStatus = "";
let activeLoginIndex = null;
let editingAccountIndex = null;
let editingPushProviders = new Set();
let logsPinnedToBottom = true;

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
  $("bbsTasks").checked = Boolean(config.features?.bbs_tasks ?? false);
  $("bbsCheckin").checked = Boolean(config.bbs?.checkin ?? true);
  $("bbsRead").checked = Boolean(config.bbs?.read ?? true);
  $("bbsLike").checked = Boolean(config.bbs?.like ?? true);
  $("bbsShare").checked = Boolean(config.bbs?.share ?? true);

  $("pushErrorOnly").checked = Boolean(config.push?.error_only ?? false);

  renderGames();
  renderPushChannels();
  updateTaskDependencyState();
  renderAccounts();
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

function updateTaskDependencyState() {
  const gameEnabled = $("gameCheckin").checked;
  const bbsEnabled = $("bbsTasks").checked;
  setTaskGroupDisabled("gameTaskGroup", "[data-game]", !gameEnabled);
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
  return Object.entries(channel)
    .filter(([key]) => key !== "provider" && key !== "enable")
    .map(([key, value]) => `<input data-push-field="${key}" type="hidden" value="${escapeAttr(value ?? "")}" />`)
    .join("");
}

function emptyPushChannel(provider) {
  return {
    provider,
    enable: true,
    token: "",
    webhook: "",
    api_url: "",
    topic: "",
    chat_id: "",
    secret: "",
    smtp_host: "",
    smtp_port: 465,
    smtp_user: "",
    smtp_password: "",
    mail_from: "",
    mail_to: "",
    smtp_ssl: true,
  };
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
              <button class="ghost icon-only" type="button" data-remove="${index}" title="删除账号">
                <svg><use href="#i-trash"></use></svg>
              </button>
            </div>
          </div>
          <input data-field="stuid" type="hidden" value="${escapeAttr(account.stuid || "")}" />
          <input data-field="stoken" type="hidden" value="${escapeAttr(account.stoken || "")}" />
          <input data-field="mid" type="hidden" value="${escapeAttr(account.mid || "")}" />
          <textarea class="hidden-field" data-field="cookie">${escapeHtml(account.cookie || "")}</textarea>
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
  document.querySelectorAll("[data-cancel-account]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.cancelAccount);
      if (config.accounts[index]?._draft) {
        config.accounts.splice(index, 1);
        editingAccountIndex = null;
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
      renderAccounts();
      if (!removed?._draft) {
        autoSaveConfig()
          .then(() => showToast("账号已删除"))
          .catch((error) => showToast(error.message));
      }
    });
  });
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
    bbs_tasks: $("bbsTasks").checked,
  };
  config.games = config.games || {};
  config.games.enabled = Array.from(document.querySelectorAll("[data-game]:checked")).map((input) => input.dataset.game);
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
  config.push.channels = Array.from(document.querySelectorAll(".push-channel"))
    .map((row) => collectPushChannel(row))
    .filter(Boolean);
  config.push.enable = config.push.channels.some((channel) => channel.enable);
  config.accounts = Array.from(document.querySelectorAll(".account-row")).map((row) => {
    const item = {};
    row.querySelectorAll("[data-field]").forEach((field) => {
      item[field.dataset.field] = field.value.trim();
    });
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
  const login = status.login || {};
  const logs = status.logs || [];
  const accounts = config?.accounts || [];
  const loggedIn = accounts.filter((account) => account.stuid).length;
  $("accountMetric").textContent = `${loggedIn}/${accounts.length}`;
  $("scheduleMetric").textContent = scheduler.running ? "执行中" : scheduler.enabled ? "已启用" : "已关闭";
  $("nextRun").textContent = formatTime(scheduler.next_run);
  $("lastResult").textContent = latestResultText(scheduler, login, logs);
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
  return { name, cookie: "", stuid: "", stoken: "", mid: "", _draft: true };
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
    return /任务汇总|签到成功|社区任务结束|获得|任务执行完成|登录成功|失败|触发验证码/.test(line);
  });
  if (latest) {
    if (latest.includes("米游币任务汇总")) {
      const points = latest.match(/实际已获得\s*([^，\s]+)/);
      return points ? `米游币 ${points[1]}` : "米游币完成";
    }
    if (latest.includes("游戏签到汇总")) return latest.includes("失败 0") ? "签到成功" : "部分失败";
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

function bindEvents() {
  document.querySelectorAll("summary button, summary input").forEach((control) => {
    control.addEventListener("click", (event) => event.stopPropagation());
  });
  document.addEventListener("change", (event) => {
    if (event.target?.matches?.("[data-autosave]")) {
      if (event.target.id === "gameCheckin" || event.target.id === "bbsTasks") {
        updateTaskDependencyState();
      }
      scheduleAutoSave();
    }
  });
  document.addEventListener("input", (event) => {
    if (event.target?.matches?.('input[type="time"][data-autosave], input[type="number"][data-autosave]')) {
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
}

bindEvents();

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
