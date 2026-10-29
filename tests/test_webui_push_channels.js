const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Exercise the browser's real form helpers without starting authentication or polling.
const source = fs.readFileSync(
  path.join(__dirname, "../miyouqian/webui/app.js"),
  "utf8",
);
assert.match(source, /\ncheckAuthAndInit\(\);\s*$/);
const ui = vm.createContext({
  document: {
    querySelectorAll: () => [],
    getElementById: () => ({ addEventListener() {} }),
    addEventListener() {},
  },
});
vm.runInContext(source.replace(/\ncheckAuthAndInit\(\);\s*$/, "\n"), ui);

function collect(html, enabled = true) {
  const fields = Array.from(html.matchAll(/<input\b([^>]*)>/g), ([, attributes]) => {
    const attr = (name) => attributes.match(new RegExp(`${name}="([^"]*)"`))?.[1];
    return {
      dataset: { pushField: attr("data-push-field") },
      type: attr("type"),
      tagName: "INPUT",
      value: attr("value") || "",
      checked: /\schecked(?:\s|$)/.test(attributes),
    };
  });
  return ui.cleanPushChannel(ui.collectPushChannel({
    dataset: { pushProvider: "wecombot" },
    querySelector: () => ({ checked: enabled }),
    querySelectorAll: () => fields,
  }));
}

test("existing WeCom channels default to Markdown and show an unchecked toggle", () => {
  const channel = { provider: "wecombot", enable: true, webhook: "https://example.invalid/bot" };
  assert.equal(ui.cleanPushChannel(channel).plain_text, false);
  const html = ui.pushChannelFields("wecombot", channel);
  assert.match(html, /纯文本消息（兼容微信）/);
  assert.equal(collect(html).plain_text, false);
});

for (const plainText of [true, false]) {
  test(`WeCom plain_text=${plainText} survives editing, saving and reloading`, () => {
    const channel = {
      provider: "wecombot", enable: true,
      webhook: "https://example.invalid/bot", plain_text: plainText,
    };
    const saved = collect(ui.pushChannelFields("wecombot", channel));
    assert.equal(saved.plain_text, plainText);
    assert.equal(saved.webhook, channel.webhook);
    const reloaded = JSON.parse(JSON.stringify(saved));
    assert.equal(collect(ui.pushChannelFields("wecombot", reloaded)).plain_text, plainText);
    // A subsequent unrelated save collects string-valued hidden fields.
    assert.equal(collect(ui.pushChannelHiddenFields(reloaded)).plain_text, plainText);
  });

  test(`disabling a configured channel retains plain_text=${plainText}`, () => {
    const channel = {
      provider: "wecombot", enable: false,
      webhook: "https://example.invalid/bot", plain_text: plainText,
    };
    const saved = collect(ui.pushChannelHiddenFields(channel), false);
    assert.equal(saved.enable, false);
    assert.equal(saved.plain_text, plainText);
    assert.equal(ui.shouldSavePushChannel(saved), true);
  });
}

test("unchecking the plain-text toggle restores Markdown", () => {
  const html = ui.pushChannelFields("wecombot", {
    provider: "wecombot", enable: true,
    webhook: "https://example.invalid/bot", plain_text: true,
  });
  const saved = collect(html.replace(/\schecked(?=\s*\/?>)/g, ""));
  assert.equal(saved.plain_text, false);
  assert.equal(collect(ui.pushChannelHiddenFields(saved)).plain_text, false);
});

test("the default false flag does not retain an empty disabled channel", () => {
  const saved = collect(ui.pushChannelFields("wecombot", ui.emptyPushChannel("wecombot")), false);
  assert.equal(saved.plain_text, false);
  assert.equal(ui.shouldSavePushChannel(saved), false);
});

test("an explicitly enabled plain-text preference is retained before adding a webhook", () => {
  const saved = collect(ui.pushChannelFields("wecombot", {
    provider: "wecombot", enable: false, plain_text: true,
  }), false);
  assert.equal(saved.plain_text, true);
  assert.equal(ui.shouldSavePushChannel(saved), true);
});

// ---------------------------------------------------------------------------
// QQ 开放平台官方机器人（qqbot）
// ---------------------------------------------------------------------------

