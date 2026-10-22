"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync(
  join(__dirname, "..", "src", "personal_os", "static", "work.js"),
  "utf8",
);
const screenIds = ["idle", "recommendation", "active", "no-work", "closed"];
const elementIds = [
  ...screenIds,
  "error",
  "progress",
  "capture-progress",
  "capture-button",
  "capture-result",
  "capture-text",
  "activate-form",
  "activate-button",
  "time-cap",
  "recommendation-title",
  "recommendation-meta",
  "recommendation-action",
  "recommendation-explanation",
  "start-button",
  "active-title",
  "active-meta",
  "active-action",
  "active-action-wrap",
  "result-note",
  "feedback-form",
  "no-work-explanation",
  "closed-title",
  "closed-meta",
  "next-button",
  "capture-form",
];

class FakeElement {
  constructor() {
    this.hidden = false;
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.listeners = new Map();
    this.classList = { add() {} };
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  append() {}

  after() {}

  replaceChildren() {}
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function activeSession() {
  return {
    session_id: 17,
    task_id: 4,
    task_title: "Finish draft",
    planned_minutes: 15,
    selected_action: "Write the next paragraph.",
    started_at: "2026-10-21T14:15:00.000000Z",
  };
}

function overview(session) {
  return { ok: true, result: { active_session: session } };
}

function createPage(fetch) {
  const elements = Object.fromEntries(elementIds.map((id) => [id, new FakeElement()]));
  for (const id of screenIds) elements[id].hidden = true;
  for (const id of ["error", "progress", "capture-progress", "capture-result", "active-action-wrap"]) {
    elements[id].hidden = true;
  }
  const document = {
    createElement: () => new FakeElement(),
    getElementById: (id) => elements[id],
    querySelectorAll: () => [],
  };
  vm.runInNewContext(source, {
    Array,
    Date,
    Error,
    JSON,
    Number,
    Object,
    Promise,
    document,
    fetch,
  });
  return {
    elements,
    trigger(id, type, event = {}) {
      elements[id].listeners.get(type)({ preventDefault() {}, ...event });
    },
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  await Promise.resolve();
}

test("restores an active session with its existing feedback controls", async () => {
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ options, path });
    return Promise.resolve(response(overview(activeSession())));
  });

  assert.equal(page.elements.idle.hidden, true);
  assert.equal(page.elements.progress.hidden, false);
  await settle();

  assert.deepEqual(calls.map((call) => call.path), ["/v1/overview"]);
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.method, undefined);
  assert.equal(page.elements.active.hidden, false);
  assert.equal(page.elements.idle.hidden, true);
  assert.equal(page.elements["active-title"].textContent, "Finish draft");
  assert.equal(
    page.elements["active-meta"].textContent,
    `15 min planned · Started ${new Date(activeSession().started_at).toLocaleString()}`,
  );
  assert.equal(page.elements["active-action"].textContent, "Write the next paragraph.");
  assert.equal(page.elements["active-action-wrap"].hidden, false);
  assert.equal(page.elements["feedback-form"].listeners.has("submit"), true);
});

test("shows idle only after overview explicitly reports no active session", async () => {
  const page = createPage(() => Promise.resolve(response(overview(null))));

  assert.equal(page.elements.idle.hidden, true);
  await settle();

  assert.equal(page.elements.idle.hidden, false);
  assert.equal(page.elements.active.hidden, true);
  assert.equal(page.elements.error.hidden, true);
});

test("rejects missing and malformed active-session overview payloads", async () => {
  const malformedPayloads = [
    { name: "missing", result: {} },
    {
      name: "malformed",
      result: {
        active_session: { ...activeSession(), planned_minutes: 0 },
      },
    },
  ];

  for (const payload of malformedPayloads) {
    const page = createPage(() => Promise.resolve(response({ ok: true, result: payload.result })));
    await settle();

    assert.equal(page.elements.idle.hidden, true, payload.name);
    assert.equal(page.elements.error.hidden, false, payload.name);
    assert.match(page.elements.error.textContent, /Could not restore the active work session/);
    assert.match(page.elements.error.textContent, /Invalid/);
  }
});

