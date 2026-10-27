"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync(
  join(__dirname, "..", "src", "personal_os", "static", "state.js"),
  "utf8",
);

const elementIds = [
  "refresh-button",
  "state-error",
  "state-progress",
  "overview",
  "needs-input",
  "active-session",
  "commitments",
  "tasks",
  "projects",
  "history",
];

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parent = null;
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.textContent = "";
    this.value = "";
    this.className = "";
    this.name = "";
    this.type = "";
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  append(...nodes) {
    for (const node of nodes) {
      node.parent = this;
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }

  after() {}

  dispatch(type) {
    return this.listeners.get(type)?.({ preventDefault() {} });
  }
}

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function errorResponse(message, status, code) {
  return response({
    ok: false,
    error: { code, message },
  }, status);
}

function task(overrides = {}) {
  return {
    id: 7,
    title: "Drfat essay",
    status: "OPEN",
    importance: "SHOULD",
    project_id: 1,
    project_name: "College",
    schedule: {
      mode: "FLEXIBLE",
      day_date: null,
      window_start: null,
      window_end: null,
    },
    deadline: null,
    execution_mode: "SPLITTABLE",
    estimated_minutes: 30,
    updated_at: "2026-10-26T12:00:00.000000Z",
    ...overrides,
  };
}

function overview(taskValue, projects = [{ id: 1, name: "College", description: null, deadline: null }]) {
  return {
    ok: true,
    result: {
      projects,
      tasks: [taskValue],
      task_history: [],
      commitments: [],
      commitment_history: [],
      inbox: [],
      active_session: null,
      history_limit: 20,
    },
  };
}

function descendants(root) {
  return [root, ...root.children.flatMap(descendants)];
}

function find(root, predicate) {
  const match = descendants(root).find(predicate);
  assert.ok(match, "expected matching element");
  return match;
}

function field(root, name) {
  return find(root, (node) => node.name === name);
}

function button(root, text) {
  return find(
    root,
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

function containingForm(node) {
  let current = node;
  while (current && current.tagName !== "FORM") current = current.parent;
  assert.ok(current, "expected containing form");
  return current;
}

function createPage(fetch) {
  const elements = Object.fromEntries(
    elementIds.map((id) => [id, new FakeElement("div")]),
  );
  elements["refresh-button"] = new FakeElement("button");
  const document = {
    createElement: (tagName) => new FakeElement(tagName),
    getElementById: (id) => elements[id],
  };
  vm.runInNewContext(source, {
    Date,
    Error,
    JSON,
    Number,
    Object,
    Promise,
    Set,
    document,
    fetch,
  });
  return elements;
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  await Promise.resolve();
}

test("saves only changed facts and refreshes authoritative overview", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = { ...shown, title: body.title };
      return response({ ok: true, result: { task_id: shown.id } });
    }
    return response(overview(shown));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const save = button(elements.tasks, "Save changes");
  const form = containingForm(title);
  assert.equal(save.disabled, true);

  title.value = "Draft essay";
  title.dispatch("input");
  assert.equal(save.disabled, false);
  await form.dispatch("submit");
  await settle();

  assert.deepEqual(calls.map((call) => call.path), [
    "/v1/overview",
    "/v1/task-facts",
    "/v1/overview",
  ]);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    task_id: 7,
    title: "Draft essay",
  });
  assert.equal(
    find(elements.tasks, (node) => node.tagName === "H3").textContent,
    "Draft essay",
  );
});