function collectProvider(provider, html, enabled = true) {
  const fields = Array.from(html.matchAll(/<input\b([^>]*)>/g), ([, attributes]) => {
    const attr = (name) => attributes.match(new RegExp(`${name}="([^"]*)"`))?.[1];
    return {
      dataset: { pushField: attr("data-push-field") },
      type: attr("type"),
      tagName: "INPUT",
      value: attr("value") || "",
      checked: /\schecked(?:\s|$)/.test(attributes),
    };
  });
  // <select> 的值来自被 selected 的 option，而不是 value 属性
  const selects = Array.from(html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g), ([, attributes, body]) => ({
    dataset: { pushField: attributes.match(/data-push-field="([^"]*)"/)?.[1] },
    type: "select-one",
    tagName: "SELECT",
    value: body.match(/<option value="([^"]*)"[^>]*selected/)?.[1] || "",
    checked: false,
  }));
  return ui.cleanPushChannel(ui.collectPushChannel({
    dataset: { pushProvider: provider },
    querySelector: () => ({ checked: enabled }),
    querySelectorAll: () => fields.concat(selects),
  }));
}

test("qqbot is offered as its own channel next to the onebot QQ channel", () => {
  const options = ui.__myqPushChannelOptions.map(([value]) => value);
  assert.ok(options.includes("qqbot"));
  // 原有 onebot 版 qq 通道必须保持不变
  assert.ok(options.includes("qq"));
});

test("every push provider has a button, so each can be tested on its own", () => {
  const providers = ui.__myqPushChannelOptions.map(([value]) => value).sort();
  // vm 里的数组原型不同，用 JSON 比较结构
  assert.equal(
    JSON.stringify(providers),
    JSON.stringify([
      "dingrobot",
      "email",
      "feishubot",
      "gotify",
      "pushplus",
      "qq",
      "qqbot",
      "serverchan",
      "telegram",
      "wecombot",
    ]),
  );
});

test("the qqbot form exposes AppID, AppSecret and both binding buttons", () => {
  const html = ui.pushChannelFields("qqbot", { provider: "qqbot", enable: true });
  assert.match(html, /AppID/);
  assert.match(html, /AppSecret/);
  assert.match(html, /data-push-field="user_openid"/);
  assert.match(html, /data-push-field="group_openid"/);
  assert.match(html, /data-qqbind="user"/);
  assert.match(html, /data-qqbind="group"/);
  // OpenID 允许手填，绑定只是可选的便捷方式，不能设成只读
  assert.equal(html.includes("readonly"), false);
});

test("a hand-typed OpenID is kept as-is", () => {
  const channel = {
    provider: "qqbot", enable: true, app_id: "102000000", client_secret: "sec",
    user_openid: "HAND_TYPED_OPENID", group_openid: "HAND_TYPED_GROUP",
    message_format: "text", api_base: "",
  };
  const saved = collectProvider("qqbot", ui.pushChannelFields("qqbot", channel));
  assert.equal(saved.user_openid, "HAND_TYPED_OPENID");
  assert.equal(saved.group_openid, "HAND_TYPED_GROUP");
  assert.equal(ui.shouldSavePushChannel(saved), true);
  // 手填的 OpenID 也要能原样往返，不能被清掉
  const reloaded = JSON.parse(JSON.stringify(saved));
  assert.equal(
    collectProvider("qqbot", ui.pushChannelHiddenFields(reloaded)).user_openid,
    "HAND_TYPED_OPENID",
  );
});

test("a configured qqbot channel survives editing, saving and reloading", () => {
  const channel = {
    provider: "qqbot", enable: true,
    app_id: "102000000", client_secret: "sec",
    user_openid: "U_OPENID_1", group_openid: "G_OPENID_2",
    message_format: "markdown", api_base: "",
  };
  const saved = collectProvider("qqbot", ui.pushChannelFields("qqbot", channel));
  assert.equal(saved.app_id, channel.app_id);
  assert.equal(saved.client_secret, channel.client_secret);
  assert.equal(saved.user_openid, channel.user_openid);
  assert.equal(saved.group_openid, channel.group_openid);
  assert.equal(saved.message_format, "markdown");

  const reloaded = JSON.parse(JSON.stringify(saved));
  // vm 里造出来的对象原型和这里不同，用 JSON 比较结构
  assert.equal(JSON.stringify(collectProvider("qqbot", ui.pushChannelFields("qqbot", reloaded))), JSON.stringify(reloaded));
  // 后续无关保存走隐藏字段，绑定结果不能被丢掉
  assert.equal(JSON.stringify(collectProvider("qqbot", ui.pushChannelHiddenFields(reloaded))), JSON.stringify(reloaded));
});

