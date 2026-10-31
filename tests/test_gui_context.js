// Runtime regressions for the actual dashboard controller, without browser dependencies.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");


class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(n => this.classes.add(n)),
      remove: (...names) => names.forEach(n => this.classes.delete(n)),
      contains: n => this.classes.has(n),
      toggle: (n, on) => {
        const enabled = on === undefined ? !this.classes.has(n) : on;
        if (enabled) this.classes.add(n);
        else this.classes.delete(n);
        return enabled;
      },
    };
  }
  set className(value) { this.classes = new Set(value.split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classes].join(" "); }
  set innerHTML(value) {
    this.html = value;
    this.children = [];
    // Only the interactive leaf elements used by these scenarios need parsing.
    for (const match of value.matchAll(/<(button|option)\b([^>]*)>([\s\S]*?)<\/\1>/g)) {
      const el = new Element(match[1]);
      for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) {
        el.setAttribute(attr[1], attr[2]);
      }
      el.textContent = match[3];
      this.appendChild(el);
    }
  }
  get innerHTML() { return this.html || ""; }
  get options() { return this.children; }
  get text() { return this.textContent; }
  set text(value) { this.textContent = value; }
  appendChild(el) { this.children.push(el); el.parent = this; return el; }
  prepend(el) { this.children.unshift(el); el.parent = this; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "class") this.className = value;
    if (name === "value") this.value = value;
    if (name.startsWith("data-")) this.dataset[name.slice(5)] = value;
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  matches(selector) {
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    const data = selector.match(/^\[([\w-]+)="([^"]*)"\]$/);
    return data ? this.getAttribute(data[1]) === data[2] : false;
  }
  querySelectorAll(selector) {
    return this.children.flatMap(c => [
      ...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async fire(name, extra = {}) {
    const event = { target: this, preventDefault() {}, stopPropagation() {}, ...extra };
    await Promise.all((this.listeners[name] || []).map(fn => fn(event)));
  }
  async click() { if (!this.disabled) await this.fire("click"); }
  scrollIntoView() {}
}

function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "fpl_manager", "gui", "static", "app.js"), "utf8",
);
const html = fs.readFileSync(
  path.join(__dirname, "..", "src", "fpl_manager", "gui", "static", "index.html"), "utf8",
);

async function harness() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const tabs = [...html.matchAll(/<button class="([^"]*\btab-btn\b[^"]*)" data-tab="([^"]+)"/g)].map(([, classes, name]) => {
    const tab = new Element("button");
    tab.className = classes;
    tab.setAttribute("data-tab", name);
    return tab;
  });
  const panes = tabs.map(tab => element(`tab-${tab.dataset.tab}`));
  panes[0].classList.add("active");
  const requests = [];
  let route = () => ({});
  const errors = [];
  const sandbox = vm.createContext({
    console: { log() {}, warn(...args) { errors.push(args); }, error(...args) { errors.push(args); } },
    document: {
      getElementById: element,
      createElement: tag => new Element(tag),
      addEventListener() {}, // Explicitly initialize only relevant actual handlers.
      querySelector: selector => {
        if (selector === ".tabs-nav .tab-btn.active") {
          return tabs.find(t => t.classList.contains("active")) || null;
        }
        const name = selector.match(/^\.tabs-nav \.tab-btn\[data-tab="([^"]+)"\]$/);
        return name ? tabs.find(t => t.dataset.tab === name[1]) || null : null;
      },
      querySelectorAll: selector => {
        if (selector === ".tabs-nav .tab-btn") return tabs;
        if (selector === ".mode-live-only") return tabs.filter(t => t.classList.contains("mode-live-only"));
        if (selector === ".tab-pane") return panes;
        return [];
      },
    },
    fetch: async (url, options) => {
      requests.push({ url, method: options.method || "GET", body: options.body && JSON.parse(options.body) });
      const data = await route(url, options);
      return { ok: true, json: async () => data };
    },
    setTimeout() {},
    clearTimeout() {},
    confirm: () => true,
    alert() {},
    window: {},
    localStorage: {
      values: new Map(),
      getItem(key) { return this.values.get(key) || null; },
      setItem(key, value) { this.values.set(key, String(value)); },
      removeItem(key) { this.values.delete(key); },
    },
  });
  vm.runInContext(source, sandbox, { filename: "app.js" });
  const run = script => vm.runInContext(script, sandbox);
  const state = run("state");
  const hist = run("histState");
  state.activeTeamId = "live";
  element("dec-chip").innerHTML = ["", "wildcard", "freehit", "benchboost", "triplecaptain"]
    .map(value => `<option value="${value}">${value}</option>`).join("");
  element("hist-chip-select").innerHTML = ["", "wildcard", "free_hit", "bench_boost", "triple_captain"]
    .map(value => `<option value="${value}">${value}</option>`).join("");
  run("initModality(); initEventListeners(); initHistoricalTimeMachine(); initStrategicStudio(); initTabs();");
  await settle();
  requests.length = 0;
  errors.length = 0;
  return {
    run, state, hist, element, requests, errors, tabs,
    route: fn => { route = fn; },
    async select(id, value) { element(id).value = String(value); await element(id).fire("change"); },
    assertNoErrors() { assert.deepEqual(errors, [], "controller emitted an unexpected runtime error"); },
  };
}

