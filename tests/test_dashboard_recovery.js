(async () => {
  function assert(condition, label) {
    if (!condition) throw new Error(label);
  }

  const calls = [];
  const directory = [];
  let post = () => ({});
  let lookup = () => { throw new Error("Unexpected lookup"); };
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
    if (path.includes("/transactions/lookup")) return lookup(path);
    if (path.endsWith("/expenses") && method === "GET") return response([]);
    return post(body);
  };

  window.confirm = () => true;
  const submit = form => form.requestSubmit();
  const tick = () => new Promise(resolve => setTimeout(resolve, 0));
  const field = (form, name) => form.elements.namedItem(name);
  const button = form => form.querySelector('[type="submit"]');
  const check = form => form.querySelector('[type="button"]');
  const messageText = () => $("message").textContent;
  const posts = () => calls.filter(call => call.method === "POST" &&
    /\/(sales|repayments|expenses)$/.test(call.path));
  const lookups = () => calls.filter(call => call.path.includes("/transactions/lookup"));

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

  function guardNavigation() {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }

  const sale = $("sale-form");
  const repayment = $("repayment-form");
  const expense = $("expense-form");
  await signIn("owner@example.test");
  assert(window.innerWidth === 360, "mobile viewport");
  assert(document.documentElement.scrollWidth <= window.innerWidth, "mobile overflow");
  assert(Math.abs(sale.getBoundingClientRect().left -
    expense.getBoundingClientRect().left) < 1, "mobile forms stack");
  assert($("gross-sales").textContent.endsWith("250.01"), "rendered report");

  enter($("customer-form"), { name: "<Musa>" });
  submit($("customer-form"));
  await tick();
  assert(field(sale, "customer_id").options[1].textContent === "<Musa>", "customer picker");
  assert($("customers").textContent.includes("<Musa>"), "customer renders as text");

  const saleValues = { customer_id: "musa", reference: "SALE-1", total: "250.01", paid: "100" };
  const repaymentValues = { customer_id: "musa", reference: "DEBT-1", amount: "50" };
  const expenseValues = {
    reference: "EXP-1", category: "Transport", description: "Delivery", amount: "40"
  };

  post = () => response({}, 201);
  for (const [form, values] of [[sale, saleValues], [repayment, repaymentValues],
                                [expense, expenseValues]]) {
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

  const badSale = { ...saleValues, total: "bad", paid: "bad" };
  assert(!sameTransaction("sale", badSale, { ...badSale, kind: "sale", found: true }),
    "two malformed sale amounts must differ");
  for (const [kind, values] of [["repayment", repaymentValues], ["expense", expenseValues]]) {
    for (const amount of [null, [], "bogus", "0", "90000000000000.01"]) {
      const bad = { ...values, amount };
      assert(!sameTransaction(kind, bad, { ...bad, kind, found: true }),
        "invalid matching " + kind + " amount");
    }
  }
  assert(money("89999999999999.99").endsWith(".99"), "exact kobo formatting");

  const miss = { found: false, kind: "sale", reference: "SALE-1" };
  for (const status of [400, 422]) {
    post = () => rejected(status);
    lookup = () => response(miss);
    enter(sale, saleValues);
    submit(sale);
    await tick();
    assert(!button(sale).disabled && messageText().includes("rejected"),
      "known rejection permits correction " + status);
  }
  const beforeAuthRejections = lookups().length;
  for (const status of [403, 401]) {
    post = () => rejected(status);
    enter(sale, saleValues);
    submit(sale);
    await tick();
    assert(lookups().length === beforeAuthRejections && !guardNavigation(),
      "authorization rejection clears pending " + status);
  }
  assert($("dashboard").hidden, "expired POST session hides dashboard");
  await signIn("owner@example.test");

  let loseResponse;
  let saved;
  post = body => {
    saved = { ...body, found: true, kind: "sale" };
    return new Promise((_, reject) => { loseResponse = reject; });
  };
  lookup = () => response(miss);
  enter(sale, saleValues);
  const beforeLost = posts().length;
  submit(sale);
  submit(sale);
  assert(guardNavigation() && field(sale, "total").disabled, "pending submit locks fields and guards refresh");
  assert(posts().length === beforeLost + 1, "double submit");
  field(sale, "total").value = "25";
  loseResponse(new TypeError("Connection interrupted"));
  await tick();
  assert(button(sale).disabled && !check(sale).hidden, "lookup miss keeps pending");
  assert(messageText().includes("uncertain"), "unknown status feedback");

  lookup = () => response({ unexpected: true });
  check(sale).click();
  await tick();
  assert(button(sale).disabled && messageText().includes("invalid response"), "malformed lookup");
  lookup = () => response({ ...saved, total: "25" });
  check(sale).click();
  await tick();
  assert(button(sale).disabled && messageText().includes("REFERENCE CONFLICT"), "reference conflict");

  lookup = () => rejected(401);
  check(sale).click();
  await tick();
  assert($("dashboard").hidden && guardNavigation(), "expired lookup preserves pending");
  assert(!$("customers").textContent, "old tenant customer data cleared");
  await signIn("other@example.test");
  const beforeOther = lookups().length;
  assert(check(sale).hidden && !button(sale).disabled, "pending state scoped to business");
  check(sale).click();
  await tick();
  assert(lookups().length === beforeOther, "other business cannot check prior reference");
  $("logout").click();
  await tick();
  assert($("dashboard").hidden, "logout");
  await signIn("owner@example.test");
  assert(!check(sale).hidden && button(sale).disabled, "original business can recover after sign-in");
  lookup = () => response({ ...saved, paid: "100.00" });
  check(sale).click();
  await tick();
  assert(messageText().includes("verified as saved") && !button(sale).disabled,
    "lookup verifies original snapshot despite form edit");
  assert(posts().length === beforeLost + 1, "recovery never repeats POST");
  assert(lookups().every(call => call.method === "GET" && call.options.cache === "no-store"),
    "lookups use fresh GETs");
  assert(!guardNavigation(), "navigation allowed after verification");
})().then(
  () => parent.postMessage("PASS", "*"),
  error => parent.postMessage(error.stack || String(error), "*")
);
