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
  "not-now-button",
  "active-title",
  "active-meta",
  "active-action",
  "active-action-wrap",
  "result-note",
  "feedback-form",
  "no-work-explanation",
  "no-work-title",
  "skipped-controls",
  "reset-skipped-button",
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
  for (const id of ["error", "progress", "capture-progress", "capture-result", "active-action-wrap", "skipped-controls"]) {
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

async function renderNoWork(result) {
  const page = createPage((path) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate") {
      return Promise.resolve(response({ ok: true, result }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  return page;
}

test("labels deterministic infeasible and HARD-blocked NO_WORK as no feasible work", async () => {
  for (const reason of ["NO_FEASIBLE_TASKS", "ACTIVE_HARD_COMMITMENT"]) {
    const explanation = `Deterministic explanation for ${reason}.`;
    const page = await renderNoWork({ kind: "NO_WORK", explanation, reason });

    assert.equal(page.elements["no-work-title"].textContent, "No feasible work right now.");
    assert.equal(page.elements["no-work-explanation"].textContent, explanation);
  }
});

test("labels exhausted skipped selections as no unskipped work", async () => {
  const explanation = "All currently permissible work was skipped for this search.";
  const page = await renderNoWork({
    kind: "NO_WORK",
    explanation,
    reason: "ALL_PERMISSIBLE_TASKS_EXCLUDED",
  });

  assert.equal(page.elements["no-work-title"].textContent, "No unskipped work in this search.");
  assert.equal(page.elements["no-work-explanation"].textContent, explanation);
});

test("labels provider-selected NO_WORK with a null reason as not recommended", async () => {
  const explanation = "The available choices are feasible, but none is recommended now.";
  const page = await renderNoWork({ kind: "NO_WORK", explanation, reason: null });

  assert.equal(page.elements["no-work-title"].textContent, "No work recommended right now.");
  assert.equal(page.elements["no-work-explanation"].textContent, explanation);
});

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
  assert.equal(page.elements["closed-meta"].textContent, "Task completed.");
});

test("Not now advances High to High to authorized lower work in one request each", async () => {
  const calls = [];
  const mediumAuthorization = {
    task_id: 3,
    duration_minutes: 10,
    timezone_name: "UTC",
    available_minutes: 20,
    feasible_high_task_ids: [1, 2],
  };
  const lowAuthorization = {
    ...mediumAuthorization,
    task_id: 4,
    duration_minutes: 15,
  };
  const page = createPage((path, options) => {
    calls.push({ path, options });
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate") {
      const body = JSON.parse(options.body);
      const excluded = body.excluded_task_ids || [];
      if (excluded.length === 0) {
        return Promise.resolve(response({ ok: true, result: {
          kind: "RECOMMEND", task_id: 1, task_title: "First High task",
          project_name: null, duration_minutes: 5,
          action: "Do first High work.", explanation: "High priority comes first.",
        } }));
      }
      if (excluded.length === 1) {
        return Promise.resolve(response({ ok: true, result: {
          kind: "RECOMMEND", task_id: 2, task_title: "Second High task",
          project_name: null, duration_minutes: 5,
          action: "Do second High work.", explanation: "Another High priority fits.",
        } }));
      }
      if (excluded.length === 2) {
        return Promise.resolve(response({ ok: true, result: {
          kind: "RECOMMEND", task_id: 3, task_title: "Medium task",
          project_name: null, duration_minutes: 10,
          action: "Do medium work.", explanation: "Automatic alternative.",
          lower_priority_authorization: mediumAuthorization,
        } }));
      }
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 4, task_title: "Low task",
        project_name: null, duration_minutes: 15,
        action: "Do low work.", explanation: "Next feasible alternative.",
        lower_priority_authorization: lowAuthorization,
      } }));
    }
    if (path === "/v1/start") {
      return Promise.resolve(response({ ok: true, result: {
        ...activeSession(), task_id: 4, task_title: "Low task",
        planned_minutes: 15, selected_action: "Do low work.",
      } }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  await settle();
  page.elements["time-cap"].value = "20";
  page.trigger("activate-form", "submit");
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "First High task");

  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "Second High task");

  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "Medium task");

  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "Low task");
  assert.equal(page.elements["skipped-controls"].hidden, false);

  page.trigger("start-button", "click");
  await settle();

  const activationBodies = calls
    .filter((call) => call.path === "/v1/activate")
    .map((call) => JSON.parse(call.options.body));
  assert.deepEqual(activationBodies, [
    { time_cap_minutes: 20 },
    { time_cap_minutes: 20, excluded_task_ids: [1] },
    { time_cap_minutes: 20, excluded_task_ids: [1, 2] },
    { time_cap_minutes: 20, excluded_task_ids: [1, 2, 3] },
  ]);
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    task_id: 4,
    planned_minutes: 15,
    selected_action: "Do low work.",
    available_minutes: 20,
    lower_priority_authorization: lowAuthorization,
  });
  assert.equal(page.elements.active.hidden, false);
  assert.equal(page.elements["skipped-controls"].hidden, true);
});

