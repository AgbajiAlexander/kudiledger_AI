(async () => {
  function assert(condition, label) {
    if (!condition) throw new Error(label);
  }

  const calls = [];
  const directory = [];
  let post = () => ({});
  let checkResult = () => { throw new Error("Unexpected recovery check"); };
  const journal = new Map();
  let nextAttempt = 0;
  let fetchReceipt = () => { throw new Error("Unexpected receipt request"); };
  const report = {
    gross_sales: "250.01",
    recorded_cash_received: "100",
    operating_expenses: "0",
    current_outstanding_debt: "150.01"
  };
  const rejected = status => ({ ok: false, status });
  const response = (data, status = 200) => ({
    ok: true, status, json: async () => data
  });
  window.fetch = async (path, options) => {
    const method = options.method || "GET";
    const body = options.body && JSON.parse(options.body);
    calls.push({ path, method, body, options });
    if (path.endsWith("/auth/login")) {
      return response({ access_token: "token-" + body.email });
    }
    if (path.endsWith("/auth/businesses")) {
      const owner = options.headers.Authorization.includes("other@") ? "other" : "shop";
      return response([{ id: owner }]);
    }
    if (path.endsWith("/auth/logout")) return response({});
    if (path.includes("/reports/daily")) return response(report);
    if (path.endsWith("/customers")) {
      if (method === "POST") {
        directory.push({ id: "musa", name: body.name, outstanding_balance: "0" });
        return response({ id: "musa", name: body.name }, 201);
      }
      return response({ customers: directory });
    }
    if (path.includes("/recovery")) {
      const [, business, id, action] =
        path.match(/businesses\/([^/]+)\/recovery(?:\/([^/?]+))?(?:\/([^?]+))?/);
      if (method === "GET") return response(
        [...journal.values()].filter(row => row.business === business).map(row => row.summary)
      );
      if (!id && method === "POST") {
        const summary = { id: String(++nextAttempt), kind: body.kind, reference: body.reference, status: "prepared" };
        journal.set(summary.id, { business, body, summary });
        return response(summary, 201);
      }
      if (method === "DELETE") {
        journal.delete(id);
        return response({ status: "cleared" });
      }
      const row = journal.get(id);
      if (action === "acknowledge") {
        row.summary = { ...row.summary, status: "recent" };
        return response(row.summary);
      }
      if (action === "submit") {
        calls.at(-1).body = row.body;
        row.summary = { ...row.summary, status: "unresolved" };
        const result = await post(row.body);
        if (!result.ok) return result;
        return response({ status: "saved", transaction_id: (await result.json()).id });
      }
      if (action === "check") return checkResult(row.summary);
    }
    if (path.includes("/receipts?")) {
      return fetchReceipt(new URLSearchParams(path.split("?")[1]));
    }
    if (path.endsWith("/expenses") && method === "GET") return response([]);
    return post(body);
  };

  window.confirm = () => true;
  const submit = form => form.requestSubmit();
  const tick = () => new Promise(resolve => setTimeout(resolve, 0));
  const field = (form, name) => form.elements.namedItem(name);
  const button = form => form.querySelector('[type="submit"]');
  const messageText = () => $("message").textContent;
  const posts = () => calls.filter(call => call.method === "POST" && call.path.endsWith("/submit"));
  const checks = () => calls.filter(call => call.method === "POST" && call.path.endsWith("/check"));
  const nav = screen => document.querySelector('.nav [data-open="' + screen + '"]');
  function go(screen) {
    nav(screen).click();
    const section = document.querySelector('[data-screen="' + screen + '"]');
    assert(!section.hidden && document.activeElement === section.querySelector("h1"),
      screen + " navigation moves focus");
    assert(nav(screen).getAttribute("aria-current") === "page", "current section announced");
    assert(document.querySelectorAll("[data-screen]:not([hidden])").length === 1,
      "only active section is exposed");
    assert(document.documentElement.scrollWidth <= window.innerWidth, screen + " overflow");
  }

  async function signIn(email) {
    $("email").value = email;
    $("password").value = "SyntheticPassword";
    submit($("login-form"));
    await tick();
    assert(!$("dashboard").hidden && $("password").value === "", "sign-in");
  }

  function enter(form, values) {
    for (const [name, value] of Object.entries(values)) field(form, name).value = value;
  }

  const sale = $("sale-form");
  const repayment = $("repayment-form");
  const expense = $("expense-form");
  await signIn("owner@example.test");
  assert([320, 360, 390, 430, 768].includes(window.innerWidth), "requested viewport");
  assert(document.documentElement.scrollWidth <= window.innerWidth, "mobile overflow");
  assert([...document.querySelectorAll(".nav button, .quick-actions button")].every(control =>
    control.tabIndex === 0 && control.getBoundingClientRect().height >= 44), "keyboard and touch navigation");
  assert(document.querySelector(".nav").getAttribute("aria-label") === "Business sections",
    "screen reader navigation label");
  document.querySelector('.quick-actions [data-open="sales"]').click();
  assert(document.activeElement === $("sales-title"), "quick sale opens focused heading");
  go("overview");
  assert($("gross-sales").textContent.endsWith("250.01"), "rendered report");
  assert($("report-date").value === "2024-02-29", "date defaults to Lagos at midnight");
  assert(calls.some(call => call.path.endsWith("/reports/daily?report_date=2024-02-29")),
    "report request uses Lagos date");
  assert(getComputedStyle(field(sale, "customer_id")).borderRadius === "9px",
    "customer select stylesheet applies");

  go("customers");
  enter($("customer-form"), { name: "<Musa>" });
  submit($("customer-form"));
  await tick();
  assert(field(sale, "customer_id").options[1].textContent === "<Musa>", "customer picker");
  assert($("customers").textContent.includes("<Musa>"), "customer renders as text");
  directory.push(...Array.from({ length: 65 }, (_, i) =>
    ({ id: "test-" + i, name: "Trader " + i, outstanding_balance: "0.01" })));
  await refreshDashboard();
  assert($("customer-count").textContent.includes("Showing 50 of 66"), "large directory capped");
  $("customer-search").value = "tRaDeR 64";
  $("customer-search").dispatchEvent(new Event("input"));
  assert($("customers").rows.length === 1 && $("customers").textContent.includes("Trader 64"),
    "directory searches beyond initial 50");
  go("sales");
  const customerSearch = sale.querySelector(".customer-filter");
  const picker = field(sale, "customer_id");
  assert(customerSearch.labels.length === 1 && picker.labels.length === 1 &&
    picker.getAttribute("aria-describedby") === "sale-customer-hint", "picker accessible names");
  customerSearch.value = "64";
  customerSearch.dispatchEvent(new Event("input"));
  assert(picker.options.length === 2 && picker.options[1].value === "test-64" && picker.value === "",
    "picker finds customer without auto-selecting");
  picker.value = "test-64";
  customerSearch.value = "nobody";
  customerSearch.dispatchEvent(new Event("input"));
  assert(picker.value === "test-64" && $("sale-customer-hint").textContent.includes("No matching"),
    "selection remains explicit when the filter changes");
  sale.reset();
  customerSearch.dispatchEvent(new Event("input"));
  submit(sale);
  assert(document.activeElement === picker && !posts().length, "native required validation focuses picker");

  const saleValues = { customer_id: "musa", reference: "SALE-1", total: "250.01", paid: "100" };
  const repaymentValues = { customer_id: "musa", reference: "DEBT-1", amount: "50" };
  const expenseValues = {
    reference: "EXP-1", category: "Transport", description: "Delivery", amount: "40"
  };

  post = body => response({ id: body.reference + "-committed" }, 201);
  for (const [form, values] of [[sale, saleValues], [repayment, repaymentValues],
                                [expense, expenseValues]]) {
    go(form.closest("[data-screen]").dataset.screen);
    enter(form, values);
    window.confirm = () => false;
    const before = posts().length;
    submit(form);
    await tick();
    assert(posts().length === before, "cancel confirmation prevents write");
    window.confirm = () => true;
    submit(form);
    await tick();
    assert(posts().length === before + 1 && posts().at(-1).body.confirmed,
      "one confirmed financial write");
    assert(messageText().includes("saved successfully"), "save feedback");
  }

  assert(money("89999999999999.99").endsWith(".99"), "exact kobo formatting");

  const search = $("receipt-search");
  const panel = $("receipt-panel");
  const receiptCalls = () => calls.filter(call => call.path.includes("/receipts?"));
  const authoritative = {
    business_name: "Authoritative <Shop>", reference: "REC / #1",
    recorded_at_utc: "2024-02-28T23:00:00+00:00",
    amount: "89999999999999.99", paid_at_sale: "0.01", due_at_sale: "89999999999999.98",
    customer_name: "<Musa>", category: "Transport", description: "Market delivery"
  };
  fetchReceipt = query => response({ ...authoritative, kind: query.get("kind") });
  for (const [form, kind, reference] of [
    [sale, "sale", saleValues.reference],
    [repayment, "repayment", repaymentValues.reference],
    [expense, "expense", expenseValues.reference]
  ]) {
    go(form.closest("[data-screen]").dataset.screen);
    const view = [...form.querySelectorAll("button")].find(item =>
      item.textContent === "View Receipt");
    assert(!view.hidden, kind + " receipt available after confirmed write");
    view.click();
    await tick();
    const request = receiptCalls().at(-1);
    assert(request.method === "GET" && request.options.cache === "no-store" &&
      request.options.headers.Authorization.startsWith("Bearer "), "authenticated receipt GET");
    assert(request.path.endsWith("kind=" + kind + "&transaction_id=" + reference + "-committed"),
      "receipt lookup uses saved ID");
    assert(!panel.hidden && panel.textContent.includes("₦89,999,999,999,999.99"),
      "receipt uses exact authoritative amount");
    assert(panel.textContent.includes("Authoritative <Shop>") && !panel.querySelector("shop"),
      "receipt displays business as text");
    assert(panel.textContent.includes("29 Feb 2024") && panel.textContent.includes("00:00:00"),
      "receipt renders Nigeria date and time");
    assert(panel.textContent.includes("has not verified an external payment"), "verification notice");
    assert(panel.getBoundingClientRect().width <= window.innerWidth, "mobile receipt fits");
    assert(form.getBoundingClientRect().height === 0, "receipt replaces the form while viewing");
    $("receipt-close").click();
    assert(panel.hidden && document.activeElement === view, "close restores focus");
  }

  go("receipts");
  enter(search, { kind: "sale", reference: authoritative.reference });
  submit(search);
  await tick();
  assert(decodeURIComponent(receiptCalls().at(-1).path.replace(/\+/g, " "))
    .endsWith("reference=REC / #1"), "search uses URL-encoded reference");
  assert(!panel.classList.contains("print-authorized"), "view alone does not enable printing");
  let prints = 0;
  window.print = () => {
    assert(!panel.hidden && panel.classList.contains("narrow") === (prints === 0),
      "selected print layout applied");
    assert(panel.classList.contains("print-authorized"), "print enabled after fresh lookup");
    assert(panel.textContent.includes("900.00"), "print uses freshly authorized receipt data");
    prints++;
    window.dispatchEvent(new Event("afterprint"));
  };
  $("receipt-paper").value = "narrow";
  fetchReceipt = () => response({ ...authoritative, kind: "sale", amount: "900.00" });
  const beforePrint = receiptCalls().length;
  $("receipt-print").click();
  await tick();
  assert(prints === 1 && receiptCalls().length === beforePrint + 1, "print rechecks access");
  $("receipt-paper").value = "a4";
  $("receipt-print").click();
  await tick();
  assert(prints === 2 && receiptCalls().length === beforePrint + 2, "A4 print rechecks access");
  assert(!panel.classList.contains("print-authorized"), "print permission clears after print");

  function assertNoStalePrint(label) {
    assert(panel.hidden && !$("receipt-details").textContent &&
      !$("receipt-business").textContent && !panel.classList.contains("print-authorized"),
      label + " clears receipt");
    const requests = receiptCalls().length;
    $("receipt-print").click();
    assert(prints === 2 && receiptCalls().length === requests, label + " blocks stale print");
  }

  $("receipt-close").click();
  assertNoStalePrint("closing receipt");
  submit(search);
  await tick();
  assert(!panel.hidden, "closed receipt can be reopened");
  fetchReceipt = () => rejected(404);
  $("receipt-print").click();
  await tick();
  assert(messageText() === "Receipt not found.", "print lookup failure feedback");
  assertNoStalePrint("failed print lookup");

  fetchReceipt = () => response({ ...authoritative, kind: "sale" });
  submit(search);
  await tick();
  assert(!panel.hidden, "receipt available before session expires");
  fetchReceipt = () => rejected(404);
  enter(search, { kind: "sale", reference: "MISSING" });
  submit(search);
  await tick();
  assert(messageText() === "Receipt not found.", "missing receipt feedback");
  assertNoStalePrint("failed receipt search");

  fetchReceipt = () => response({ ...authoritative, kind: "sale" });
  enter(search, { kind: "sale", reference: authoritative.reference });
  submit(search);
  await tick();
  assert(!panel.hidden, "receipt available before expired print attempt");
  fetchReceipt = () => rejected(401);
  $("receipt-print").click();
  await tick();
  assert($("dashboard").hidden, "expired session returns to sign-in");
  assertNoStalePrint("expired session");
  await signIn("owner@example.test");
  go("sales");

  enter(sale, { ...saleValues, reference: "" });
  window.confirm = () => true;
  submit(sale);
  await tick();
  assert(/^WEB-[a-f0-9]{32}$/.test(posts().at(-1).body.reference),
    "blank reference assigned on a confirmed save");

  let loseResponse;
  post = () => new Promise((_, reject) => { loseResponse = reject; });
  enter(sale, saleValues);
  const beforeLost = posts().length;
  submit(sale);
  submit(sale);
  await tick();
  assert(button(sale).textContent === "Saving..." && field(sale, "total").disabled,
    "pending request locks the form");
  assert(posts().length === beforeLost + 1, "double submit is blocked");
  loseResponse(new TypeError("Connection interrupted"));
  await tick();
  assert(!document.querySelector('[data-screen="recovery"]').hidden, "interrupted save opens Recovery");
  assert($("recovery-list").textContent.includes("SALE-1"), "reference remains visible");
  assert(button(sale).disabled && nav("sales").hasAttribute("data-pending"), "pending save blocks new writes");
  const check = () => [...$("recovery-list").querySelectorAll("button")].find(
    control => control.textContent === "Check saved transaction"
  );

  checkResult = () => { throw new TypeError("Offline"); };
  check().click();
  await tick();
  assert(messageText().includes("Try again when connected") && button(sale).disabled,
    "offline lookup leaves uncertainty and lock");
  checkResult = summary => response({ ...summary, status: "conflict" });
  check().click();
  await tick();
  assert($("recovery-list").textContent.includes("Reference already used") && button(sale).disabled,
    "conflict remains blocked");

  checkResult = () => rejected(401);
  check().click();
  await tick();
  assert($("dashboard").hidden && !$("recovery-list").textContent, "expiry clears visible recovery data");
  await signIn("other@example.test");
  go("recovery");
  assert(!check() && !$("recovery-list").textContent.includes("SALE-1"), "other business has no recovery details");
  $("logout").click();
  await tick();
  await signIn("owner@example.test");
  go("recovery");
  assert(check() && button(sale).disabled, "journal survives sign-out and sign-in");
  checkResult = summary => response({ ...summary, status: "committed", transaction_id: "recovered-sale" });
  check().click();
  await tick();
  assert($("recovery-list").textContent.includes("Verified as saved") && !button(sale).disabled,
    "checked match unlocks financial form");
  assert($("recovery-list").textContent.includes("View Receipt"), "verified record offers receipt");
  assert(posts().length === beforeLost + 1, "recovery never repeats financial POST");
  assert(checks().every(call => call.options.cache === "no-store"), "checks bypass browser cache");

})().then(
  () => parent.postMessage({ width: innerWidth, result: "PASS" }, "*"),
  error => parent.postMessage({ width: innerWidth, result: error.stack || String(error) }, "*")
);