function session(id, captain = 1) {
  return {
    session_id: id, season: "2023-24", current_gw: 5, free_transfers: 1,
    chips_remaining: ["wildcard_1", "wildcard_2", "free_hit"], history: [],
    squad: [1, 2, 3].map(player_id => ({
      player_id, id: player_id, name: `Player ${player_id}`, pos_abbr: "MID",
      is_starter: true, is_captain: player_id === captain, is_vice_captain: player_id !== captain,
    })),
  };
}

function defaults(url) {
  if (url.startsWith("/api/squad?")) return {
    gameweek: 12, state: { chips_remaining: [], active_chip: null }, players: [], financials: {},
  };
  if (url.startsWith("/api/lineup?")) return { gameweek: 12, starters: [], bench: [] };
  if (url.includes("/lineup?")) return { gameweek: 5, starters: [], bench: [] };
  if (url.startsWith("/api/decisions")) return { decisions: [] };
  if (url === "/api/historical/simulations") return {
    simulations: [{ session_id: "A", season: "2023-24", current_gw: 5 }],
  };
  if (/\/simulations\/[AB]$/.test(url)) return session(url.endsWith("A") ? "A" : "B");
  return {};
}

test("live writes carry the loaded revision and adopt only their matching receipt", async () => {
  const h = await harness();
  h.state.currentSquad = {
    revision: 4, command_context: { mode: "live", team_id: "live", season: "2026/27", gameweek: 12 },
  };
  h.route(() => ({
    success: true,
    command: { context: h.state.currentSquad.command_context, revision_after: 5 },
  }));
  await h.run('api("/api/decisions", {method:"POST",body:JSON.stringify({team_id:"live",gameweek:12})})');
  const body = h.requests[0].body;
  assert.equal(body.expected_revision, 4);
  assert.equal(body.command_context.team_id, "live");
  assert.ok(body.command_id);
  assert.equal(h.state.currentSquad.revision, 5);
  h.assertNoErrors();
});

test("a delayed command receipt cannot replace another team's revision", async () => {
  const h = await harness();
  h.state.currentSquad = {
    revision: 4, command_context: { mode: "live", team_id: "live", season: "2026/27", gameweek: 12 },
  };
  const response = deferred();
  h.route(() => response.promise);
  const pending = h.run('api("/api/decisions", {method:"POST",body:JSON.stringify({team_id:"live",gameweek:12})})');
  h.state.contextEpoch++;
  h.state.activeTeamId = "next";
  h.state.currentSquad = {
    revision: 2, command_context: { mode: "live", team_id: "next", season: "2026/27", gameweek: 12 },
  };
  response.resolve({
    command: { context: { mode: "live", team_id: "live" }, revision_after: 5 },
  });
  await pending;
  assert.equal(h.state.currentSquad.revision, 2);
  h.assertNoErrors();
});

for (const mode of ["live", "historical"]) {
  test(`older ${mode} receipts cannot regress revisions or run successful continuations`, async () => {
    const h = await harness();
    h.state.appMode = mode;
    h.hist.sessionId = mode === "historical" ? "A" : null;
    const context = mode === "historical"
      ? { mode, session_id: "A", season: "2023-24", gameweek: 5 }
      : { mode, team_id: "live", season: "2026/27", gameweek: 12 };
    const setState = revision => {
      const data = { revision, command_context: context };
      if (mode === "historical") h.hist.sessionData = data;
      else h.state.currentSquad = data;
    };
    setState(4);
    const response = deferred();
    h.route(() => response.promise);
    const endpoint = mode === "historical" ? "/api/historical/simulations/A/chip" : "/api/decisions";
    const body = mode === "historical" ? { chip: null } : { team_id: "live", gameweek: 12 };
    const pending = h.run(`(async () => {
      await api(${JSON.stringify(endpoint)}, {method:"POST",body:${JSON.stringify(JSON.stringify(body))}});
      document.getElementById("stale-continuation").textContent = "ran";
    })()`);
    setState(6);
    response.resolve({
      success: true,
      command: { context, command_id: "older-command", revision_after: 5 },
    });
    await assert.rejects(pending, error =>
      error.code === "STALE_COMMAND_RESPONSE" && error.committed === true);
    const selected = mode === "historical" ? h.hist.sessionData : h.state.currentSquad;
    assert.equal(selected.revision, 6);
    assert.equal(h.element("stale-continuation").textContent, "");
    assert.equal(h.requests.length, 1);
  });

  test(`equal ${mode} idempotency receipts remain usable`, async () => {
    const h = await harness();
    h.state.appMode = mode;
    h.hist.sessionId = mode === "historical" ? "A" : null;
    const context = mode === "historical"
      ? { mode, session_id: "A", season: "2023-24", gameweek: 5 }
      : { mode, team_id: "live", season: "2026/27", gameweek: 12 };
    const selected = { revision: 6, command_context: context };
    if (mode === "historical") h.hist.sessionData = selected;
    else h.state.currentSquad = selected;
    h.route(() => ({
      success: true, command: { context, command_id: "replayed-command", revision_after: 6 },
    }));
    const endpoint = mode === "historical" ? "/api/historical/simulations/A/chip" : "/api/decisions";
    const body = { expected_revision: 5, command_id: "replayed-command" };
    if (mode === "live") body.team_id = "live";
    const result = await h.run(`api(${JSON.stringify(endpoint)}, {
      method:"POST",body:${JSON.stringify(JSON.stringify(body))}
    })`);
    assert.equal(result.success, true);
    assert.equal(selected.revision, 6);
    h.assertNoErrors();
  });
}

