const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Exercise the browser's real account helpers without starting authentication or polling.
const source = fs.readFileSync(
  path.join(__dirname, "../miyouqian/webui/app.js"),
  "utf8",
);
assert.match(source, /\ncheckAuthAndInit\(\);\s*$/);
const ui = vm.createContext({
  document: {
    querySelectorAll: () => [],
    querySelector: () => null,
    getElementById: () => ({ addEventListener() {} }),
    addEventListener() {},
  },
});
vm.runInContext(source.replace(/\ncheckAuthAndInit\(\);\s*$/, "\n"), ui);

const CN = { name: "国服号", region: "cn", stuid: "1001", cookie: "cn-cookie" };
const OS = { name: "海外号", region: "os", stuid: "2002", cookie: "ltuid_v2=2002; ltoken_v2=v2_x" };

function run(code) {
  return vm.runInContext(code, ui);
}

function setState({ accounts = [], editing = null, avatars = {}, panel = null } = {}) {
  ui.accounts = accounts;
  ui.avatars = avatars;
  run("config = { accounts }; accountAvatars = avatars;");
  run(`editingAccountIndex = ${JSON.stringify(editing)}; localLoginPanel = null; activeLoginIndex = null;`);
  if (panel) {
    ui.panel = panel;
    run("localLoginPanel = panel");
  }
}

function card(account, index = 0) {
  return ui.accountCard(account, index);
}

function regionInput(html) {
  return html.match(/<input data-field="region" type="hidden" value="(\w+)"/)?.[1];
}

test("only accounts marked os count as overseas", () => {
  assert.equal(ui.isOverseas(OS), true);
  assert.equal(ui.isOverseas(CN), false);
  assert.equal(ui.isOverseas({}), false);
  assert.equal(ui.isOverseas(undefined), false);
});

test("a new account defaults to the CN server", () => {
  assert.equal(ui.emptyAccount("账号1").region, "cn");
});