test("an unknown message format is normalized back to text", () => {
  assert.equal(ui.cleanPushChannel({ provider: "qqbot", message_format: "html" }).message_format, "text");
  assert.equal(ui.cleanPushChannel({ provider: "qqbot" }).message_format, "text");
});

test("the default text format alone does not retain an empty channel", () => {
  const empty = collectProvider("qqbot", ui.pushChannelFields("qqbot", ui.emptyPushChannel("qqbot")), false);
  assert.equal(empty.message_format, "text");
  assert.equal(ui.shouldSavePushChannel(empty), false);
  // 但填了 AppID 就应该保留，否则用户配到一半刷新就没了
  assert.equal(ui.shouldSavePushChannel({ ...empty, app_id: "1" }), true);
  assert.equal(ui.shouldSavePushChannel({ ...empty, user_openid: "u" }), true);
  assert.equal(ui.shouldSavePushChannel({ ...empty, message_format: "markdown" }), true);
});

test("a bound OpenID is recognised as configured without other fields", () => {
  assert.equal(ui.hasPushChannelConfig({ provider: "qqbot", user_openid: "u" }), true);
  assert.equal(ui.hasPushChannelConfig({ provider: "qqbot", group_openid: "g" }), true);
  assert.equal(ui.hasPushChannelConfig({ provider: "qqbot", message_format: "text" }), false);
});

test("the QQ push-type dropdown alone does not count as a configured channel", () => {
  // 下拉框总有值，只选了推送方式不应该让空通道显示成「已关闭」或通过测试前的参数检查
  const empty = { provider: "qq", enable: false, msg_type: "group" };
  assert.equal(ui.hasPushChannelConfig(empty), false);
  assert.equal(ui.shouldSavePushChannel(empty), false);
  assert.equal(ui.hasPushChannelConfig({ ...empty, push_url: "http://127.0.0.1:3000" }), true);
  assert.equal(ui.shouldSavePushChannel({ ...empty, push_url: "http://127.0.0.1:3000" }), true);
});

test("gotify priority 0 survives rendering, saving and reloading instead of falling back to 5", () => {
  const channel = { provider: "gotify", enable: true, server: "https://g.example.com", token: "t", priority: 0 };
  const html = ui.pushChannelFields("gotify", channel);
  assert.match(html, /data-push-field="priority"[^>]*value="0"/);
  const saved = collectProvider("gotify", html);
  assert.equal(saved.priority, "0");
  // 后续无关保存走隐藏字段，数字 0 也不能被当成空值丢掉
  assert.equal(collectProvider("gotify", ui.pushChannelHiddenFields(channel)).priority, "0");
  assert.equal(ui.cleanPushChannel(channel).priority, "0");
});

test("gotify priority input is bounded to 0-10 and defaults to 5", () => {
  const html = ui.pushChannelFields("gotify", { provider: "gotify", enable: true });
  assert.match(html, /data-push-field="priority"[^>]*value="5"[^>]*min="0" max="10" step="1"/);
  assert.equal(collectProvider("gotify", html).priority, "5");
});

test("the gotify priority default alone does not retain an empty channel", () => {
  const empty = collectProvider("gotify", ui.pushChannelFields("gotify", ui.emptyPushChannel("gotify")), false);
  assert.equal(empty.priority, "5");
  assert.equal(ui.shouldSavePushChannel(empty), false);
  assert.equal(ui.hasPushChannelConfig(empty), false);
  assert.equal(ui.shouldSavePushChannel({ ...empty, server: "https://g.example.com" }), true);
  // 留空等于没填，同样补成默认值
  assert.equal(ui.cleanPushChannel({ ...empty, priority: "" }).priority, "5");
});

test("a non-default gotify priority counts as configured, like the backend", () => {
  const empty = collectProvider("gotify", ui.pushChannelFields("gotify", ui.emptyPushChannel("gotify")), false);
  for (const priority of ["0", "8", 0, 8]) {
    assert.equal(ui.shouldSavePushChannel({ ...empty, priority }), true, String(priority));
    assert.equal(ui.hasPushChannelConfig({ ...empty, priority }), true, String(priority));
  }
});