test("a calculation's original revision is not replaced by a newer HUD revision", async () => {
  const h = await harness();
  h.state.currentSquad = {
    revision: 8, command_context: { mode: "live", team_id: "live", season: "2026/27", gameweek: 12 },
  };
  h.route(() => ({ success: true }));
  await h.run('api("/api/plan/apply-step", {method:"POST",body:JSON.stringify({team_id:"live",expected_revision:6})})');
  assert.equal(h.requests[0].body.expected_revision, 6);
  h.assertNoErrors();
});

test("Strategic Studio applies the candidate revision rather than the latest HUD revision", async () => {
  const h = await harness();
  h.state.currentSquad = {
    revision: 8, command_context: { mode: "live", team_id: "live", season: "2026/27", gameweek: 1 },
  };
  h.run(`strategicState.previousCandidate = {
    strategy:"balanced", mode:"initial", revision:6,
    command_context:{mode:"live",team_id:"live",season:"2026/27",gameweek:1}
  };`);
  h.route(() => ({ success: false }));
  await h.element("btn-apply-strategic-squad").click();
  const applied = h.requests.find(request => request.url === "/api/strategic-squad/apply");
  assert.ok(applied);
  assert.equal(applied.body.expected_revision, 6);
  h.assertNoErrors();
});

test("historical writes carry session revisions and cannot fall back to a live team", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.hist.sessionData = {
    revision: 7, command_context: { mode: "historical", session_id: "A", season: "2023-24", gameweek: 5 },
  };
  h.route(() => ({ success: true }));
  await h.run('api("/api/historical/simulations/A/chip", {method:"POST",body:JSON.stringify({chip:null})})');
  assert.equal(h.requests[0].body.expected_revision, 7);
  assert.equal(h.requests[0].body.command_context.session_id, "A");
  await assert.rejects(h.run('api("/api/decisions", {method:"POST",body:"{}"})'), /selected simulation/);
  assert.equal(h.requests.length, 1);
  h.assertNoErrors();
});

test("read-only archives render normally but never submit mutation requests", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(url => url === "/api/historical/simulations/A"
    ? { ...session("A"), read_only: true, execution_version: "v146" } : defaults(url));
  await h.run('loadHistoricalSession("A")');
  assert.ok(h.run("getHistoricalMutationContext()"), "read context must remain usable");
  assert.equal(h.element("hist-archive-notice").style.display, "block");
  assert.equal(h.element("btn-hist-run-gw").disabled, true);
  assert.equal(h.element("btn-execute-trade").disabled, true);
  const count = h.requests.length;
  await assert.rejects(
    h.run('api("/api/historical/simulations/A/chip", {method:"POST",body:"{}"})'),
    /read-only archive/,
  );
  assert.equal(h.requests.length, count);
  await h.element("btn-mode-live").click();
  assert.equal(h.element("hist-archive-notice").style.display, "none");
  h.assertNoErrors();
});

test("explicit fork preserves archive controls and hydrates the corrected session", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(url => {
    if (url === "/api/historical/simulations/A") return { ...session("A"), read_only: true };
    if (url.endsWith("/fork")) return { session_id: "B" };
    if (url === "/api/historical/simulations") return {
      simulations: ["A", "B"].map(session_id => ({ session_id, season: "2023-24", current_gw: 5 })),
    };
    return defaults(url);
  });
  await h.run('loadHistoricalSession("A")');
  await h.element("btn-hist-fork").click();
  assert.equal(h.requests.filter(request => request.url.endsWith("/fork")).length, 1);
  assert.equal(h.hist.sessionId, "B");
  assert.equal(h.element("hist-archive-notice").style.display, "none");
  assert.equal(h.element("btn-hist-run-gw").disabled, false);
  h.assertNoErrors();
});

