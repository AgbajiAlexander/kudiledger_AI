const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const [debugPort, baseUrl, customer, screenshotDirectory] = process.argv.slice(2);
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function run() {
  const tabs = await fetch("http://127.0.0.1:" + debugPort + "/json/list").then(r => r.json());
  const socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  const replies = new Map();
  let sequence = 0;
  let interrupted = 0;
  let failure;
  let writes = 0;
  let expectedResponse = 200;
  socket.addEventListener("message", event => {
    const info = JSON.parse(event.data);
    if (info.id) {
      const reply = replies.get(info.id);
      if (!reply) return;
      replies.delete(info.id);
      if (info.error) reply.reject(new Error(info.error.message));
      else reply.resolve(info.result);
    } else if (info.method === "Fetch.requestPaused") {
      if (info.params.responseStatusCode !== expectedResponse) {
        failure = new Error("Financial save did not return a successful response.");
      }
      interrupted++;
      cdp("Fetch.failRequest", {
        requestId: info.params.requestId, errorReason: "InternetDisconnected"
      }).catch(error => { failure = error; });
    } else if (info.method === "Network.requestWillBeSent") {
      const request = info.params.request;
      if (request.method === "POST" && request.url.endsWith("/submit")) writes++;
    }
  });

  function cdp(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      replies.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const result = await cdp("Runtime.evaluate", { expression, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  }

  async function until(expression) {
    for (let count = 0; count < 90; count++) {
      if (failure) throw failure;
      if (await evaluate(expression)) return;
      await pause(100);
    }
    throw new Error("Browser did not reach expected state: " + expression);
  }

  async function signIn(email = "live@example.test") {
    await until('document.readyState === "complete" && !!document.getElementById("login-form")');
    await evaluate('document.getElementById("email").value = ' + JSON.stringify(email) + ';' +
      'document.getElementById("password").value = "SyntheticLiveRecovery123!";' +
      'document.getElementById("login-form").requestSubmit()');
    await until('!document.getElementById("dashboard").hidden && recoveryLoaded');
  }

  function go(screen) {
    return evaluate('document.querySelector(".nav [data-open=' + screen + ']").click()');
  }

  function submitSale(reference) {
    return evaluate('window.confirm = () => true;' +
      '(() => { const sale = document.getElementById("sale-form");' +
      'sale.elements.customer_id.value = ' + JSON.stringify(customer) + ';' +
      'sale.elements.reference.value = ' + JSON.stringify(reference) + ';' +
      'sale.elements.total.value = "100.01"; sale.elements.paid.value = "20.01";' +
      'sale.requestSubmit(); sale.requestSubmit(); })()');
  }

  async function reloadAndSignIn() {
    await cdp("Page.reload", { ignoreCache: true });
    await until('document.readyState === "complete" && document.getElementById("dashboard")?.hidden');
    await signIn();
  }

  const network = { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 };
  const online = { ...network, offline: false, downloadThroughput: -1, uploadThroughput: -1 };
  const recoveryText = 'document.getElementById("recovery-list").textContent';

  function screenshot(name) {
    if (!screenshotDirectory) return;
    return cdp("Page.captureScreenshot", { format: "png", fromSurface: true }).then(result => {
      fs.mkdirSync(screenshotDirectory, { recursive: true });
      fs.writeFileSync(path.join(screenshotDirectory, name + ".png"), Buffer.from(result.data, "base64"));
    });
  }

  try {
    await cdp("Page.enable");
    await cdp("Network.enable");
    await cdp("Emulation.setDeviceMetricsOverride", {
      width: 390, height: 844, mobile: true, deviceScaleFactor: 1
    });
    await cdp("Page.navigate", { url: baseUrl + "/app" });
    await signIn();
    await until('document.getElementById("sale-customer").options.length === 2');
    await go("sales");

    // ADB-like disconnect before the initial prepare: no journal row or ledger write.
    await cdp("Network.emulateNetworkConditions", network);
    await submitSale("NETWORK-TEST-1");
    await until(recoveryText + '.includes("NETWORK-TEST-1")');
    assert.equal(writes, 0);
    assert.equal(await evaluate('localStorage.length'), 1);
    assert.equal(await evaluate('Object.keys(JSON.parse(localStorage.getItem(localStorage.key(0)))).sort().join(",")'),
      "id,reference");
    await cdp("Network.emulateNetworkConditions", online);
    await reloadAndSignIn();
    await go("sales");
    assert.equal(await evaluate('document.querySelector("#sale-form button[type=submit]").disabled'), true);
    await go("recovery");
    await until(recoveryText + '.includes("NETWORK-TEST-1")');
    const server = await cdp("Runtime.evaluate", {
      expression: 'api(recoveryPath())', awaitPromise: true, returnByValue: true
    });
    assert.deepEqual(server.result.value, []);
    const debt = await cdp("Runtime.evaluate", {
      expression: 'api("/api/v1/businesses/" + businessId + "/reports/daily?report_date=2026-11-24")',
      awaitPromise: true, returnByValue: true
    });
    assert.equal(debt.result.value.current_outstanding_debt, "95.01");
    await evaluate('document.getElementById("logout").click()');
    await until('document.getElementById("dashboard").hidden');
    await signIn("other-live@example.test");
    await go("recovery");
    assert.equal(await evaluate(recoveryText + '.includes("NETWORK-TEST-1")'), false);
    assert.equal(await evaluate('localStorage.length'), 1);
    await evaluate('document.getElementById("logout").click()');
    await until('document.getElementById("dashboard").hidden');
    await signIn();
    await go("recovery");
    await until(recoveryText + '.includes("NETWORK-TEST-1")');
    await evaluate('navigator.locks.request(localRecoveryKey("sale"), () => ' +
      'new Promise(resolve => window.releaseTestLock = resolve)); void 0');
    await until('typeof window.releaseTestLock === "function"');
    await evaluate('document.querySelector("#recovery-list button").click()');
    await until('document.getElementById("message").textContent.includes("no save is running")');
    assert.equal(await evaluate('localStorage.length'), 1);
    await evaluate('window.releaseTestLock()');
    await evaluate('window.confirm = () => true; document.querySelector("#recovery-list button").click()');
    await until('localStorage.length === 0 && !' + recoveryText + '.includes("NETWORK-TEST-1")');
    assert.equal(writes, 0);

    // If only the prepare reply is lost, the exact server draft takes precedence.
    await go("sales");
    expectedResponse = 201;
    await cdp("Fetch.enable", {
      patterns: [{ urlPattern: "*/recovery?attempt_id=*", requestStage: "Response" }]
    });
    await submitSale("PREPARE-LOSS-1");
    await until(recoveryText + '.includes("Ready but unsent")');
    assert.equal(interrupted, 1);
    assert.equal(writes, 0);
    await cdp("Fetch.disable");
    await reloadAndSignIn();
    await go("recovery");
    await until(recoveryText + '.includes("PREPARE-LOSS-1")');
    await evaluate('document.querySelector("#recovery-list button").click()');
    await until('localStorage.length === 0 && !' + recoveryText + '.includes("PREPARE-LOSS-1")');
    assert.equal(writes, 0);

    // The API completes the financial POST before Chrome discards its response.
    await go("sales");
    expectedResponse = 200;
    await cdp("Fetch.enable", {
      patterns: [{ urlPattern: "*/recovery/*/submit", requestStage: "Response" }]
    });
    await submitSale("LIVE-LOSS-1");
    await until('!document.querySelector("[data-screen=recovery]").hidden && ' +
      'document.getElementById("recovery-list").textContent.includes("LIVE-LOSS-1")');
    assert.equal(interrupted, 2);
    assert.equal(writes, 1);
    await cdp("Fetch.disable");

    await cdp("Network.emulateNetworkConditions", network);
    await evaluate('document.querySelector("#recovery-list button").click()');
    await until('document.getElementById("message").textContent.includes("Try again when connected")');
    assert.equal(writes, 1);
    await cdp("Network.emulateNetworkConditions", online);

    await cdp("Page.reload", { ignoreCache: true });
    await until('document.readyState === "complete" && document.getElementById("dashboard")?.hidden');
    assert.equal(await evaluate('localStorage.length + sessionStorage.length'), 0);
    await signIn();
    await go("sales");
    assert.equal(await evaluate('document.querySelector("#sale-form button[type=submit]").disabled'), true);
    await go("recovery");
    await until('document.getElementById("recovery-list").textContent.includes("Still uncertain")');
    await screenshot("unresolved-after-sign-in");

    await evaluate('document.querySelector("#recovery-list button").click()');
    await until('document.getElementById("recovery-list").textContent.includes("Verified as saved")');
    await until('!document.getElementById("refresh").disabled');
    await screenshot("verified-with-receipt");
    await evaluate('document.querySelector("#recovery-list button").click()');
    await until('document.getElementById("receipt-details").textContent.includes("LIVE-LOSS-1")');
    assert.equal(await evaluate('document.getElementById("receipt-details").textContent.includes("100.01")'), true);
    assert.equal(writes, 1);
    console.log("One committed sale, one dropped response, offline check, page reload, sign-in, fresh verification and receipt.");
  } finally {
    socket.close();
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