test("channel defaults match the backend's PUSH_CHANNEL_DEFAULTS", (t) => {
  const root = path.join(__dirname, "..");
  const run = spawnSync(
    process.env.PYTHON || "python",
    ["-c", "import json; from miyouqian.core.config import PUSH_CHANNEL_DEFAULTS as d; print(json.dumps(d))"],
    { cwd: root, env: { ...process.env, PYTHONPATH: root }, encoding: "utf8" },
  );
  if (run.error || run.status !== 0) {
    t.skip(`python is not available to read the backend defaults: ${run.error?.message || run.stderr}`);
    return;
  }
  const backend = JSON.parse(run.stdout);
  // 前端统一用字符串；vm 里的对象原型不同，用 JSON 比较结构
  const stringified = Object.fromEntries(
    Object.entries(backend).map(([provider, fields]) => [
      provider,
      Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, String(value)])),
    ]),
  );
  assert.equal(JSON.stringify(ui.__myqPushChannelDefaults), JSON.stringify(stringified));
});

test("a backdrop click closes the dialog only when the press started on the backdrop", () => {
  const handlers = {};
  const overlay = { addEventListener: (type, fn) => { handlers[type] = fn; } };
  let closed = 0;
  ui.closeOnBackdropClick(overlay, () => { closed += 1; });
  // 在输入框里按下、拖到遮罩上松手：浏览器照样会在遮罩上触发 click
  handlers.mousedown({ target: {} });
  handlers.click({ target: overlay });
  assert.equal(closed, 0);
  handlers.mousedown({ target: overlay });
  handlers.click({ target: overlay });
  assert.equal(closed, 1);
});

test("unsaved dialog input goes into the draft and never into config", () => {
  const field = { dataset: { pushField: "app_id" }, type: "text", tagName: "INPUT", value: " 102000000 ", checked: false };
  const card = {
    dataset: { pushProvider: "qqbot" },
    querySelector: (selector) => (selector === "[data-push-field]" ? field : { checked: true }),
    querySelectorAll: () => [field],
  };
  ui.fakeModal = { querySelector: () => card };
  vm.runInContext(
    "config = { push: { channels: [] } }; pushModalProvider = 'qqbot'; pushModalEl = fakeModal; pushModalDraft = null;",
    ui,
  );
  try {
    const draft = ui.captureModalDraft();
    assert.equal(draft.app_id, "102000000");
    assert.equal(draft.enable, true);
    assert.equal(vm.runInContext("pushModalDraft.app_id", ui), "102000000");
    assert.equal(vm.runInContext("JSON.stringify(config.push.channels)", ui), "[]");
  } finally {
    vm.runInContext("config = null; pushModalProvider = null; pushModalEl = null; pushModalDraft = null;", ui);
  }
});

test("every push provider has a small icon file in the web assets", () => {
  for (const [provider] of ui.__myqPushChannelOptions) {
    const src = ui.pushChannelIcon(provider).match(/src="([^"]+)"/)?.[1];
    assert.ok(src, `${provider} has no icon`);
    assert.ok(src.startsWith("/assets/push/"), src);
    const file = path.join(__dirname, "../miyouqian/webui", src);
    assert.ok(fs.existsSync(file), `${src} is missing`);
    assert.ok(fs.statSync(file).size < 8 * 1024, `${src} is too big for a 24px icon`);
  }
  assert.equal(ui.pushChannelIcon("not-a-provider"), "");
});