test("historical continuation cannot overwrite live GW after its lineup finishes", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  const lineup = deferred();
  h.route(url => url.includes("/A/lineup?") ? lineup.promise : defaults(url));
  const pending = h.run('loadHistoricalSession("A")');
  await settle();
  h.assertNoErrors();
  assert.equal(h.requests.some(r => r.url.includes("/A/lineup?")), true, JSON.stringify(h.requests));
  await h.element("btn-mode-live").click();
  assert.equal(Number(h.element("dec-gw").value), 12);
  const requestCount = h.requests.length;
  lineup.resolve({ gameweek: 5, starters: [], bench: [] });
  await pending;
  assert.equal(Number(h.element("dec-gw").value), 12, "old simulation must not replace the live form");
  assert.equal(h.requests.length, requestCount, "stale continuation must not start more loaders");
  await h.element("form-log-decision").fire("submit");
  assert.equal(h.requests.findLast(r => r.method === "POST").body.gameweek, 12);
  h.assertNoErrors();
});

test("staged transfer banner is rebound after a same-GW session refresh", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  let staged = [{ out_id: 1, in_id: 4, out_name: "One", in_name: "Four", cost_tenths: 0 }];
  h.route((url, opts) => {
    if (url.endsWith("/A")) return { ...session("A"), transfers_staged: staged };
    if (url.endsWith("/transfers") && opts.method === "POST") {
      staged = [];
      return {};
    }
    return defaults(url);
  });
  await h.run('loadHistoricalSession("A")');
  const container = h.element("tx-results-container");
  const oldRevert = container.querySelector(".btn-clear-staged");
  assert.ok(oldRevert);
  await h.run('loadHistoricalSession("A")');
  const count = h.requests.length;
  await oldRevert.click();
  assert.equal(h.requests.length, count, "detached banner must retain its old provenance guard");
  const currentRevert = container.querySelector(".btn-clear-staged");
  assert.ok(currentRevert);
  await currentRevert.click();
  const clear = h.requests.findLast(r => r.method === "POST" && r.url.endsWith("/transfers"));
  assert.ok(clear, "the current banner must remain actionable after hydration replaces sessionData");
  assert.equal(clear.url, "/api/historical/simulations/A/transfers");
  assert.equal(clear.body.action, "clear");
  assert.equal(container.querySelector(".hist-staged-banner"), null);
  h.assertNoErrors();
});

test("staging a first trade during the same GW creates a current banner", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A")');
  const container = h.element("tx-results-container");
  const proposition = new Element("div");
  proposition.className = "retained-proposition";
  container.appendChild(proposition);
  h.route(url => url.endsWith("/A") ? {
    ...session("A"), transfers_staged: [{ out_id: 1, in_id: 4, out_name: "One", in_name: "Four" }],
  } : defaults(url));
  await h.run('loadHistoricalSession("A")');
  assert.ok(container.querySelector(".btn-clear-staged"));
  assert.equal(container.querySelector(".retained-proposition"), proposition);
  h.assertNoErrors();
});

test("live continuation stops before squad/player reads when historical mode takes over", async () => {
  const h = await harness();
  const overview = deferred();
  h.route(url => url.startsWith("/api/overview?") ? overview.promise : defaults(url));
  const live = h.element("btn-mode-live").click();
  await settle();
  await h.element("btn-mode-historical").click();
  await settle();
  const count = h.requests.length;
  overview.resolve({});
  await live;
  await settle();
  await settle();
  assert.equal(h.requests.slice(count).some(r => /^\/api\/(squad|lineup|players)\?/.test(r.url)), false);
  assert.equal(Number(h.element("dec-gw").value), 5);
  h.assertNoErrors();
});

test("session switch detaches squad and blocks all mutations until B is hydrated", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A")');
  h.assertNoErrors();
  const b = deferred();
  h.route((url, opts) => url.endsWith("/B") && !opts.method ? b.promise : defaults(url));
  const switching = h.select("hist-session-select", "B");
  await settle();
  assert.equal(h.hist.sessionData, null, "A's data must be detached while B is pending");
  assert.equal(h.element("btn-hist-save-lineup").disabled, true);
  const before = h.requests.filter(r => r.method === "POST").length;
  await h.element("btn-hist-save-lineup").click();
  await Promise.all([
    h.run("saveHistoricalLineupFromSquad()"), h.run("updateHistoricalLineupRoles(1, 2)"),
    h.run("stageHistoricalTransfer(1, 4)"),
  ]);
  h.element("tx-exec-out").value = "1";
  h.element("tx-exec-in").value = "Incoming";
  await h.element("btn-execute-trade").fire("click");
  await h.element("hist-chip-select").fire("change");
  await h.element("btn-hist-run-gw").click();
  await h.element("btn-hist-auto-lineup").click();
  await h.element("form-log-decision").fire("submit");
  assert.equal(h.requests.filter(r => r.method === "POST").length, before);
  b.resolve(session("B", 2));
  await switching;
  await h.element("btn-hist-save-lineup").click();
  const saved = h.requests.findLast(r => r.method === "POST" && r.url.endsWith("/lineup"));
  assert.equal(saved.url, "/api/historical/simulations/B/lineup");
  assert.equal(saved.body.captain_id, 2, "same player IDs must not carry A's captain into B");
  h.assertNoErrors();
});

