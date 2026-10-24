const assert = require("node:assert/strict");
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
