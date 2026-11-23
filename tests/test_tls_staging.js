const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function run() {
  const { debugPort, invitation, email, outbox, screenshots } = JSON.parse(fs.readFileSync(0, "utf8"));
  const password = "SyntheticTlsPassword123!";
  const replacement = "SyntheticTlsReplacement456!";
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
  function openScreen(name) {
    return evaluate('document.querySelector(".nav [data-open=' + name + ']").click()');
  }
  async function saveForm(id, values) {
    await evaluate(
      'window.confirm = () => true;' +
      '{ const form = document.getElementById(' + JSON.stringify(id) + ');' +
      'for (const [field, value] of Object.entries(' + JSON.stringify(values) + '))' +
      'form.elements[field].value = value; form.requestSubmit(); }'
    );
    await until('document.getElementById("message").textContent === "Record saved successfully."');
  }
  async function capture(name) {
    if (!screenshots) return;
    fs.mkdirSync(screenshots, { recursive: true });
    const result = await cdp("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(screenshots, name + ".png"), Buffer.from(result.data, "base64"));
  }
  try {
    await cdp("Page.enable");
    await resize(390, 844, true);
    await cdp("Page.navigate", { url: invitation });
    await until('document.getElementById("account-link-form") && !document.getElementById("account-link-form").hidden');
    assert.equal(await evaluate("location.hash"), "");
    await evaluate('document.getElementById("account-link-form").elements.password.value = ' + JSON.stringify(password) + ';' +
      'document.getElementById("account-link-form").requestSubmit()');
    await until('document.getElementById("message").textContent.includes("Email verified")');
    await evaluate('document.getElementById("email").value = ' + JSON.stringify(email) + ';' +
      'document.getElementById("password").value = ' + JSON.stringify(password) + ';' +
      'document.getElementById("login-form").requestSubmit()');
    await until('!document.getElementById("dashboard").hidden && recoveryLoaded');
    assert.equal(await evaluate("innerWidth"), 390);
    assert.equal(await evaluate("document.documentElement.scrollWidth"), 390);
    await evaluate('document.querySelector(".nav [data-open=customers]").click()');
    await evaluate('window.confirm = () => true;' +
      'document.getElementById("customer-form").elements.name.value = "Synthetic TLS Customer";' +
      'document.getElementById("customer-form").requestSubmit()');
    await until('document.getElementById("customers").textContent.includes("Synthetic TLS Customer")');
    const customer = await evaluate('document.getElementById("sale-customer").options[1].value');
    await openScreen("sales");
    await saveForm("sale-form", { customer_id: customer, reference: "RC-SALE-1", total: "100.01", paid: "20.01" });
    await evaluate('[...document.querySelectorAll("#sale-form button")].find(b => b.textContent === "View Receipt").click()');
    await until('document.getElementById("receipt-details").textContent.includes("RC-SALE-1")');
    await capture("mobile-receipt");
    await evaluate('window.print = () => { window.rcPrintReady = true; }; document.getElementById("receipt-print").click()');
    await until("window.rcPrintReady === true");
    await cdp("Emulation.setEmulatedMedia", { media: "print" });
    assert.equal(await evaluate('getComputedStyle(document.getElementById("receipt-panel")).display !== "none"'), true);
    assert.equal(await evaluate('getComputedStyle(document.getElementById("dashboard")).display'), "none");
    const pdf = Buffer.from((await cdp("Page.printToPDF", { preferCSSPageSize: true })).data, "base64");
    assert.equal(pdf.subarray(0, 4).toString(), "%PDF");
    assert(pdf.length > 1000);
    if (screenshots) fs.writeFileSync(path.join(screenshots, "receipt-preview.pdf"), pdf);
    await cdp("Emulation.setEmulatedMedia", { media: "" });
    await evaluate('window.dispatchEvent(new Event("afterprint")); document.getElementById("receipt-close").click()');
    await openScreen("repayments");
    await saveForm("repayment-form", { customer_id: customer, reference: "RC-PAY-1", amount: "5.01" });
    await openScreen("expenses");
    await saveForm("expense-form", { reference: "RC-EXP-1", amount: "1.01",
      category: "Transport", description: "Synthetic stock delivery" });
    await openScreen("overview");
    await until('document.getElementById("outstanding").textContent.endsWith("74.99")');
    assert((await evaluate('document.getElementById("gross-sales").textContent')).endsWith("100.01"));
    await resize(1440, 900, false);
    assert.equal(await evaluate("innerWidth"), 1440);
    assert.equal(await evaluate("document.documentElement.scrollWidth"), 1440);
    await capture("desktop-overview");

    // Keep the old bearer token only in the test process to verify revocation.
    const oldToken = await evaluate("accessToken");
    await cdp("Page.navigate", { url: new URL("/app", invitation).href });
    await until('document.getElementById("login-panel") && !document.getElementById("login-panel").hidden');
    await evaluate('document.getElementById("forgot-password").click();' +
      'document.getElementById("password-reset-request").elements.email.value = ' + JSON.stringify(email) + ';' +
      'document.getElementById("password-reset-request").requestSubmit()');
    await until('document.getElementById("message").textContent.includes("check its inbox")');
    let reset;
    for (let attempt = 0; attempt < 90 && !reset; attempt++) {
      for (const filename of fs.readdirSync(outbox)) {
        try {
          const item = JSON.parse(fs.readFileSync(path.join(outbox, filename), "utf8"));
          if (item.purpose === "reset") reset = item.link;
        } catch (_) {
          // The capture can become visible before its file write finishes.
        }
      }
      if (!reset) await delay(100);
    }
    assert(reset, "Synthetic reset email missing");
    await cdp("Page.navigate", { url: reset });
    await until('document.getElementById("account-link-form") && !document.getElementById("account-link-form").hidden');
    await evaluate('document.getElementById("account-link-form").elements.password.value = ' +
      JSON.stringify(replacement) + '; document.getElementById("account-link-form").requestSubmit()');
    await until('document.getElementById("message").textContent.includes("Password updated")');
    const revoked = await cdp("Runtime.evaluate", {
      expression: 'fetch("/api/v1/auth/businesses", {headers:{Authorization:' +
        JSON.stringify("Bearer " + oldToken) + '}}).then(response => response.status)',
      awaitPromise: true, returnByValue: true
    });
    assert.equal(revoked.result.value, 401);
    console.log("Verified HTTPS merchant journey, print rendering and reset revocation at 390 px and 1440 px.");
  } finally {
    socket.close();
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