test("an overseas card shows its badge and keeps the CN-only controls away", () => {
  setState({ accounts: [OS] });
  const html = card(OS);
  assert.match(html, /acc-pill os">国际服</);
  assert.match(html, /UID 2002/);
  assert.match(html, /更新 Cookie/);
  assert.equal(regionInput(html), "os");
  // cloud games are a CN feature: no button, no chip, and no expanded token editor
  assert.doesNotMatch(html, /data-toggle-cloud/);
  assert.doesNotMatch(html, /云游戏/);
  assert.doesNotMatch(html, /data-account-cloud-token="genshin" type="password"/);
});

test("a CN card is unchanged apart from carrying its region", () => {
  setState({ accounts: [CN] });
  const html = card(CN);
  assert.doesNotMatch(html, /acc-pill os/);
  assert.match(html, /data-toggle-cloud="0"/);
  assert.match(html, /刷新登录/);
  assert.equal(regionInput(html), "cn");
});

test("a legacy account without a region is treated as CN", () => {
  const legacy = { name: "旧", stuid: "9", cookie: "c" };
  setState({ accounts: [legacy] });
  const html = card(legacy);
  assert.equal(regionInput(html), "cn");
  assert.match(html, /data-toggle-cloud/);
});

test("each server shows its own avatar even when the UIDs collide", () => {
  const cnTwin = { ...OS, region: "cn" };
  const avatars = {
    "os:2002": "https://upload-os-bbs.hoyolab.com/avatar/a.png",
    2002: "https://bbs-static.miyoushe.com/avatar/a.png",
  };
  setState({ accounts: [OS, cnTwin], avatars });

  const osHtml = card(OS);
  assert.match(osHtml, /src="https:\/\/upload-os-bbs\.hoyolab\.com\/avatar\/a\.png"/);
  assert.match(osHtml, /data-avatar-uid="os:2002"/);

  const cnHtml = card(cnTwin);
  assert.match(cnHtml, /src="https:\/\/bbs-static\.miyoushe\.com\/avatar\/a\.png"/);
  assert.match(cnHtml, /data-avatar-uid="2002"/);
});

test("an unlogged overseas account still uses the default avatar", () => {
  const empty = { name: "海外号", region: "os", stuid: "", cookie: "" };
  setState({ accounts: [empty], avatars: { "os:": "https://upload-os-bbs.hoyolab.com/avatar/a.png" } });
  assert.doesNotMatch(card(empty), /is-remote/);
});

test("avatar keys are scoped by server", () => {
  assert.equal(ui.avatarKey(OS), "os:2002");
  assert.equal(ui.avatarKey(CN), "1001");
  assert.equal(ui.avatarKey({ region: "cn", stuid: "2002" }), "2002");
  assert.equal(ui.avatarKey({}), "");
});

test("the unlogged overseas card tells the user to paste a cookie", () => {
  const empty = { name: "海外号", region: "os", stuid: "", cookie: "" };
  setState({ accounts: [empty] });
  const html = card(empty);
  assert.match(html, /粘贴 Cookie/);
  assert.doesNotMatch(html, /扫码或验证码/);
});

test("the server can be picked while an account is still logged out", () => {
  const draft = { name: "新", region: "os", stuid: "", cookie: "", _draft: true };
  setState({ accounts: [draft], editing: 0 });
  const html = card(draft);
  const select = html.match(/<select data-field="region" data-region-select="0">([\s\S]*?)<\/select>/);
  assert.ok(select, "region select is rendered");
  assert.match(select[1], /<option value="os" selected>/);
  assert.match(select[1], /<option value="cn" >/);
  // the select is the field, so there must be no second hidden region input competing with it
  assert.equal(regionInput(html), undefined);
});

test("a brand-new account shows only the name hint, never a login prompt", () => {
  for (const region of ["os", "cn"]) {
    const draft = { name: "新", region, stuid: "", cookie: "", _draft: true };
    setState({ accounts: [draft], editing: 0 });
    const html = card(draft);
    // 此刻还没有登录按钮，指向它的提示只会误导
    assert.doesNotMatch(html, /粘贴 Cookie/);
    assert.doesNotMatch(html, /登录方式/);
    assert.doesNotMatch(html, /还没有登录/);
    assert.match(html, /最多 10 个字，仅用于本地显示/);
  }
});

test("once saved, an unlogged account points at the login button again", () => {
  const saved = { name: "海外号", region: "os", stuid: "", cookie: "" };
  setState({ accounts: [saved] });
  const html = card(saved);
  assert.match(html, /还没有登录，点「粘贴 Cookie」/);
  assert.doesNotMatch(html, /点「保存」/);
});

test("the server is locked once the account has logged in", () => {
  setState({ accounts: [OS], editing: 0 });
  const html = card(OS);
  assert.doesNotMatch(html, /data-region-select/);
  assert.equal(regionInput(html), "os");
});

test("the server select is not offered outside edit mode", () => {
  const draft = { name: "新", region: "cn", stuid: "", cookie: "" };
  setState({ accounts: [draft], editing: null });
  const html = card(draft);
  assert.doesNotMatch(html, /data-region-select/);
  assert.equal(regionInput(html), "cn");
});

test("the same UID may exist on both servers but not twice on one", () => {
  const twin = { ...OS, stuid: CN.stuid };
  assert.doesNotThrow(() => ui.validateUniqueAccountUids([CN, twin]));
  assert.throws(() => ui.validateUniqueAccountUids([twin, { ...twin }]), /已存在/);
  assert.throws(() => ui.validateUniqueAccountUids([CN, { ...CN }]), /已存在/);
  // a legacy account without a region still collides with a CN account
  assert.throws(() => ui.validateUniqueAccountUids([CN, { stuid: CN.stuid }]), /已存在/);
});

test("shop exchange only offers logged-in CN accounts", () => {
  setState({ accounts: [OS, CN] });
  const choices = ui.loggedInAccountChoices();
  assert.deepEqual(JSON.parse(JSON.stringify(choices.map(({ index }) => index))), [1]);
});

test("a shop plan's account dropdown skips overseas accounts but keeps real indexes", () => {
  setState({ accounts: [OS, CN] });
  const html = ui.shopPlanRow({ goods_id: "g", account_index: 1, account_stuid: CN.stuid }, 0);
  const select = html.match(/<select data-shop-plan-field="account_index"[^>]*>([\s\S]*?)<\/select>/)[1];
  const values = Array.from(select.matchAll(/<option value="([^"]*)"/g), ([, value]) => value);
  assert.deepEqual(values, ["1"]);
  assert.match(select, /selected/);
});

test("the cookie panel renders the pasted text and a submit button", () => {
  const slot = { classList: { add() {} }, dataset: {}, innerHTML: "", querySelector: () => null };
  ui.renderCookieLoginPanel(slot, { account_index: 3, mode: "cookie", cookie: "ltuid_v2=1 <b>" });
  assert.match(slot.innerHTML, /<textarea data-login-cookie="3"/);
  assert.match(slot.innerHTML, /data-login-submit-cookie="3"/);
  // pasted text must be escaped, it is rendered back into the page
  assert.match(slot.innerHTML, /ltuid_v2=1 &lt;b&gt;/);
  assert.doesNotMatch(slot.innerHTML, /<b>/);
});

test("the cookie panel disables its inputs while logging in and shows errors", () => {
  const slot = { classList: { add() {} }, dataset: {}, innerHTML: "", querySelector: () => null };
  ui.renderCookieLoginPanel(slot, { account_index: 0, mode: "cookie", verifying: true, message: "正在登录" });
  assert.match(slot.innerHTML, /<textarea[^>]*disabled/);
  assert.match(slot.innerHTML, /登录中/);
  ui.renderCookieLoginPanel(slot, { account_index: 0, mode: "cookie", error: true, message: "没有找到 ltuid_v2" });
  assert.match(slot.innerHTML, /login-panel-message error/);
});

test("the local login panel dispatches the cookie mode", () => {
  const slot = { classList: { add() {} }, dataset: {}, innerHTML: "", querySelector: () => null };
  ui.renderLocalLoginPanel(slot, { account_index: 0, mode: "cookie", cookie: "" });
  assert.equal(slot.dataset.localLoginMode, "cookie");
  assert.match(slot.innerHTML, /data-login-cookie/);
  assert.doesNotMatch(slot.innerHTML, /data-login-phone/);
});

test("filling a draft from a login adopts the server the login reports", () => {
  const draft = { name: "新", region: "cn", stuid: "", cookie: "", _draft: true };
  setState({ accounts: [draft] });
  run(`
    var realCollect = collectConfig, realRender = renderAccounts, realReveal = revealAccount;
    collectConfig = () => config;
    renderAccounts = () => {};
    revealAccount = () => {};
  `);
  try {
    ui.applyDraftLogin({
      account_index: 0,
      account_data: { stuid: "2002", cookie: "ltuid_v2=2002; ltoken_v2=v2_x", stoken: "", mid: "", region: "os" },
    });
  } finally {
    run("collectConfig = realCollect; renderAccounts = realRender; revealAccount = realReveal;");
  }
  assert.equal(draft.region, "os");
  assert.equal(draft.stuid, "2002");
  assert.equal(draft.cookie, "ltuid_v2=2002; ltoken_v2=v2_x");
  assert.equal(draft._draft, true);
  // a CN login carries no region of its own, so the draft keeps what it already had
  const cnDraft = { name: "新", region: "cn", stuid: "", cookie: "", _draft: true };
  setState({ accounts: [cnDraft] });
  run("collectConfig = () => config; renderAccounts = () => {}; revealAccount = () => {};");
  try {
    ui.applyDraftLogin({ account_index: 0, account_data: { stuid: "1001", cookie: "c", stoken: "s", mid: "m" } });
  } finally {
    run("collectConfig = realCollect; renderAccounts = realRender; revealAccount = realReveal;");
  }
  assert.equal(cnDraft.region, "cn");
  assert.equal(cnDraft.stoken, "s");
});

const baseDocument = ui.document;

function fakeDocument(nodes) {
  ui.document = {
    querySelector: (selector) => nodes[selector] ?? null,
    querySelectorAll: () => [],
  };
}

function resetDocument() {
  ui.document = baseDocument;
  ui.navigator = undefined;
}

test("the cookie panel offers a clipboard button and a detection line", () => {
  const slot = { classList: { add() {} }, dataset: {}, innerHTML: "", querySelector: () => null };
  ui.renderCookieLoginPanel(slot, { account_index: 0, mode: "cookie", cookie: "" });
  assert.match(slot.innerHTML, /data-login-paste-clipboard/);
  assert.match(slot.innerHTML, /data-login-detect/);
  assert.match(slot.innerHTML, /从剪贴板粘贴/);
});

test("pasted text is classified before it is sent", () => {
  const cases = [
    ["ltuid_v2=2002; ltoken_v2=v2_x", "2002", "ltoken_v2"],
    ["Cookie: ltuid_v2=2002; ltoken_v2=v2_x", "2002", "ltoken_v2"],
    ["ltuid_v2\t2002\t.hoyolab.com\t/\nltoken_v2\tv2_x\t.hoyolab.com\t/", "2002", "ltoken_v2"],
    ['[{"name":"ltuid_v2","value":"2002"},{"name":"ltoken_v2","value":"v2_x"}]', "2002", "ltoken_v2"],
    ['{"ltuid_v2":"2002","ltoken_v2":"v2_x"}', "2002", "ltoken_v2"],
    ["account_id=2002; cookie_token=tok", "2002", "cookie_token"],
    ["ltuid_v2=2002", "2002", ""],
    ["ltoken_v2=v2_x", "", "ltoken_v2"],
    ["", "", ""],
  ];
  for (const [text, uid, token] of cases) {
    const result = ui.describeHoyolabCookie(text);
    assert.deepEqual({ uid: result.uid, token: result.token }, { uid, token }, text);
  }
});

test("the detection line names whatever is still missing", () => {
  const textarea = { value: "" };
  const detect = { textContent: "", dataset: {} };
  fakeDocument({ "[data-login-cookie]": textarea, "[data-login-detect]": detect });
  try {
    ui.updateCookieDetect();
    assert.equal(detect.textContent, "");

    textarea.value = "ltuid_v2=2002; ltoken_v2=v2_x";
    ui.updateCookieDetect();
    assert.equal(detect.textContent, "已识别 UID 2002，凭证 ltoken_v2");
    assert.equal(detect.dataset.state, "ok");

    textarea.value = "ltuid_v2=2002";
    ui.updateCookieDetect();
    assert.equal(detect.dataset.state, "warn");
    assert.match(detect.textContent, /已识别 UID 2002，但没有找到 ltoken_v2/);

    textarea.value = "ltoken_v2=v2_x";
    ui.updateCookieDetect();
    assert.match(detect.textContent, /没有找到 ltuid_v2/);
  } finally {
    resetDocument();
  }
});

test("the clipboard button fills the box and reports what it found", async () => {
  const textarea = { value: "", focusCalls: 0, focus() { this.focusCalls += 1; } };
  const detect = { textContent: "", dataset: {} };
  fakeDocument({ '[data-login-cookie="0"]': textarea, "[data-login-cookie]": textarea, "[data-login-detect]": detect });
  ui.navigator = { clipboard: { readText: async () => "  Cookie: ltuid_v2=2002; ltoken_v2=v2_x  " } };
  const panel = { account_index: 0, mode: "cookie", cookie: "" };
  try {
    await ui.readClipboardCookie(panel);
  } finally {
    resetDocument();
  }

  assert.equal(textarea.value, "Cookie: ltuid_v2=2002; ltoken_v2=v2_x");
  assert.equal(panel.cookie, "Cookie: ltuid_v2=2002; ltoken_v2=v2_x");
  assert.equal(textarea.focusCalls, 1);
  assert.equal(detect.dataset.state, "ok");
  assert.match(detect.textContent, /UID 2002/);
});

test("a refused or empty clipboard leaves a hint instead of throwing", async () => {
  const textarea = { value: "", focus() {} };
  const detect = { textContent: "", dataset: {} };
  fakeDocument({ '[data-login-cookie="0"]': textarea, "[data-login-detect]": detect });
  try {
    ui.navigator = { clipboard: { readText: async () => { throw new Error("denied"); } } };
    await ui.readClipboardCookie({ account_index: 0 });
    assert.equal(detect.dataset.state, "error");
    assert.match(detect.textContent, /Ctrl\+V/);
    assert.equal(textarea.value, "");

    ui.navigator = { clipboard: { readText: async () => "   " } };
    await ui.readClipboardCookie({ account_index: 0 });
    assert.equal(detect.dataset.state, "error");
    assert.match(detect.textContent, /剪贴板是空的/);
  } finally {
    resetDocument();
  }
});

function stubLoginEnvironment({ response, error } = {}) {
  const calls = { api: [], toasts: [], reloaded: 0, drafts: [] };
  ui.calls = calls;
  ui.response = response;
  ui.failure = error;
  ui.pasted = "  ltuid_v2=2002; ltoken_v2=v2_x  ";
  run(`
    collectConfig = () => config;
    renderLoginSlot = () => {};
    showToast = (message) => calls.toasts.push(message);
    loadConfig = async () => { calls.reloaded += 1; };
    applyDraftLogin = (login) => calls.drafts.push(login);
    api = async (path, options) => {
      calls.api.push([path, JSON.parse(options.body)]);
      if (failure) throw failure;
      return response;
    };
    document.querySelector = () => ({ value: pasted });
  `);
}

test("submitting posts the trimmed cookie with the account and the draft flag", async () => {
  const draft = { name: "新", region: "os", stuid: "", cookie: "", _draft: true };
  setState({ accounts: [draft], panel: { account_index: 0, mode: "cookie", cookie: "" } });
  stubLoginEnvironment({ response: { ok: true, draft: true, message: "ok", account_data: { stuid: "2002" } } });

  await ui.submitCookieLogin(0);

  const [[path, body]] = ui.calls.api;
  assert.equal(path, "/api/login/cookie");
  assert.equal(body.cookie, "ltuid_v2=2002; ltoken_v2=v2_x");
  assert.equal(body.draft, true);
  assert.equal(body.account_index, 0);
  assert.equal(body.account.region, "os");
  assert.equal("_draft" in body.account, false);
  // a draft is filled in locally, not reloaded from the server
  assert.equal(ui.calls.drafts.length, 1);
  assert.equal(ui.calls.reloaded, 0);
});

test("submitting for a saved account reloads the config", async () => {
  setState({ accounts: [{ ...OS, stuid: "" }], panel: { account_index: 0, mode: "cookie", cookie: "" } });
  stubLoginEnvironment({ response: { ok: true, draft: false, message: "ok" } });

  await ui.submitCookieLogin(0);

  assert.equal(ui.calls.reloaded, 1);
  assert.equal(ui.calls.drafts.length, 0);
  assert.equal(ui.calls.api[0][1].draft, false);
});

test("a fresh login forgets the old avatar so the next redraw fetches it again", async () => {
  const draft = { name: "新", region: "os", stuid: "", cookie: "", _draft: true };
  setState({
    accounts: [draft],
    avatars: { "os:2002": "https://old.example/a.png" },
    panel: { account_index: 0, mode: "cookie", cookie: "" },
  });
  run('avatarRequested.add("os:2002");');
  stubLoginEnvironment({ response: { ok: true, draft: true, message: "ok", account_data: { stuid: "2002", region: "os" } } });

  await ui.submitCookieLogin(0);

  assert.equal(run('accountAvatars["os:2002"]'), undefined);
  assert.equal(run('avatarRequested.has("os:2002")'), false);
  // 另一个账号的头像不受影响
  run('accountAvatars["cn:1"] = "https://bbs-static.miyoushe.com/a.png"; avatarRequested.add("cn:1");');
  assert.equal(run('avatarRequested.has("cn:1")'), true);
});

test("a rejected cookie keeps the panel open with the server's message", async () => {
  setState({ accounts: [{ ...OS, stuid: "" }], panel: { account_index: 0, mode: "cookie", cookie: "" } });
  stubLoginEnvironment({ error: new Error("cookie 里没有找到 ltoken_v2") });

  await assert.rejects(ui.submitCookieLogin(0), /ltoken_v2/);

  const panel = run("localLoginPanel");
  assert.equal(panel.error, true);
  assert.equal(panel.verifying, false);
  assert.match(panel.message, /ltoken_v2/);
  assert.equal(ui.calls.reloaded, 0);
});

test("an empty paste is rejected before any request", async () => {
  setState({ accounts: [{ ...OS, stuid: "" }], panel: { account_index: 0, mode: "cookie", cookie: "" } });
  stubLoginEnvironment({ response: {} });
  ui.pasted = "   ";
  run("document.querySelector = () => ({ value: pasted });");

  await assert.rejects(ui.submitCookieLogin(0), /粘贴/);

  assert.equal(ui.calls.api.length, 0);
});