test("old historical pitch callbacks cannot mutate a newly loaded identical squad", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A");');
  h.run("renderHistoricalPitch(histState.sessionData.squad)");
  const oldCaptain = h.element("hist-pitch-mid").children[0].querySelector('[data-act="cap"]');
  assert.ok(oldCaptain);
  h.route(url => url.endsWith("/B") ? session("B", 2) : defaults(url));
  await h.select("hist-session-select", "B");
  const count = h.requests.length;
  await oldCaptain.click();
  assert.equal(h.requests.length, count, "detached A card must not assign A captain in B");
  assert.equal(h.hist.sessionData.squad.find(p => p.is_captain).player_id, 2);
  h.assertNoErrors();
});

test("current historical pitch quick actions work with independently fetched lineup objects", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(url => url.includes("/A/lineup?") ? {
    gameweek: 5, squad: session("A").squad, starters: session("A").squad, bench: [],
  } : defaults(url));
  await h.run('loadHistoricalSession("A")');
  const swap = h.element("hist-pitch-mid").children[0].querySelector('[data-act="swap"]');
  assert.ok(swap);
  await swap.click();
  assert.equal(h.hist.subbingPlayer?.player_id, 1, "lineup and session GETs deserialize different objects");
  h.assertNoErrors();
});

test("historical auto-lineup stops between its recommendation GET and lineup POST", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A")');
  const recs = deferred();
  h.route(url => url.endsWith("/recommendations") ? recs.promise : defaults(url));
  const pending = h.element("btn-hist-auto-lineup").click();
  await h.select("hist-session-select", "B");
  const count = h.requests.length;
  recs.resolve({
    recommended_starters: [1, 2, 3], recommended_bench: [], recommended_captain: 1,
  });
  await pending;
  assert.equal(h.requests.length, count);
  h.assertNoErrors();
});

test("historical recommendation apply stops between POSTs when session changes", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A")');
  h.run(`showHistoricalRecommendationsModal({
    gameweek: 5, recommended_transfers: [{out_id: 1, in_id: 4, out_name: "One", in_name: "Four"}]
  })`);
  const clear = deferred();
  h.route((url, opts) => url.endsWith("/transfers") && opts.method === "POST"
    ? clear.promise : defaults(url));
  const pending = h.element("btn-hist-apply-all-recs").click();
  await h.select("hist-session-select", "B");
  const count = h.requests.length;
  clear.resolve({});
  await pending;
  assert.equal(h.requests.length, count, "A recommendations must not continue posting into B");
  h.assertNoErrors();
});

test("a stale historical overview continuation starts no decision reload in live mode", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  const overview = deferred();
  h.route(url => url.startsWith("/api/historical/overview?") ? overview.promise : defaults(url));
  const pending = h.run('loadHistoricalSession("A")');
  await settle();
  await h.element("btn-mode-live").click();
  const count = h.requests.length;
  overview.resolve({});
  await pending;
  assert.equal(h.requests.length, count);
  assert.equal(Number(h.element("dec-gw").value), 12);
  h.assertNoErrors();
});

test("a live squad response cannot hydrate historical controls or start a live lineup read", async () => {
  const h = await harness();
  const squad = deferred();
  h.route(url => url.startsWith("/api/squad?") ? squad.promise : defaults(url));
  const pending = h.run("refreshActiveTeamData()");
  await h.element("btn-mode-historical").click();
  const count = h.requests.length;
  squad.resolve(defaults("/api/squad?"));
  await pending;
  assert.equal(h.requests.length, count);
  assert.equal(Number(h.element("dec-gw").value), 5);
  h.assertNoErrors();
});

for (const contextChange of ["gameweek", "mode", "session", "team"]) {
  test(`target-GW decisions ignore a delayed response after ${contextChange} changes`, async () => {
    const h = await harness();
    h.state.appMode = "historical";
    h.hist.sessionId = "A";
    const old = deferred();
    let first = true;
    h.route(url => {
      if (first && url.startsWith("/api/decisions?")) { first = false; return old.promise; }
      if (url.startsWith("/api/decisions?")) return {
        decisions: [{ gameweek: 12, notes: "current", chip_played: null }],
      };
      return defaults(url);
    });
    const pending = h.select("dec-gw", 5);
    if (contextChange === "gameweek") await h.select("dec-gw", 12);
    if (contextChange === "mode") {
      await h.element("btn-mode-live").click();
      await settle();
    }
    if (contextChange === "session") h.hist.sessionId = "B";
    if (contextChange === "team") h.state.activeTeamId = "other";
    h.element("dec-notes").value = "current";
    h.element("dec-chip").value = "";
    old.resolve({ decisions: [{ gameweek: 5, notes: "stale", chip_played: "free_hit" }] });
    await pending;
    assert.equal(h.element("dec-notes").value, "current");
    assert.equal(h.element("dec-chip").value, "");
    if (contextChange === "mode") {
      await h.element("form-log-decision").fire("submit");
      const saved = h.requests.findLast(r => r.method === "POST").body;
      assert.equal(saved.gameweek, 12);
      assert.equal(saved.notes, "current");
      assert.equal(saved.chip, null);
    }
    h.assertNoErrors();
  });
}

