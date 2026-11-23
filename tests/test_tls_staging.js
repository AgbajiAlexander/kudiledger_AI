const assert = require("node:assert/strict");
const fs = require("node:fs");

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function run() {
  const { debugPort, invitation, email } = JSON.parse(fs.readFileSync(0, "utf8"));
  const tabs = await fetch("http://127.0.0.1:" + debugPort + "/json/list").then(r => r.json());
  const socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  const pending = new Map();
  let sequence = 0;
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const reply = pending.get(message.id);
    if (!reply) return;
    pending.delete(message.id);
    if (message.error) reply.reject(new Error(message.error.message));
    else reply.resolve(message.result);
  });
  function cdp(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evaluate(expression) {
    const result = await cdp("Runtime.evaluate", { expression, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }
  async function until(expression) {
    for (let attempt = 0; attempt < 90; attempt++) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw new Error("Expected staging browser state was not reached");
  }
  function resize(width, height, mobile) {
    return cdp("Emulation.setDeviceMetricsOverride", { width, height, mobile, deviceScaleFactor: 1 });
  }
  try {
    await cdp("Page.enable");
    await resize(390, 844, true);
    await cdp("Page.navigate", { url: invitation });
    await until('document.getElementById("account-link-form") && !document.getElementById("account-link-form").hidden');
    assert.equal(await evaluate("location.hash"), "");
    await evaluate('document.getElementById("account-link-form").elements.password.value = "SyntheticTlsPassword123!";' +
      'document.getElementById("account-link-form").requestSubmit()');
    await until('document.getElementById("message").textContent.includes("Email verified")');
    await evaluate('document.getElementById("email").value = ' + JSON.stringify(email) + ';' +
      'document.getElementById("password").value = "SyntheticTlsPassword123!";' +
      'document.getElementById("login-form").requestSubmit()');
    await until('!document.getElementById("dashboard").hidden && recoveryLoaded');
    assert.equal(await evaluate("innerWidth"), 390);
    assert.equal(await evaluate("document.documentElement.scrollWidth"), 390);
    await evaluate('document.querySelector(".nav [data-open=customers]").click()');
    await evaluate('window.confirm = () => true;' +
      'document.getElementById("customer-form").elements.name.value = "Synthetic TLS Customer";' +
      'document.getElementById("customer-form").requestSubmit()');
    await until('document.getElementById("customers").textContent.includes("Synthetic TLS Customer")');
    await resize(1440, 900, false);
    await evaluate('document.querySelector(".nav [data-open=sales]").click()');
    assert.equal(await evaluate("innerWidth"), 1440);
    assert.equal(await evaluate("document.documentElement.scrollWidth"), 1440);
    assert.equal(await evaluate('document.activeElement.id'), "sales-title");
    assert.equal(await evaluate('document.getElementById("sale-customer").options.length'), 2);
    console.log("Verified onboarding and customer creation on the HTTPS staging site at 390 px and 1440 px.");
  } finally {
    socket.close();
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