test("cancel restores authoritative values without a mutation", async () => {
  const calls = [];
  const elements = createPage(async (path) => {
    calls.push(path);
    return response(overview(task()));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const importance = field(elements.tasks, "importance");
  const project = field(elements.tasks, "project_id");
  const cancel = button(elements.tasks, "Cancel");
  const save = button(elements.tasks, "Save changes");
  const details = find(
    elements.tasks,
    (node) => node.tagName === "DETAILS" && node.className.includes("task-facts-editor"),
  );
  details.open = true;
  title.value = "Changed";
  importance.value = "MUST";
  project.value = "";
  title.dispatch("input");
  assert.equal(save.disabled, false);

  cancel.dispatch("click");

  assert.equal(title.value, "Drfat essay");
  assert.equal(importance.value, "SHOULD");
  assert.equal(project.value, "1");
  assert.equal(save.disabled, true);
  assert.equal(details.open, false);
  assert.deepEqual(calls, ["/v1/overview"]);
});

test("suppresses a duplicate save while the correction is in flight", async () => {
  const calls = [];
  let releaseCorrection;
  const correction = new Promise((resolve) => {
    releaseCorrection = resolve;
  });
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") return correction;
    return response(overview(task()));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const form = containingForm(title);
  title.value = "Draft essay";
  title.dispatch("input");

  form.dispatch("submit");
  form.dispatch("submit");
  await settle();
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );

  releaseCorrection(response({ ok: true, result: { task_id: 7 } }));
  await settle();
});

test("HTTP 400 validation rejection preserves edits and permits resubmission", async () => {
  const calls = [];
  const inactiveTask = task({ project_id: 9, project_name: "Old project" });
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      return errorResponse(
        "title must be a non-empty string",
        400,
        "INVALID_REQUEST",
      );
    }
    return response(overview(inactiveTask));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const project = field(elements.tasks, "project_id");
  const form = containingForm(title);
  const inactiveOption = find(
    project,
    (node) => node.tagName === "OPTION" && node.textContent.includes("inactive, current"),
  );
  assert.equal(project.value, "9");
  assert.equal(inactiveOption.disabled, true);

  title.value = "   ";
  project.value = "1";
  title.dispatch("input");
  await form.dispatch("submit");
  await settle();

  const message = find(
    form,
    (node) => node.className === "form-message",
  );
  assert.equal(message.hidden, false);
  assert.match(message.textContent, /title must be a non-empty string/);
  assert.match(message.textContent, /correction was not saved/);
  assert.equal(title.value, "   ");
  assert.equal(project.value, "1");
  assert.equal(title.disabled, false);
  assert.equal(elements.overview.hidden, false);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    task_id: 7,
    title: "   ",
    project_id: 1,
  });
});

test("HTTP 500 has uncertain outcome and refresh restores authoritative state", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = { ...shown, title: body.title };
      return errorResponse(
        "server failed after handling the request",
        500,
        "INTERNAL_SERVER_ERROR",
      );
    }
    return response(overview(shown));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const form = containingForm(title);
  title.value = "Draft essay";
  title.dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /save result is uncertain/);
  assert.match(elements["state-error"].textContent, /may have been saved/);
  assert.doesNotMatch(elements["state-error"].textContent, /was not saved/);
  assert.equal(title.disabled, true);

  await form.dispatch("submit");
  await settle();
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );

  await elements["refresh-button"].dispatch("click");
  await settle();

  assert.equal(elements.overview.hidden, false);
  assert.equal(elements["state-error"].hidden, true);
  assert.equal(
    find(elements.tasks, (node) => node.tagName === "H3").textContent,
    "Draft essay",
  );
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );
});

test("lost POST response is uncertain even after the correction may commit", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = { ...shown, title: body.title };
      throw new Error("connection lost before the response arrived");
    }
    return response(overview(shown));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const form = containingForm(title);
  title.value = "Draft essay";
  title.dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /save result is uncertain/);
  assert.match(elements["state-error"].textContent, /connection lost/);
  assert.doesNotMatch(elements["state-error"].textContent, /was not saved/);
  assert.equal(title.disabled, true);
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );
});

test("malformed successful POST response has uncertain outcome", async () => {
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      return {
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError("invalid JSON response");
        },
      };
    }
    return response(overview(task()));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const form = containingForm(title);
  title.value = "Draft essay";
  title.dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /save result is uncertain/);
  assert.match(elements["state-error"].textContent, /invalid JSON response/);
  assert.doesNotMatch(elements["state-error"].textContent, /was not saved/);
  assert.equal(title.disabled, true);
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );
});

test("saved correction locks stale state until a later refresh succeeds", async () => {
  const calls = [];
  let shown = task();
  let failNextOverview = false;
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = { ...shown, title: body.title };
      failNextOverview = true;
      return response({ ok: true, result: { task_id: shown.id } });
    }
    if (failNextOverview) {
      failNextOverview = false;
      return response({
        ok: false,
        error: { message: "overview unavailable" },
      }, 500);
    }
    return response(overview(shown));
  });
  await settle();

  const title = field(elements.tasks, "title");
  const form = containingForm(title);
  title.value = "Draft essay";
  title.dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(elements.overview.hidden, true);
  assert.equal(elements["state-error"].hidden, false);
  assert.match(elements["state-error"].textContent, /correction was saved/);
  assert.match(elements["state-error"].textContent, /could not refresh/);
  assert.equal(title.disabled, true);
  assert.equal(elements["refresh-button"].disabled, false);

  await form.dispatch("submit");
  await settle();
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );

  await elements["refresh-button"].dispatch("click");
  await settle();

  assert.equal(elements.overview.hidden, false);
  assert.equal(elements["state-error"].hidden, true);
  assert.equal(
    find(elements.tasks, (node) => node.tagName === "H3").textContent,
    "Draft essay",
  );
  assert.equal(
    calls.filter((call) => call.path === "/v1/task-facts").length,
    1,
  );
});