test("reset from automatic lower work restores normal High-priority selection", async () => {
  const activationBodies = [];
  const page = createPage((path, options) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    const body = JSON.parse(options.body);
    activationBodies.push(body);
    if (body.excluded_task_ids) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 2, task_title: "Medium task",
        project_name: null, duration_minutes: 5,
        action: "Do medium work.", explanation: "Automatic alternative.",
        lower_priority_authorization: {
          task_id: 2, duration_minutes: 5, timezone_name: "UTC",
          available_minutes: null, feasible_high_task_ids: [1],
        },
      } }));
    }
    return Promise.resolve(response({ ok: true, result: {
      kind: "RECOMMEND", task_id: 1, task_title: "High task",
      project_name: null, duration_minutes: 5,
      action: "Do high work.", explanation: "High priority comes first.",
    } }));
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "Medium task");
  page.trigger("reset-skipped-button", "click");
  await settle();

  assert.deepEqual(activationBodies, [{}, { excluded_task_ids: [1] }, {}]);
  assert.equal(page.elements.recommendation.hidden, false);
  assert.equal(page.elements["recommendation-title"].textContent, "High task");
  assert.equal(page.elements["skipped-controls"].hidden, true);
});

test("New search clears an automatic lower-priority flow", async () => {
  const activationBodies = [];
  const page = createPage((path, options) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    const body = JSON.parse(options.body);
    activationBodies.push(body);
    if (body.excluded_task_ids) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 2, task_title: "Medium task",
        project_name: null, duration_minutes: 5,
        action: "Do medium work.", explanation: "Automatic alternative.",
        lower_priority_authorization: {
          task_id: 2, duration_minutes: 5, timezone_name: "UTC",
          available_minutes: null, feasible_high_task_ids: [1],
        },
      } }));
    }
    return Promise.resolve(response({ ok: true, result: {
      kind: "RECOMMEND", task_id: 1, task_title: "High task",
      project_name: null, duration_minutes: 5,
      action: "Do high work.", explanation: "High priority comes first.",
    } }));
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "Medium task");
  assert.equal(page.elements["activate-button"].textContent, "New search");
  page.trigger("activate-form", "submit");
  await settle();

  assert.deepEqual(activationBodies.at(-1), {});
  assert.equal(page.elements["recommendation-title"].textContent, "High task");
  assert.equal(page.elements["skipped-controls"].hidden, true);
});

test("Not now accumulates exclusions and successful reset clears skipped work", async () => {
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ options, path });
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path !== "/v1/activate") throw new Error(`Unexpected request: ${path}`);
    const body = JSON.parse(options.body);
    const excluded = body.excluded_task_ids || [];
    if (excluded.length === 0) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 1, task_title: "First", project_name: null,
        duration_minutes: 10, action: "Do first.", explanation: "First fit.",
      } }));
    }
    if (excluded.length === 1) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 2, task_title: "Second", project_name: null,
        duration_minutes: 10, action: "Do second.", explanation: "Second fit.",
      } }));
    }
    return Promise.resolve(response({ ok: true, result: {
      kind: "NO_WORK",
      explanation: "All currently permissible work was skipped for this search.",
      reason: "ALL_PERMISSIBLE_TASKS_EXCLUDED",
    } }));
  });

  await settle();
  page.elements["time-cap"].value = "20";
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();

  const activationBodies = calls
    .filter((call) => call.path === "/v1/activate")
    .map((call) => JSON.parse(call.options.body));
  assert.deepEqual(activationBodies, [
    { time_cap_minutes: 20 },
    { time_cap_minutes: 20, excluded_task_ids: [1] },
    { time_cap_minutes: 20, excluded_task_ids: [1, 2] },
  ]);
  assert.equal(page.elements["no-work"].hidden, false);
  assert.equal(page.elements["skipped-controls"].hidden, false);

  page.trigger("reset-skipped-button", "click");
  await settle();
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), { time_cap_minutes: 20 });
  assert.equal(page.elements.recommendation.hidden, false);
  assert.equal(page.elements["recommendation-title"].textContent, "First");
  assert.equal(page.elements["skipped-controls"].hidden, true);

  page.trigger("not-now-button", "click");
  await settle();
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    time_cap_minutes: 20,
    excluded_task_ids: [1],
  });
});