test("target-GW request sequence rejects the first GW5 response after GW5-GW6-GW5", async () => {
  const h = await harness();
  const old = deferred();
  let first = true;
  h.route(url => {
    if (url.startsWith("/api/decisions?") && first) { first = false; return old.promise; }
    return { decisions: [{ gameweek: 5, notes: "latest" }] };
  });
  const pending = h.select("dec-gw", 5);
  await h.select("dec-gw", 6);
  await h.select("dec-gw", 5);
  old.resolve({ decisions: [{ gameweek: 5, notes: "stale", chip_played: "free_hit" }] });
  await pending;
  assert.equal(h.element("dec-notes").value, "latest");
  assert.equal(h.element("dec-chip").value, "");
  h.assertNoErrors();
});

test("Studio Generate stays disabled until the current configuration is ready", async () => {
  const h = await harness();
  const config = deferred();
  h.route(url => url.startsWith("/api/strategic-squad/config") ? config.promise : defaults(url));
  const pending = h.run("loadStrategicStudio()");
  const gen = h.element("btn-generate-strategic");
  assert.equal(gen.disabled, true);
  await gen.click();
  assert.equal(h.requests.some(r => r.url.endsWith("/optimize")), false);
  config.resolve({ players: [{ id: 1, name: "One" }] });
  await pending;
  assert.equal(gen.disabled, false);
  assert.equal(h.element("strategic-player-search").disabled, false);
  assert.equal(h.run("strategicState.allPlayers.length"), 1);
  h.assertNoErrors();
});

test("stale Studio solve finally cannot re-enable controls in the next loading context", async () => {
  const h = await harness();
  const solve = deferred();
  h.route(url => url.endsWith("/optimize") ? solve.promise : { players: [{ id: 1, name: "One" }] });
  await h.run("loadStrategicStudio()");
  const pending = h.element("btn-generate-strategic").click();
  h.state.activeTeamId = "other";
  const config = deferred();
  h.route(() => config.promise);
  const loading = h.run("loadStrategicStudio()");
  solve.resolve({ squad: [{ id: 1 }], strategy: "maximum_ev" });
  await pending;
  assert.equal(h.run("Object.keys(strategicState.candidates).length"), 0);
  assert.equal(h.element("btn-generate-strategic").disabled, true);
  assert.equal(h.element("strategic-player-search").disabled, true);
  config.resolve({ players: [{ id: 2, name: "Two" }] });
  await loading;
  assert.equal(h.run("strategicState.allPlayers[0].id"), 2);
  h.assertNoErrors();
});

test("stale Studio config cannot replace the next context's pool", async () => {
  const h = await harness();
  const old = deferred();
  h.route(() => old.promise);
  const pending = h.run("loadStrategicStudio()");
  h.state.activeTeamId = "other";
  h.route(() => ({ players: [{ id: 2, name: "Two" }] }));
  await h.run("loadStrategicStudio()");
  old.resolve({ players: [{ id: 1, name: "One" }] });
  await pending;
  assert.equal(h.run("strategicState.allPlayers[0].id"), 2);
  h.assertNoErrors();
});

test("Studio configuration refresh and optimization have independent request lifecycles", async () => {
  const h = await harness();
  const solve = deferred();
  h.route(url => url.endsWith("/optimize") ? solve.promise : { players: [{ id: 1, name: "One" }] });
  await h.run("loadStrategicStudio()");
  const solving = h.element("btn-generate-strategic").click();
  await h.run("loadStrategicStudio()");
  assert.equal(h.run("strategicState.allPlayers.length"), 1);
  assert.equal(h.element("btn-generate-strategic").disabled, true, "solve still owns its button");
  solve.resolve({});
  await solving;
  assert.equal(h.element("btn-generate-strategic").disabled, false);
  h.assertNoErrors();
});

test("Studio reoptimization completion restores both buttons after a configuration refresh", async () => {
  const h = await harness();
  const configData = { players: [{ id: 1, name: "One" }] };
  h.route(() => configData);
  await h.run("loadStrategicStudio()");
  h.run("strategicState.previousCandidate = { _context: getStrategicStudioContext() }");
  await h.run("loadStrategicStudio()");
  const reopt = h.element("btn-reoptimize-strategic");
  assert.equal(reopt.disabled, false);
  const solve = deferred();
  const config = deferred();
  h.route(url => url.endsWith("/reoptimize") ? solve.promise : config.promise);
  const solving = reopt.click();
  assert.ok(h.requests.some(r => r.url.endsWith("/reoptimize") && r.method === "POST"));
  const loading = h.run("loadStrategicStudio()");
  config.resolve(configData);
  await loading;
  assert.equal(h.run("strategicState.configReady"), true);
  assert.equal(h.element("btn-generate-strategic").disabled, true);
  solve.resolve({});
  await solving;
  assert.equal(h.run("strategicState.solving"), false);
  assert.equal(h.element("btn-generate-strategic").disabled, false);
  assert.equal(reopt.disabled, false);
  h.assertNoErrors();
});