test("shows a restore error when the overview server fails", async () => {
  const page = createPage(() => Promise.resolve(response({
    ok: false,
    error: { message: "overview unavailable" },
  }, 500)));
  await settle();

  assert.equal(page.elements.idle.hidden, true);
  assert.equal(page.elements.error.hidden, false);
  assert.match(page.elements.error.textContent, /overview unavailable/);
});

test("shows a restore error when the initial overview request is unavailable", async () => {
  const page = createPage(() => Promise.reject(new TypeError("Failed to fetch")));
  await settle();

  assert.equal(page.elements.idle.hidden, true);
  assert.equal(page.elements.error.hidden, false);
  assert.match(page.elements.error.textContent, /Could not restore the active work session/);
  assert.match(page.elements.error.textContent, /Failed to fetch/);
  assert.equal(page.elements.progress.hidden, true);
});

test("ignores a late successful startup response after Find Work", async () => {
  const startup = deferred();
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ options, path });
    if (path === "/v1/overview") return startup.promise;
    if (path === "/v1/activate") {
      return Promise.resolve(response({
        ok: true,
        result: {
          kind: "RECOMMEND",
          task_id: 4,
          task_title: "Finish draft",
          project_name: null,
          duration_minutes: 15,
          action: "Write the next paragraph.",
          explanation: "This fits now.",
        },
      }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  page.trigger("activate-form", "submit");
  await settle();
  startup.resolve(response(overview(activeSession())));
  await settle();

  assert.deepEqual(calls.map((call) => call.path), ["/v1/overview", "/v1/activate"]);
  assert.equal(page.elements.recommendation.hidden, false);
  assert.equal(page.elements.active.hidden, true);
  assert.equal(page.elements.error.hidden, true);
});

test("ignores a late failed startup response after Find Work", async () => {
  const startup = deferred();
  const page = createPage((path) => {
    if (path === "/v1/overview") return startup.promise;
    if (path === "/v1/activate") {
      return Promise.resolve(response({
        ok: true,
        result: {
          kind: "NO_WORK",
          explanation: "Nothing needs attention right now.",
        },
      }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  page.trigger("activate-form", "submit");
  await settle();
  startup.reject(new Error("stale overview failure"));
  await settle();

  assert.equal(page.elements["no-work"].hidden, false);
  assert.equal(page.elements.error.hidden, true);
});

test("retains Find Work, Start, and feedback requests", async () => {
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ options, path });
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate") {
      return Promise.resolve(response({
        ok: true,
        result: {
          kind: "RECOMMEND",
          task_id: 4,
          task_title: "Finish draft",
          project_name: null,
          duration_minutes: 15,
          action: "Write the next paragraph.",
          explanation: "This fits now.",
        },
      }));
    }
    if (path === "/v1/start") {
      return Promise.resolve(response({
        ok: true,
        result: activeSession(),
      }));
    }
    if (path === "/v1/feedback") {
      return Promise.resolve(response({
        ok: true,
        result: {
          task_title: "Finish draft",
          outcome: "FINISHED",
          task_status: "COMPLETED",
        },
      }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("start-button", "click");
  await settle();
  page.elements["result-note"].value = "Completed the draft.";
  page.trigger("feedback-form", "submit", { submitter: { value: "FINISHED" } });
  await settle();

  assert.deepEqual(calls.map((call) => call.path), [
    "/v1/overview",
    "/v1/activate",
    "/v1/start",
    "/v1/feedback",
  ]);
  assert.equal(calls[1].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[2].options.body), {
    task_id: 4,
    planned_minutes: 15,
    selected_action: "Write the next paragraph.",
  });
  assert.deepEqual(JSON.parse(calls[3].options.body), {
    outcome: "FINISHED",
    result_note: "Completed the draft.",
  });
  assert.equal(page.elements.closed.hidden, false);
  assert.equal(page.elements["closed-title"].textContent, "Finish draft: finished");
});