test("failed reset preserves exhausted NO_WORK state and skipped controls", async () => {
  const activationBodies = [];
  const page = createPage((path, options) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path !== "/v1/activate") throw new Error(`Unexpected request: ${path}`);
    const body = JSON.parse(options.body);
    activationBodies.push(body);
    if (activationBodies.length === 1) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 1, task_title: "Only task", project_name: null,
        duration_minutes: 10, action: "Do the task.", explanation: "It fits.",
      } }));
    }
    if (activationBodies.length === 2) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "NO_WORK",
        explanation: "All currently permissible work was skipped for this search.",
        reason: "ALL_PERMISSIBLE_TASKS_EXCLUDED",
      } }));
    }
    return Promise.resolve(response({
      ok: false, error: { message: "provider unavailable" },
    }, 500));
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  page.trigger("reset-skipped-button", "click");
  await settle();

  assert.deepEqual(activationBodies, [{}, { excluded_task_ids: [1] }, {}]);
  assert.equal(page.elements["no-work"].hidden, false);
  assert.equal(
    page.elements["no-work-explanation"].textContent,
    "All currently permissible work was skipped for this search.",
  );
  assert.equal(page.elements["skipped-controls"].hidden, false);
  assert.equal(page.elements["reset-skipped-button"].disabled, false);
  assert.match(page.elements.error.textContent, /provider unavailable/i);
});

test("failed New search preserves the visible alternative and exclusion context", async () => {
  const activationBodies = [];
  const page = createPage((path, options) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path !== "/v1/activate") throw new Error(`Unexpected request: ${path}`);
    const body = JSON.parse(options.body);
    activationBodies.push(body);
    if (activationBodies.length === 1) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 1, task_title: "First", project_name: null,
        duration_minutes: 10, action: "Do first.", explanation: "First fit.",
      } }));
    }
    if (activationBodies.length === 2) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 2, task_title: "Second", project_name: null,
        duration_minutes: 10, action: "Do second.", explanation: "Second fit.",
      } }));
    }
    if (activationBodies.length === 3) {
      return Promise.resolve(response({
        ok: false, error: { message: "provider unavailable" },
      }, 500));
    }
    return Promise.resolve(response({ ok: true, result: {
      kind: "NO_WORK",
      explanation: "All currently permissible work was skipped for this search.",
      reason: "ALL_PERMISSIBLE_TASKS_EXCLUDED",
    } }));
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  page.trigger("activate-form", "submit");
  await settle();

  assert.deepEqual(activationBodies.slice(0, 3), [{}, { excluded_task_ids: [1] }, {}]);
  assert.equal(page.elements.recommendation.hidden, false);
  assert.equal(page.elements["recommendation-title"].textContent, "Second");
  assert.equal(page.elements["recommendation-explanation"].textContent, "Second fit.");
  assert.equal(page.elements["skipped-controls"].hidden, false);

  page.trigger("not-now-button", "click");
  await settle();
  assert.deepEqual(activationBodies.at(-1), { excluded_task_ids: [1, 2] });
  assert.equal(page.elements["no-work"].hidden, false);
});

test("New search starts a new selection flow", async () => {
  const activationBodies = [];
  const page = createPage((path, options) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate") {
      activationBodies.push(JSON.parse(options.body));
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: activationBodies.length === 2 ? 2 : 1,
        task_title: "Task", project_name: null, duration_minutes: 5,
        action: "Do task.", explanation: "Fits.",
      } }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  page.trigger("activate-form", "submit");
  await settle();

  assert.deepEqual(activationBodies, [{}, { excluded_task_ids: [1] }, {}]);
  assert.equal(page.elements["skipped-controls"].hidden, true);
});