test("Decision Logger entry uses hydrated live chips, not an all-chips fallback", async () => {
  const h = await harness();
  for (const [remaining, active] of [
    [[], null], [["bench_boost"], null], [[], "triple_captain"],
  ]) {
    h.route(url => url.startsWith("/api/squad?") ? {
      ...defaults(url), state: { chips_remaining: remaining, active_chip: active },
    } : defaults(url));
    await h.run("loadSquadHUD()");
    const decTab = h.tabs.find(t => t.dataset.tab === "decisions");
    await decTab.click();
    const options = Object.fromEntries(h.element("dec-chip").options.map(o => [o.value, !o.disabled]));
    assert.equal(options.wildcard, false);
    assert.equal(options.freehit, false);
    assert.equal(options.benchboost, remaining.length > 0);
    assert.equal(options.triplecaptain, !!active);
    assert.equal(h.element("dec-chip").value, active ? "triplecaptain" : "");
  }
  h.assertNoErrors();
});

test("unknown live chip availability stays closed while hydration is pending", async () => {
  const h = await harness();
  const overview = deferred();
  h.route(url => url.startsWith("/api/overview?") ? overview.promise : defaults(url));
  const live = h.element("btn-mode-live").click();
  assert.equal(h.element("dec-chip").options.filter(o => o.value && !o.disabled).length, 0);
  overview.resolve({});
  await live;
  h.assertNoErrors();
});

test("historical-to-live switch does not enable unavailable chips even before hydration", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.state.currentSquad = { state: { chips_remaining: [], active_chip: "bench_boost" } };
  h.hist.sessionData = session("A");
  const overview = deferred();
  h.route(url => url.startsWith("/api/overview?") ? overview.promise : defaults(url));
  const live = h.element("btn-mode-live").click();
  const chips = h.element("dec-chip");
  assert.equal(chips.options.find(o => o.value === "wildcard").disabled, true);
  assert.equal(chips.value, "benchboost");
  overview.resolve({});
  await live;
  await settle();
  await settle();
});

test("canonical chip aliases and historical wildcard windows remain intact", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.hist.gameweek = 5;
  h.run('updateDecisionLoggerChipOptions(["wildcard_2", "bench_boost"], "free_hit")');
  assert.equal(h.element("dec-chip").options.find(o => o.value === "wildcard").disabled, true);
  assert.equal(h.element("dec-chip").value, "freehit");
  h.hist.gameweek = 20;
  h.run('updateDecisionLoggerChipOptions(["wildcard_2"], "triple_captain")');
  assert.equal(h.element("dec-chip").options.find(o => o.value === "wildcard").disabled, false);
  assert.equal(h.element("dec-chip").value, "triplecaptain");
});

test("no-session decision history and empty-session switch never fall back to live data", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.hist.sessionId = null;
  h.hist.playerPool = [{ id: 4, name: "Old" }];
  const count = h.requests.length;
  await h.run("loadDecisions()");
  assert.equal(h.requests.length, count);
  await h.select("hist-session-select", "");
  assert.equal(h.hist.playerPool.length, 0);
  assert.equal(h.element("available-players-datalist").children.length, 0);
  assert.equal(h.requests.length, count);
  h.assertNoErrors();
});

test("a transfer proposition retained across a mode change cannot apply to the live team", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A")');
  h.route(url => url.startsWith("/api/transfers?") ? {
    top_suggestions: [{
      outgoing: [{ id: 1, name: "One", team: "Club" }],
      incoming: [{ id: 4, name: "Four", team: "Club" }], xp_delta: 2,
    }],
  } : defaults(url));
  await h.run("runSuggestTransfers()");
  const apply = h.element("tx-results-container").querySelector(".btn-apply-tx");
  assert.ok(apply);
  await h.element("btn-mode-live").click();
  const count = h.requests.length;
  await apply.click();
  assert.equal(h.requests.length, count);
  h.assertNoErrors();
});

test("the dashboard has no decision engine version selectors but retains solver profiles and LLM choices", () => {
  for (const id of ["tx-engine", "strategic-engine-select", "create-sim-strategy"]) {
    assert.doesNotMatch(html, new RegExp(`\\bid="${id}"`));
    assert.doesNotMatch(source, new RegExp(`getElementById\\("${id}"\\)`));
  }
  for (const select of html.matchAll(/<select\b[^>]*>[\s\S]*?<\/select>/g)) {
    assert.doesNotMatch(select[0], /<option value="v\d[\d.]*"/);
  }
  const options = id => [...html.match(new RegExp(`<select id="${id}"[^>]*>([\\s\\S]*?)</select>`))[1]
    .matchAll(/<option value="([^"]*)"/g)].map(m => m[1]);
  assert.deepEqual(options("tx-risk"), ["neutral", "floor", "ceiling"]);
  assert.deepEqual(options("tx-num"), ["1", "2", "3", "4", "5"]);
  assert.deepEqual(options("strategic-mode-select"), ["initial", "wildcard", "free_hit"]);
  assert.deepEqual(options("adv-provider"), ["auto", "heuristic", "openrouter", "gemini", "openai"]);
  assert.deepEqual(options("adv-model"), [""]);
});