test("cloud games use the shared choice-toggle style and keep the starrail entry disabled", () => {
  const host = { innerHTML: "" };
  const realDocument = ui.document;
  // 只留下渲染需要的最小 DOM；任务开关不存在时依赖状态更新会直接跳过
  ui.document = { ...realDocument, getElementById: (id) => (id === "cloudGameChips" ? host : null) };
  vm.runInContext("config = { cloud_games: { enabled: ['genshin'] } };", ui);
  try {
    ui.renderCloudGames();
  } finally {
    ui.document = realDocument;
    vm.runInContext("config = null;", ui);
  }
  const labels = Array.from(host.innerHTML.matchAll(/<label\b[^>]*>[\s\S]*?<\/label>/g), ([html]) => html);
  assert.equal(labels.length, 3);
  for (const html of labels) assert.match(html, /^<label class="choice-toggle\b/);
  assert.doesNotMatch(host.innerHTML, /\bchips?\b/);
  assert.match(labels[0], /data-cloud-game="genshin"[^>]*\schecked/);
  assert.doesNotMatch(labels[1], /\schecked/);
  assert.match(labels[2], /class="choice-toggle is-disabled"/);
  assert.match(labels[2], /title="云星穹铁道是版本更新赠送/);
  assert.match(labels[2], /data-cloud-game-disabled="1" disabled/);
});

test("no multi-select control falls back to the native checkbox look or the old chip style", () => {
  const css = fs.readFileSync(path.join(__dirname, "../miyouqian/webui/app.css"), "utf8");
  assert.doesNotMatch(css, /accent-color/);
  assert.doesNotMatch(css, /\.chips?\b/);
  assert.doesNotMatch(source, /class="chip\b|class="chips\b/);
  // 勾选框和按钮式多选都从同一个对勾图标取形状
  assert.equal(css.match(/--check-icon:/g)?.length, 1);
  assert.match(css, /\.check-row input\[type="checkbox"\]::after \{[^}]*var\(--check-icon\)/);
  assert.match(css, /\.choice-toggle input:checked \+ span::before \{[^}]*var\(--check-icon\)/);
});

test("the exchange view is tagged so the one-screen layout CSS can find it", () => {
  const html = fs.readFileSync(path.join(__dirname, "../miyouqian/webui/index.html"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../miyouqian/webui/app.css"), "utf8");
  assert.match(html, /class="view-panel shop-view[^"]*" data-view-panel="shop"/);
  assert.match(css, /\.shell:has\(\.shop-view:not\(\.is-hidden\)\)/);
  // 筛选框宽度交给样式表，不再写在标签上
  assert.doesNotMatch(html, /class="select-wrapper"[^>]*style=/);
});

test("a sold-out good shows the sold-out label only once, in its meta row", () => {
  const html = ui.shopGoodCard(
    { goods_id: "1", goods_name: "护身符", price: 7900, stock: "0", limit: "永久 0/1", sold_out: true, display_status: "sold_out_with_next" },
    0,
  );
  assert.match(html, /<span class="sold-out">已售罄<\/span>/);
  const title = html.match(/<div class="shop-good-title">([\s\S]*?)<\/div>/)[1];
  assert.doesNotMatch(title, /已售罄/);
});

// 临时换上一个最小的 document / 全局对象，用完还原，不影响其它用例
function withGlobals(overrides, run) {
  const saved = {};
  for (const key of Object.keys(overrides)) saved[key] = ui[key];
  Object.assign(ui, overrides);
  try {
    return run();
  } finally {
    for (const key of Object.keys(overrides)) {
      if (saved[key] === undefined) delete ui[key];
      else ui[key] = saved[key];
    }
  }
}

function renderAccountList(count, { previousScroll = 0 } = {}) {
  const accounts = Array.from({ length: count }, (_, i) => ({
    name: `账号${i + 1}`,
    stuid: String(300000000 + i),
    stoken: "x",
    cloud_games: { tokens: {} },
  }));
  let list = { scrollTop: previousScroll };
  const host = {
    html: "",
    get innerHTML() {
      return this.html;
    },
    set innerHTML(value) {
      this.html = value;
      list = { scrollTop: 0 }; // 重绘会得到一个全新的、滚动位置为 0 的列表
    },
  };
  vm.runInContext(`config = { accounts: ${JSON.stringify(accounts)} };`, ui);
  const document = {
    ...ui.document,
    getElementById: (id) => (id === "accounts" ? host : null),
    querySelector: (selector) => (selector === "#accounts .acc-list" ? list : null),
  };
  try {
    withGlobals({ document }, () => ui.renderAccounts());
  } finally {
    vm.runInContext("config = null;", ui);
  }
  return { html: host.html, scrollTop: list.scrollTop };
}

test("the account list scrolls only beyond three accounts and the add button stays outside it", () => {
  assert.equal(vm.runInContext("ACCOUNTS_VISIBLE", ui), 3);
  const css = fs.readFileSync(path.join(__dirname, "../miyouqian/webui/app.css"), "utf8");
  assert.match(css, /\.acc-list\.is-scrollable \{[^}]*max-height: calc\(var\(--acc-card-h\) \* 3\b/);

  for (const [count, scrollable] of [[1, false], [3, false], [4, true], [6, true]]) {
    const { html } = renderAccountList(count);
    assert.equal(/class="acc-list is-scrollable"/.test(html), scrollable, `${count} accounts`);
    assert.equal(html.match(/class="account-row\b/g)?.length, count);
    // 添加按钮在列表闭合之后，不在滚动区域里面
    assert.match(html, /<\/div>\s*<button class="acc-add-card" type="button" data-add-account>/);
    assert.ok(
      html.indexOf('class="acc-add-card"') > html.lastIndexOf('class="account-row'),
      "add button comes after every account card",
    );
  }
  // 没有账号时仍是空状态，不套滚动列表
  const empty = renderAccountList(0).html;
  assert.match(empty, /class="acc-empty"/);
  assert.doesNotMatch(empty, /acc-list/);
});

test("re-rendering the accounts keeps the list's scroll position", () => {
  assert.equal(renderAccountList(5, { previousScroll: 296 }).scrollTop, 296);
  assert.equal(renderAccountList(5).scrollTop, 0);
});

test("revealAccount scrolls a clipped card fully into the capped list", () => {
  const rect = (top, bottom) => ({ getBoundingClientRect: () => ({ top, bottom }) });
  const reveal = (rowRect, listRect, scrollTop) => {
    const list = { scrollTop, ...rect(listRect[0], listRect[1]) };
    const row = { ...rect(rowRect[0], rowRect[1]), closest: () => list };
    withGlobals({ document: { ...ui.document, querySelector: () => row } }, () => ui.revealAccount(1));
    return list.scrollTop;
  };
  // 留 3px 内边距：滚到卡片边缘离列表边缘 3px，阴影不会被裁
  assert.equal(reveal([500, 840], [300, 740], 200), 303); // 下半截被裁掉，往下滚到底边对齐
  assert.equal(reveal([200, 340], [300, 740], 200), 97); // 上半截在可视区外，往上滚到顶边对齐
  assert.equal(reveal([320, 460], [300, 740], 200), 200); // 已完整可见，不动
  assert.equal(reveal([200, 900], [300, 740], 200), 97); // 比列表还高时以顶边为准
});

test("left panels remember their open state and default to accounts and tasks only", () => {
  assert.equal(vm.runInContext("PANEL_STATE_KEY", ui), "miyouqian.panels");
  const html = fs.readFileSync(path.join(__dirname, "../miyouqian/webui/index.html"), "utf8");
  const declared = Array.from(
    html.matchAll(/<details class="panel" data-panel="(\w+)"(\s+open)?>/g),
    ([, id, open]) => [id, Boolean(open)],
  );
  assert.deepEqual(declared, [
    ["accounts", true],
    ["tasks", true],
    ["schedule", false],
    ["push", false],
    ["captcha", false],
  ]);

  const init = (stored) => {
    const panels = declared.map(([id, open]) => ({
      dataset: { panel: id },
      open,
      listeners: [],
      addEventListener(name, fn) {
        if (name === "toggle") this.listeners.push(fn);
      },
    }));
    const store = new Map(stored === undefined ? [] : [["miyouqian.panels", stored]]);
    const localStorage = {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => store.set(key, value),
    };
    const document = { ...ui.document, querySelectorAll: () => panels };
    withGlobals({ document, localStorage }, () => ui.initPanelState());
    // 点开/收起发生在初始化之后，写入时同样要有 localStorage
    const toggle = (id) => {
      const panel = panels.find((item) => item.dataset.panel === id);
      panel.open = !panel.open;
      withGlobals({ localStorage }, () => panel.listeners.forEach((fn) => fn()));
    };
    return { panels, store, toggle };
  };
  const openIds = (panels) => panels.filter((panel) => panel.open).map((panel) => panel.dataset.panel);

  // 从没用过：保持 HTML 默认，只展开前两栏，也不会凭空写入
  let { panels, store } = init();
  assert.deepEqual(openIds(panels), ["accounts", "tasks"]);
  assert.equal(store.size, 0);

  // 之前记过：按记下的状态恢复（包括把默认展开的栏收起来）
  ({ panels } = init(JSON.stringify({ accounts: false, tasks: true, schedule: true, push: false, captcha: false })));
  assert.deepEqual(openIds(panels), ["tasks", "schedule"]);

  // 记录里缺的栏保持默认；坏数据整体忽略
  ({ panels } = init(JSON.stringify({ accounts: false })));
  assert.deepEqual(openIds(panels), ["tasks"]);
  for (const broken of ["not json", "42", '"x"', JSON.stringify({ accounts: "yes" })]) {
    assert.deepEqual(openIds(init(broken).panels), ["accounts", "tasks"], broken);
  }

  // 展开/收起时把所有栏的状态整体写回
  let toggle;
  ({ store, toggle } = init());
  toggle("push");
  assert.deepEqual(JSON.parse(store.get("miyouqian.panels")), {
    accounts: true,
    tasks: true,
    schedule: false,
    push: true,
    captcha: false,
  });
});

test("the log panel fills the window below its current top edge, with a floor", () => {
  const fit = ({ top, innerHeight, innerWidth = 1400, visible = true }) => {
    const classes = new Set(["is-fitted"]);
    const side = {
      style: {
        height: "",
        removeProperty(name) {
          if (name === "height") this.height = "";
        },
      },
      classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) },
      offsetParent: visible ? {} : null,
      getBoundingClientRect: () => ({ top }),
    };
    withGlobals(
      { document: { ...ui.document, querySelector: () => side }, window: { innerHeight, innerWidth } },
      () => ui.fitLogPanel(),
    );
    return { height: side.style.height, fitted: classes.has("is-fitted") };
  };
  assert.deepEqual(fit({ top: 202, innerHeight: 803 }), { height: "577px", fitted: true }); // 页面顶部：从当前位置补到窗口底
  assert.deepEqual(fit({ top: 16, innerHeight: 803 }), { height: "763px", fitted: true }); // 已吸顶
  assert.deepEqual(fit({ top: -300, innerHeight: 803 }), { height: "763px", fitted: true }); // 顶边不会小于吸顶位置
  assert.deepEqual(fit({ top: 16, innerHeight: 300 }), { height: "320px", fitted: true }); // 窗口太矮时保底
  assert.deepEqual(fit({ top: 202, innerHeight: 803, innerWidth: 800 }), { height: "", fitted: false }); // 窄屏退回普通流
  assert.deepEqual(fit({ top: 202, innerHeight: 803, visible: false }), { height: "", fitted: false }); // 切到兑换页时不处理
});

// withGlobals 的异步版：等 run 完全结束再还原，异步续接里还要用到替身 document / fetch
async function withGlobalsAsync(overrides, run) {
  const saved = {};
  for (const key of Object.keys(overrides)) saved[key] = ui[key];
  Object.assign(ui, overrides);
  try {
    return await run();
  } finally {
    for (const key of Object.keys(overrides)) {
      if (saved[key] === undefined) delete ui[key];
      else ui[key] = saved[key];
    }
  }
}

const MIYOUSHE_AVATAR = "https://bbs-static.miyoushe.com/avatar/avatar10013.png";
const DEFAULT_AVATAR = "/assets/paimon-avatar-192.webp";

// accountAvatars / avatarRequested 是脚本顶层的 let，只能在上下文里读写
function resetAvatars(known = {}) {
  vm.runInContext(`accountAvatars = ${JSON.stringify(known)}; avatarRequested.clear();`, ui);
}

test("a logged-in account shows its Miyoushe avatar, everyone else keeps the default one", () => {
  resetAvatars({ 300: MIYOUSHE_AVATAR });
  try {
    const account = (stuid) => ({ name: "阿止", stuid, cloud_games: { tokens: {} } });
    const known = ui.accountCard(account("300"), 0);
    assert.match(known, new RegExp(`<img class="acc-avatar is-remote" src="${MIYOUSHE_AVATAR}" data-avatar-uid="300" referrerpolicy="no-referrer"`));

    // 取不到头像的账号、还没登录的账号都用默认头像；没登录的还是灰的
    const unknown = ui.accountCard(account("301"), 0);
    assert.match(unknown, new RegExp(`<img class="acc-avatar" src="${DEFAULT_AVATAR}"`));
    assert.doesNotMatch(unknown, /data-avatar-uid/);
    const loggedOut = ui.accountCard(account(""), 0);
    assert.match(loggedOut, new RegExp(`<img class="acc-avatar is-empty" src="${DEFAULT_AVATAR}"`));
  } finally {
    resetAvatars();
  }
});

test("avatar addresses are looked up once per account and swapped in without a re-render", async () => {
  const requests = [];
  const fetch = async (url) => {
    requests.push(url);
    return { ok: true, json: async () => ({ avatars: { 300: MIYOUSHE_AVATAR } }) };
  };
  const makeImg = () => {
    const classes = new Set(["acc-avatar"]);
    const listeners = {};
    return {
      src: DEFAULT_AVATAR,
      dataset: {},
      classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name), contains: (name) => classes.has(name) },
      addEventListener: (name, fn) => { listeners[name] = fn; },
      listeners,
    };
  };
  const imgs = [makeImg(), makeImg(), makeImg()];
  const document = {
    ...ui.document,
    querySelector: (selector) => imgs[Number(selector.match(/data-index="(\d+)"/)?.[1])] ?? null,
  };
  resetAvatars();
  vm.runInContext(
    `config = { accounts: [{ stuid: "300" }, { stuid: "301" }, { stuid: "" }, { name: "草稿" }] };`,
    ui,
  );
  try {
    await withGlobalsAsync({ document, fetch }, () => ui.loadAccountAvatars());
    // 没登录的、没有 UID 的账号不会被拿去问
    assert.deepEqual(requests, ["/api/account/avatars?uids=300,301"]);
    assert.equal(imgs[0].src, MIYOUSHE_AVATAR);
    assert.equal(imgs[0].dataset.avatarUid, "300");
    assert.ok(imgs[0].classList.contains("is-remote"));
    assert.equal(imgs[1].src, DEFAULT_AVATAR); // 后端没返回头像的账号保持默认
    assert.ok(!imgs[1].classList.contains("is-remote"));

    // 问过的不再问：重绘多少次都只请求一次
    await withGlobalsAsync({ document, fetch }, () => ui.loadAccountAvatars());
    assert.equal(requests.length, 1);

    // 头像打不开时退回默认头像，并且之后的重绘不再使用这个地址
    imgs[0].listeners.error();
    assert.equal(imgs[0].src, DEFAULT_AVATAR);
    assert.ok(!imgs[0].classList.contains("is-remote"));
    assert.equal(vm.runInContext("accountAvatars['300']", ui), undefined);
  } finally {
    vm.runInContext("config = null;", ui);
    resetAvatars();
  }
});

test("overseas accounts are looked up under their own key", async () => {
  const requests = [];
  const fetch = async (url) => {
    requests.push(url);
    return { ok: true, json: async () => ({ avatars: {} }) };
  };
  resetAvatars();
  vm.runInContext(
    `config = { accounts: [{ stuid: "12" }, { stuid: "12", region: "os" }, { stuid: "" }] };`,
    ui,
  );
  try {
    await withGlobalsAsync({ fetch }, () => ui.loadAccountAvatars());
    assert.deepEqual(requests, ["/api/account/avatars?uids=12,os:12"]);
  } finally {
    vm.runInContext("config = null;", ui);
    resetAvatars();
  }
});

test("a failed avatar request is silent and is not retried on every redraw", async () => {
  let calls = 0;
  const fetch = async () => {
    calls += 1;
    throw new Error("offline");
  };
  resetAvatars();
  vm.runInContext(`config = { accounts: [{ stuid: "300" }] };`, ui);
  try {
    await withGlobalsAsync({ fetch }, () => ui.loadAccountAvatars());
    await withGlobalsAsync({ fetch }, () => ui.loadAccountAvatars());
    assert.equal(calls, 1);
    assert.equal(vm.runInContext("JSON.stringify(accountAvatars)", ui), "{}");
  } finally {
    vm.runInContext("config = null;", ui);
    resetAvatars();
  }
});

test("the real avatar is cropped round and the default stays an uncropped sticker", () => {
  const css = fs.readFileSync(path.join(__dirname, "../miyouqian/webui/app.css"), "utf8");
  assert.match(css, /\.acc-avatar\.is-remote \{[^}]*border-radius: 50%/);
  assert.doesNotMatch(css.match(/\.acc-avatar \{[^}]*\}/)[0], /border-radius/);
});