test("failed alternative rolls back the exclusion and keeps Start usable", async () => {
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ path, options });
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate" && calls.filter((call) => call.path === path).length === 1) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 4, task_title: "Finish draft",
        project_name: null, duration_minutes: 15,
        action: "Write the next paragraph.", explanation: "Fits.",
      } }));
    }
    if (path === "/v1/activate") {
      return Promise.resolve(response({
        ok: false, error: { message: "provider unavailable" },
      }, 500));
    }
    if (path === "/v1/start") {
      return Promise.resolve(response({ ok: true, result: activeSession() }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();

  assert.equal(page.elements.recommendation.hidden, false);
  assert.equal(page.elements["recommendation-title"].textContent, "Finish draft");
  assert.equal(page.elements["skipped-controls"].hidden, true);
  assert.match(page.elements.error.textContent, /current recommendation is still available/i);

  page.trigger("start-button", "click");
  await settle();
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    task_id: 4,
    planned_minutes: 15,
    selected_action: "Write the next paragraph.",
  });
  assert.equal(page.elements.active.hidden, false);
});

test("starting an alternative clears skipped work and preserves its exact choice", async () => {
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ path, options });
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate") {
      const excluded = JSON.parse(options.body).excluded_task_ids || [];
      return Promise.resolve(response({ ok: true, result: excluded.length === 0 ? {
        kind: "RECOMMEND", task_id: 1, task_title: "First", project_name: null,
        duration_minutes: 5, action: "Do first.", explanation: "Fits.",
      } : {
        kind: "RECOMMEND", task_id: 2, task_title: "Second", project_name: null,
        duration_minutes: 15, action: "Do second exactly.", explanation: "Alternative.",
      } }));
    }
    if (path === "/v1/start") {
      return Promise.resolve(response({ ok: true, result: {
        ...activeSession(), task_id: 2, task_title: "Second",
        planned_minutes: 15, selected_action: "Do second exactly.",
      } }));
    }
    throw new Error(`Unexpected request: ${path}`);
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(page.elements["skipped-controls"].hidden, false);
  page.trigger("start-button", "click");
  await settle();

  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    task_id: 2,
    planned_minutes: 15,
    selected_action: "Do second exactly.",
  });
  assert.equal(page.elements.active.hidden, false);
  assert.equal(page.elements["skipped-controls"].hidden, true);
});

test("double Not now during a delayed response sends only one alternative request", async () => {
  const alternative = deferred();
  const calls = [];
  const page = createPage((path, options) => {
    calls.push({ path, options });
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    if (path === "/v1/activate" && calls.filter((call) => call.path === path).length === 1) {
      return Promise.resolve(response({ ok: true, result: {
        kind: "RECOMMEND", task_id: 1, task_title: "First", project_name: null,
        duration_minutes: 5, action: "Do first.", explanation: "Fits.",
      } }));
    }
    if (path === "/v1/activate") return alternative.promise;
    throw new Error(`Unexpected request: ${path}`);
  });

  await settle();
  page.trigger("activate-form", "submit");
  await settle();
  page.trigger("not-now-button", "click");
  page.trigger("not-now-button", "click");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/activate").length, 2);

  alternative.resolve(response({ ok: true, result: {
    kind: "RECOMMEND", task_id: 2, task_title: "Second", project_name: null,
    duration_minutes: 5, action: "Do second.", explanation: "Fits.",
  } }));
  await settle();
  assert.equal(page.elements["recommendation-title"].textContent, "Second");
});

test("a fresh page starts with no exclusions", async () => {
  const activationBodies = [];
  const fetch = (path, options) => {
    if (path === "/v1/overview") return Promise.resolve(response(overview(null)));
    activationBodies.push(JSON.parse(options.body));
    return Promise.resolve(response({ ok: true, result: {
      kind: "RECOMMEND", task_id: 1, task_title: "First", project_name: null,
      duration_minutes: 5, action: "Do first.", explanation: "Fits.",
    } }));
  };

  const firstPage = createPage(fetch);
  await settle();
  firstPage.trigger("activate-form", "submit");
  await settle();
  firstPage.trigger("not-now-button", "click");
  await settle();

  const refreshedPage = createPage(fetch);
  await settle();
  refreshedPage.trigger("activate-form", "submit");
  await settle();

  assert.deepEqual(activationBodies.at(-1), {});
  assert.equal(refreshedPage.elements["skipped-controls"].hidden, true);
});