for (const mode of ["live", "historical"]) {
  test(`${mode} transfer handler delegates engine selection to the backend`, async () => {
    const h = await harness();
    h.state.appMode = mode;
    h.hist.sessionId = mode === "historical" ? "A" : null;
    h.hist.gameweek = 5;
    h.element("tx-engine").value = "v1.0";
    h.element("tx-num").value = "3";
    h.element("tx-gws").value = "8";
    h.element("tx-risk").value = "ceiling";
    h.route(url => url.startsWith("/api/transfers?") ? { top_suggestions: [] } : defaults(url));
    await h.element("btn-run-suggest-tx").click();
    const request = h.requests.find(r => r.url.startsWith("/api/transfers?"));
    const params = new URL(request.url, "http://localhost").searchParams;
    assert.equal(params.has("engine"), false);
    assert.equal(params.get("transfers"), "3");
    assert.equal(params.get("gameweeks"), "8");
    assert.equal(params.get("risk"), "ceiling");
    assert.equal(params.get("session_id"), mode === "historical" ? "A" : null);
    h.assertNoErrors();
  });
}

test("new simulation handler omits algorithm versions and preserves creation settings", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.element("create-sim-season").value = "2023-24";
  h.element("create-sim-start-gw").value = "5";
  h.element("create-sim-id").value = "A";
  h.element("create-sim-manager").value = "Test Manager";
  h.element("create-sim-strategy").value = "v0.9";
  h.route(defaults);
  await h.element("btn-confirm-create-sim").click();
  const request = h.requests.find(r => r.url === "/api/historical/simulations/create");
  assert.deepEqual(request.body, {
    session_id: "A", season: "2023-24", start_gw: 5, manager_name: "Test Manager",
  });
  h.assertNoErrors();
});

test("LLM provider changes still populate their model choices", async () => {
  const h = await harness();
  for (const provider of ["openrouter", "gemini", "openai"]) {
    await h.select("adv-provider", provider);
    const expected = h.run(`PROVIDER_MODELS["${provider}"].map(m => m.id)`);
    assert.deepEqual(h.element("adv-model").options.map(o => o.value), ["", ...expected]);
    assert.equal(h.element("adv-model-group").style.display, "inline-flex");
    assert.equal(h.element("adv-api-key").disabled, false);
  }
  await h.select("adv-provider", "heuristic");
  assert.equal(h.element("adv-model-group").style.display, "none");
  assert.equal(h.element("adv-api-key").disabled, true);
  h.assertNoErrors();
});

for (const activeTab of ["live", "advisor"]) {
  test(`historical mode preserves live-only tab hiding when leaving ${activeTab}`, async () => {
    const h = await harness();
    h.route(defaults);
    await h.tabs.find(t => t.dataset.tab === activeTab).click();
    h.requests.length = 0;
    await h.element("btn-mode-historical").click();
    await settle();
    assert.equal(h.tabs.find(t => t.classList.contains("active")).dataset.tab, "overview");
    for (const name of ["live", "advisor"]) {
      assert.equal(h.tabs.find(t => t.dataset.tab === name).style.display, "none");
      assert.equal(h.element(`tab-${name}`).classList.contains("active"), false);
    }
    assert.equal(h.requests.some(r => !r.url.startsWith("/api/historical/") &&
      !r.url.startsWith("/api/decisions?session_id=")), false, JSON.stringify(h.requests));
    h.assertNoErrors();
  });
}

test("historical comparison and recommendation text never invent an engine version", async () => {
  const h = await harness();
  h.state.appMode = "historical";
  h.route(defaults);
  await h.run('loadHistoricalSession("A")');
  h.run(`showHistoricalResolutionModal({
    gameweek: 5, starters_points: [], net_points: 50, gross_points: 50,
    captain_points: 10, engine_net_points: 47,
  })`);
  assert.match(h.element("hist-modal-body").innerHTML, /Baseline: 47 pts/);
  assert.doesNotMatch(h.element("hist-modal-body").innerHTML, /v1\.\d/);
  h.run('showHistoricalRecommendationsModal({gameweek: 5, engine_version: "v0.9"})');
  assert.equal(h.element("hist-modal-title").textContent, "Decision Recommendations (GW 5)");
  assert.doesNotMatch(h.element("hist-modal-body").innerHTML, /v0\.9|v1\.3\.5/);
  h.assertNoErrors();
});
