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
  "refresh-button", "state-error", "state-progress", "overview", "needs-input",
  "active-session", "commitments", "tasks", "projects", "history",
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
    this.checked = false;
    this.required = false;
    this.textContent = "";
    this.value = "";
    this.className = "";
    this.name = "";
    this.type = "";
    this.id = "";
    this.htmlFor = "";
  }

  addEventListener(type, listener) { this.listeners.set(type, listener); }

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

  dispatch(type) { return this.listeners.get(type)?.({ preventDefault() {} }); }
}

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function errorResponse(message, status, code) {
  return response({ ok: false, error: { code, message } }, status);
}

function task(overrides = {}) {
  return {
    id: 7,
    title: "Drfat essay",
    status: "OPEN",
    importance: "SHOULD",
    project_id: 1,
    project_name: "College",
    schedule: { mode: "FLEXIBLE", day_date: null, window_start: null, window_end: null },
    deadline: null,
    execution_mode: "SPLITTABLE",
    estimated_minutes: 30,
    updated_at: "2026-10-26T12:00:00.000000Z",
    ...overrides,
  };
}

function project(id, name) {
  return { id, name, description: null, deadline: null };
}

function overview(taskValues, projects = [project(1, "College")], activeSession = null) {
  return {
    ok: true,
    result: {
      projects,
      tasks: Array.isArray(taskValues) ? taskValues : [taskValues],
      task_history: [],
      commitments: [],
      commitment_history: [],
      inbox: [],
      active_session: activeSession,
      history_limit: 20,
    },
  };
}

function descendants(root) { return [root, ...root.children.flatMap(descendants)]; }
function all(root, predicate) { return descendants(root).filter(predicate); }

function find(root, predicate) {
  const match = descendants(root).find(predicate);
  assert.ok(match, "expected matching element");
  return match;
}

function field(root, name) { return find(root, (node) => node.name === name); }

function button(root, text) {
  return find(root, (node) => node.tagName === "BUTTON" && node.textContent === text);
}

function formFor(root, taskId, section) {
  return find(root, (node) => (
    node.tagName === "FORM"
    && node.dataset.taskId === String(taskId)
    && node.dataset.section === section
  ));
}

function editorFor(form) {
  let current = form;
  while (current && current.tagName !== "DETAILS") current = current.parent;
  assert.ok(current, "expected containing details");
  return current;
}

function priorityRadios(form) { return all(form, (node) => node.type === "radio"); }

function choosePriority(form, value) {
  const radios = priorityRadios(form);
  for (const radio of radios) radio.checked = radio.value === value;
  return radios.find((radio) => radio.value === value).dispatch("change");
}

function createPage(fetch) {
  const elements = Object.fromEntries(elementIds.map((id) => [id, new FakeElement("div")]));
  elements["refresh-button"] = new FakeElement("button");
  const document = {
    createElement: (tagName) => new FakeElement(tagName),
    getElementById: (id) => elements[id],
  };
  vm.runInNewContext(source, {
    Date, Error, JSON, Map, Number, Object, Promise, Set, document, fetch,
  });
  return elements;
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  await Promise.resolve();
}

test("renders one accessible Edit details disclosure with separate forms", async () => {
  const elements = createPage(async () => response(overview(task({ status: "BLOCKED" }))));
  await settle();

  const details = all(
    elements.tasks,
    (node) => node.tagName === "DETAILS" && node.className.includes("task-details-editor"),
  );
  assert.equal(details.length, 1);
  assert.equal(find(details[0], (node) => node.tagName === "SUMMARY").textContent, "Edit details");
  assert.deepEqual(
    all(details[0], (node) => node.tagName === "H4").map((node) => node.textContent),
    ["Task details", "Work requirements"],
  );

  const factsForm = formFor(elements.tasks, 7, "facts");
  const planningForm = formFor(elements.tasks, 7, "planning");
  assert.equal(field(factsForm, "title").value, "Drfat essay");
  assert.equal(field(factsForm, "project_id").value, "1");
  assert.equal(field(planningForm, "estimated_minutes").value, "30");
  assert.equal(field(planningForm, "can_split").checked, true);
  assert.equal(button(factsForm, "Save task details").disabled, true);
  assert.equal(button(planningForm, "Save work requirements").disabled, true);
  assert.match(find(details[0], (node) => node.className === "editor-help").textContent, /save separately/);

  const taskItem = details[0].parent;
  for (const label of ["Done", "Remove", "Unblock"]) {
    const action = button(taskItem, label);
    assert.equal(descendants(details[0]).includes(action), false);
  }
  assert.doesNotMatch(source, /Edit task|Save planning|Not specified|Must do|Should do|Could do/);
  assert.doesNotMatch(source, /Save all/);
});

test("maps all Priority labels to unchanged enum values with unique radio groups", async () => {
  const tasks = [
    task({ id: 7, importance: "MUST" }),
    task({ id: 8, title: "Medium", importance: "SHOULD" }),
    task({ id: 9, title: "Low", importance: "COULD" }),
    task({ id: 10, title: "Unset", importance: "UNSPECIFIED" }),
  ];
  const elements = createPage(async () => response(overview(tasks)));
  await settle();

  const expected = [
    [7, "MUST", "Priority: High"],
    [8, "SHOULD", "Priority: Medium"],
    [9, "COULD", "Priority: Low"],
    [10, "UNSPECIFIED", null],
  ];
  const groupNames = new Set();
  for (const [id, value, metadata] of expected) {
    const form = formFor(elements.tasks, id, "facts");
    const radios = priorityRadios(form);
    assert.equal(radios.length, 4);
    assert.deepEqual(radios.map((radio) => radio.value), ["MUST", "SHOULD", "COULD", "UNSPECIFIED"]);
    assert.equal(radios.filter((radio) => radio.checked).length, 1);
    assert.equal(radios.find((radio) => radio.checked).value, value);
    assert.equal(new Set(radios.map((radio) => radio.name)).size, 1);
    assert.equal(radios.every((radio) => radio.id && radio.parent.htmlFor === radio.id), true);
    assert.equal(radios.every((radio) => radio.disabled === false), true);
    groupNames.add(radios[0].name);
    const item = editorFor(form).parent;
    const meta = find(item, (node) => node.className === "meta" && node.parent === item);
    if (metadata) assert.match(meta.textContent, new RegExp(metadata));
    else assert.doesNotMatch(meta.textContent, /Priority:/);
  }
  assert.equal(groupNames.size, 4);
  assert.deepEqual(
    all(formFor(elements.tasks, 7, "facts"), (node) => (
      node.tagName === "SPAN" && ["High", "Medium", "Low", "Not set"].includes(node.textContent)
    )).map((node) => node.textContent),
    ["High", "Medium", "Low", "Not set"],
  );
  assert.equal(find(formFor(elements.tasks, 7, "facts"), (node) => node.tagName === "LEGEND").textContent, "Priority");
});

test("saves only changed Task details and refreshes authoritative overview", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = { ...shown, title: body.title, importance: body.importance, project_id: body.project_id, project_name: null };
      return response({ ok: true, result: { task_id: shown.id } });
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "facts");
  const title = field(form, "title");
  title.value = "Draft essay";
  title.dispatch("input");
  choosePriority(form, "MUST");
  const projectSelect = field(form, "project_id");
  projectSelect.value = "";
  projectSelect.dispatch("change");
  assert.equal(button(form, "Save task details").disabled, false);
  await form.dispatch("submit");
  await settle();

  assert.deepEqual(calls.map((call) => call.path), ["/v1/overview", "/v1/task-facts", "/v1/overview"]);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    task_id: 7, title: "Draft essay", importance: "MUST", project_id: null,
  });
  assert.equal(find(elements.tasks, (node) => node.tagName === "H3").textContent, "Draft essay");
  assert.match(find(elements.tasks, (node) => node.className === "meta").textContent, /Priority: High/);
});

test("no-op section submissions perform no mutation", async () => {
  const calls = [];
  const elements = createPage(async (path) => {
    calls.push(path);
    return response(overview(task()));
  });
  await settle();

  await formFor(elements.tasks, 7, "facts").dispatch("submit");
  await formFor(elements.tasks, 7, "planning").dispatch("submit");
  await settle();
  assert.deepEqual(calls, ["/v1/overview"]);
});

test("section-local Cancel restores only that section without mutation", async () => {
  const calls = [];
  const elements = createPage(async (path) => {
    calls.push(path);
    return response(overview(task()));
  });
  await settle();

  const factsForm = formFor(elements.tasks, 7, "facts");
  const planningForm = formFor(elements.tasks, 7, "planning");
  const details = editorFor(factsForm);
  details.open = true;
  field(factsForm, "title").value = "Changed";
  field(factsForm, "title").dispatch("input");
  choosePriority(factsForm, "MUST");
  field(planningForm, "estimated_minutes").value = "75";
  field(planningForm, "estimated_minutes").dispatch("input");

  button(factsForm, "Cancel").dispatch("click");
  assert.equal(field(factsForm, "title").value, "Drfat essay");
  assert.equal(priorityRadios(factsForm).find((radio) => radio.checked).value, "SHOULD");
  assert.equal(button(factsForm, "Save task details").disabled, true);
  assert.equal(field(planningForm, "estimated_minutes").value, "75");
  assert.equal(button(planningForm, "Save work requirements").disabled, false);
  assert.equal(details.open, true);

  button(planningForm, "Cancel").dispatch("click");
  assert.equal(field(planningForm, "estimated_minutes").value, "30");
  assert.equal(button(planningForm, "Save work requirements").disabled, true);
  assert.deepEqual(calls, ["/v1/overview"]);
});

test("inactive current Project remains visible but cannot be newly selected", async () => {
  const inactiveTask = task({ project_id: 9, project_name: "Old project" });
  const elements = createPage(async () => response(overview(inactiveTask)));
  await settle();

  const projectSelect = field(formFor(elements.tasks, 7, "facts"), "project_id");
  const inactiveOption = find(projectSelect, (node) => (
    node.tagName === "OPTION" && node.textContent.includes("inactive, current")
  ));
  assert.equal(projectSelect.value, "9");
  assert.equal(inactiveOption.disabled, true);
  assert.match(inactiveOption.textContent, /Old project/);
});

test("HTTP 400 Task-details rejection preserves edits and permits resubmission", async () => {
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      return errorResponse("title must be a non-empty string", 400, "INVALID_REQUEST");
    }
    return response(overview(task()));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "facts");
  const title = field(form, "title");
  title.value = "   ";
  title.dispatch("input");
  await form.dispatch("submit");
  await settle();

  const message = find(form, (node) => node.className === "form-message");
  assert.equal(message.hidden, false);
  assert.match(message.textContent, /title must be a non-empty string/);
  assert.match(message.textContent, /Task details were not saved/);
  assert.equal(title.value, "   ");
  assert.equal(title.disabled, false);
  assert.equal(elements.overview.hidden, false);

  await form.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 2);
});

test("HTTP 500 Task-details outcome locks stale state and Refresh recovers without repost", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = { ...shown, title: body.title };
      return errorResponse("server failed after handling the request", 500, "INTERNAL_SERVER_ERROR");
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "facts");
  field(form, "title").value = "Draft essay";
  field(form, "title").dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /save result is uncertain/);
  assert.match(elements["state-error"].textContent, /may have been saved/);
  assert.doesNotMatch(elements["state-error"].textContent, /were not saved/);
  assert.equal(field(form, "title").disabled, true);
  await form.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);

  await elements["refresh-button"].dispatch("click");
  await settle();
  assert.equal(elements.overview.hidden, false);
  assert.equal(find(elements.tasks, (node) => node.tagName === "H3").textContent, "Draft essay");
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
});

test("lost Task-details POST response is uncertain after a possible commit", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      shown = { ...shown, title: JSON.parse(options.body).title };
      throw new Error("connection lost before the response arrived");
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "facts");
  field(form, "title").value = "Draft essay";
  field(form, "title").dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /save result is uncertain/);
  assert.match(elements["state-error"].textContent, /connection lost/);
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
});

test("malformed successful Task-details response has uncertain outcome", async () => {
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      return {
        ok: true,
        status: 200,
        json: async () => { throw new SyntaxError("invalid JSON response"); },
      };
    }
    return response(overview(task()));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "facts");
  field(form, "title").value = "Draft essay";
  field(form, "title").dispatch("input");
  await form.dispatch("submit");
  await settle();
  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /invalid JSON response/);
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
});

test("saved Task details lock stale state until a later Refresh succeeds", async () => {
  const calls = [];
  let shown = task();
  let failNextOverview = false;
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") {
      shown = { ...shown, title: JSON.parse(options.body).title };
      failNextOverview = true;
      return response({ ok: true, result: { task_id: shown.id } });
    }
    if (failNextOverview) {
      failNextOverview = false;
      return errorResponse("overview unavailable", 500, "INTERNAL_SERVER_ERROR");
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "facts");
  field(form, "title").value = "Draft essay";
  field(form, "title").dispatch("input");
  await form.dispatch("submit");
  await settle();
  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /Task details were saved/);
  assert.match(elements["state-error"].textContent, /could not refresh/);
  assert.equal(elements["refresh-button"].disabled, false);

  await form.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
  await elements["refresh-button"].dispatch("click");
  await settle();
  assert.equal(elements.overview.hidden, false);
  assert.equal(find(elements.tasks, (node) => node.tagName === "H3").textContent, "Draft essay");
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
});

test("Work requirements checkbox maps to canonical planning values", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-planning") {
      const body = JSON.parse(options.body);
      shown = { ...shown, execution_mode: body.execution_mode, estimated_minutes: body.estimated_minutes };
      return response({ ok: true, result: body });
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "planning");
  const canSplit = field(form, "can_split");
  const minutes = field(form, "estimated_minutes");
  canSplit.checked = false;
  canSplit.dispatch("change");
  minutes.value = "90";
  minutes.dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.deepEqual(JSON.parse(calls[1].options.body), {
    task_id: 7, execution_mode: "ONE_SITTING", estimated_minutes: 90,
  });
  assert.equal(calls[1].path, "/v1/task-planning");
  const refreshed = formFor(elements.tasks, 7, "planning");
  assert.equal(field(refreshed, "can_split").checked, false);
  assert.equal(field(refreshed, "estimated_minutes").value, "90");

  field(refreshed, "can_split").checked = true;
  field(refreshed, "can_split").dispatch("change");
  await refreshed.dispatch("submit");
  await settle();
  assert.equal(JSON.parse(calls[3].options.body).execution_mode, "SPLITTABLE");
});

test("saving Task details preserves unsaved Work requirements", async () => {
  let shown = task();
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push(path);
    if (path === "/v1/task-facts") {
      shown = { ...shown, title: JSON.parse(options.body).title };
      return response({ ok: true, result: { task_id: 7 } });
    }
    return response(overview(shown));
  });
  await settle();

  const factsForm = formFor(elements.tasks, 7, "facts");
  const planningForm = formFor(elements.tasks, 7, "planning");
  field(factsForm, "title").value = "Draft essay";
  field(factsForm, "title").dispatch("input");
  field(planningForm, "estimated_minutes").value = "75";
  field(planningForm, "estimated_minutes").dispatch("input");
  await factsForm.dispatch("submit");
  await settle();

  const restoredPlanning = formFor(elements.tasks, 7, "planning");
  assert.equal(field(restoredPlanning, "estimated_minutes").value, "75");
  assert.equal(button(restoredPlanning, "Save work requirements").disabled, false);
  assert.equal(editorFor(restoredPlanning).open, true);
  assert.match(find(restoredPlanning, (node) => node.className === "draft-status").textContent, /restored after refresh/);
  assert.deepEqual(calls, ["/v1/overview", "/v1/task-facts", "/v1/overview"]);
});

test("saving Work requirements preserves unsaved Task details", async () => {
  let shown = task();
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push(path);
    if (path === "/v1/task-planning") {
      const body = JSON.parse(options.body);
      shown = { ...shown, estimated_minutes: body.estimated_minutes };
      return response({ ok: true, result: body });
    }
    return response(overview(shown));
  });
  await settle();

  const factsForm = formFor(elements.tasks, 7, "facts");
  const planningForm = formFor(elements.tasks, 7, "planning");
  field(factsForm, "title").value = "Unsaved title";
  field(factsForm, "title").dispatch("input");
  field(planningForm, "estimated_minutes").value = "45";
  field(planningForm, "estimated_minutes").dispatch("input");
  await planningForm.dispatch("submit");
  await settle();

  const restoredFacts = formFor(elements.tasks, 7, "facts");
  assert.equal(field(restoredFacts, "title").value, "Unsaved title");
  assert.equal(button(restoredFacts, "Save task details").disabled, false);
  assert.equal(editorFor(restoredFacts).open, true);
  assert.match(find(restoredFacts, (node) => node.className === "draft-status").textContent, /restored after refresh/);
  assert.deepEqual(calls, ["/v1/overview", "/v1/task-planning", "/v1/overview"]);
});

test("saving one Task preserves another Task's unsaved draft", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  const elements = createPage(async (path, options = {}) => {
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = shown.map((item) => item.id === body.task_id ? { ...item, title: body.title } : item);
      return response({ ok: true, result: { task_id: body.task_id } });
    }
    return response(overview(shown));
  });
  await settle();

  const first = formFor(elements.tasks, 7, "facts");
  const second = formFor(elements.tasks, 8, "facts");
  field(first, "title").value = "First saved";
  field(first, "title").dispatch("input");
  field(second, "title").value = "Second unsaved";
  field(second, "title").dispatch("input");
  await first.dispatch("submit");
  await settle();

  const restoredSecond = formFor(elements.tasks, 8, "facts");
  assert.equal(field(restoredSecond, "title").value, "Second unsaved");
  assert.equal(button(restoredSecond, "Save task details").disabled, false);
  assert.equal(editorFor(restoredSecond).open, true);
});

test("changed authoritative priority rejects stale Task details but preserves safe planning", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ path, options });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = shown.map((item) => {
        if (item.id === 7) return { ...item, importance: "MUST" };
        if (item.id === body.task_id) return { ...item, title: body.title };
        return item;
      });
      return response({ ok: true, result: { task_id: body.task_id } });
    }
    return response(overview(shown));
  });
  await settle();

  const firstFacts = formFor(elements.tasks, 7, "facts");
  const firstPlanning = formFor(elements.tasks, 7, "planning");
  const secondFacts = formFor(elements.tasks, 8, "facts");
  field(firstFacts, "title").value = "Unsaved first title";
  field(firstFacts, "title").dispatch("input");
  field(firstPlanning, "estimated_minutes").value = "75";
  field(firstPlanning, "estimated_minutes").dispatch("input");
  field(secondFacts, "title").value = "Saved second title";
  field(secondFacts, "title").dispatch("input");
  await secondFacts.dispatch("submit");
  await settle();

  const refreshedFacts = formFor(elements.tasks, 7, "facts");
  const refreshedPlanning = formFor(elements.tasks, 7, "planning");
  assert.equal(field(refreshedFacts, "title").value, "Drfat essay");
  assert.equal(priorityRadios(refreshedFacts).find((radio) => radio.checked).value, "MUST");
  assert.equal(button(refreshedFacts, "Save task details").disabled, true);
  assert.equal(field(refreshedPlanning, "estimated_minutes").value, "75");
  assert.equal(button(refreshedPlanning, "Save work requirements").disabled, false);
  assert.match(
    find(refreshedPlanning, (node) => node.className === "draft-status").textContent,
    /restored after refresh/,
  );
  assert.match(elements["state-error"].textContent, /Task details.*changed elsewhere/);

  await refreshedFacts.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
  assert.equal(JSON.parse(calls.find((call) => call.path === "/v1/task-facts").options.body).task_id, 8);
});

test("changed authoritative Project rejects stale Task-details relationship", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  const projects = [project(1, "College"), project(2, "Work")];
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ path, options });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = shown.map((item) => {
        if (item.id === 7) return { ...item, project_id: 2, project_name: "Work" };
        if (item.id === body.task_id) return { ...item, title: body.title };
        return item;
      });
      return response({ ok: true, result: { task_id: body.task_id } });
    }
    return response(overview(shown, projects));
  });
  await settle();

  const firstFacts = formFor(elements.tasks, 7, "facts");
  const secondFacts = formFor(elements.tasks, 8, "facts");
  field(firstFacts, "title").value = "Unsaved first title";
  field(firstFacts, "title").dispatch("input");
  field(secondFacts, "title").value = "Saved second title";
  field(secondFacts, "title").dispatch("input");
  await secondFacts.dispatch("submit");
  await settle();

  const refreshedFacts = formFor(elements.tasks, 7, "facts");
  assert.equal(field(refreshedFacts, "title").value, "Drfat essay");
  assert.equal(field(refreshedFacts, "project_id").value, "2");
  assert.equal(button(refreshedFacts, "Save task details").disabled, true);
  assert.match(elements["state-error"].textContent, /Task details.*changed elsewhere/);
  await refreshedFacts.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
});

test("changed authoritative planning rejects stale Work requirements", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ path, options });
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = shown.map((item) => {
        if (item.id === 7) {
          return { ...item, execution_mode: "ONE_SITTING", estimated_minutes: 60 };
        }
        if (item.id === body.task_id) return { ...item, title: body.title };
        return item;
      });
      return response({ ok: true, result: { task_id: body.task_id } });
    }
    return response(overview(shown));
  });
  await settle();

  const firstPlanning = formFor(elements.tasks, 7, "planning");
  const secondFacts = formFor(elements.tasks, 8, "facts");
  field(firstPlanning, "estimated_minutes").value = "75";
  field(firstPlanning, "estimated_minutes").dispatch("input");
  field(secondFacts, "title").value = "Saved second title";
  field(secondFacts, "title").dispatch("input");
  await secondFacts.dispatch("submit");
  await settle();

  const refreshedPlanning = formFor(elements.tasks, 7, "planning");
  assert.equal(field(refreshedPlanning, "estimated_minutes").value, "60");
  assert.equal(field(refreshedPlanning, "can_split").checked, false);
  assert.equal(button(refreshedPlanning, "Save work requirements").disabled, true);
  assert.match(elements["state-error"].textContent, /Work requirements.*changed elsewhere/);
  await refreshedPlanning.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-planning").length, 0);
});

test("unchanged original baseline survives subsequent draft edits", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  const elements = createPage(async (path, options = {}) => {
    if (path === "/v1/task-facts") {
      const body = JSON.parse(options.body);
      shown = shown.map((item) => item.id === body.task_id ? { ...item, title: body.title } : item);
      return response({ ok: true, result: { task_id: body.task_id } });
    }
    return response(overview(shown));
  });
  await settle();

  const firstFacts = formFor(elements.tasks, 7, "facts");
  const secondFacts = formFor(elements.tasks, 8, "facts");
  field(firstFacts, "title").value = "First draft title";
  field(firstFacts, "title").dispatch("input");
  field(firstFacts, "title").value = "Latest draft title";
  field(firstFacts, "title").dispatch("input");
  field(secondFacts, "title").value = "Saved second title";
  field(secondFacts, "title").dispatch("input");
  await secondFacts.dispatch("submit");
  await settle();

  const restoredFacts = formFor(elements.tasks, 7, "facts");
  assert.equal(field(restoredFacts, "title").value, "Latest draft title");
  assert.equal(button(restoredFacts, "Save task details").disabled, false);
  assert.match(
    find(restoredFacts, (node) => node.className === "draft-status").textContent,
    /restored after refresh/,
  );
  assert.equal(elements["state-error"].hidden, true);
});

test("invalid Project draft fails closed after automatic refresh", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  let projects = [project(1, "College"), project(2, "Temporary")];
  const elements = createPage(async (path, options = {}) => {
    if (path === "/v1/task-planning") {
      const body = JSON.parse(options.body);
      shown = shown.map((item) => item.id === body.task_id ? { ...item, estimated_minutes: body.estimated_minutes } : item);
      projects = [project(1, "College")];
      return response({ ok: true, result: body });
    }
    return response(overview(shown, projects));
  });
  await settle();

  const secondFacts = formFor(elements.tasks, 8, "facts");
  field(secondFacts, "project_id").value = "2";
  field(secondFacts, "project_id").dispatch("change");
  const firstPlanning = formFor(elements.tasks, 7, "planning");
  field(firstPlanning, "estimated_minutes").value = "45";
  field(firstPlanning, "estimated_minutes").dispatch("input");
  await firstPlanning.dispatch("submit");
  await settle();

  assert.match(elements["state-error"].textContent, /could not be restored/);
  const refreshedSecond = formFor(elements.tasks, 8, "facts");
  assert.equal(field(refreshedSecond, "project_id").value, "");
  assert.equal(button(refreshedSecond, "Save task details").disabled, true);
});

test("draft for a Task that disappears fails closed with an explanation", async () => {
  let shown = [task(), task({ id: 8, title: "Second task", project_id: null, project_name: null })];
  const elements = createPage(async (path, options = {}) => {
    if (path === "/v1/task-planning") {
      const body = JSON.parse(options.body);
      shown = [{ ...shown[0], estimated_minutes: body.estimated_minutes }];
      return response({ ok: true, result: body });
    }
    return response(overview(shown));
  });
  await settle();

  const secondFacts = formFor(elements.tasks, 8, "facts");
  field(secondFacts, "title").value = "Unsaved second title";
  field(secondFacts, "title").dispatch("input");
  const firstPlanning = formFor(elements.tasks, 7, "planning");
  field(firstPlanning, "estimated_minutes").value = "45";
  field(firstPlanning, "estimated_minutes").dispatch("input");
  await firstPlanning.dispatch("submit");
  await settle();

  assert.match(elements["state-error"].textContent, /Task #8.*no longer editable/);
  assert.equal(all(elements.tasks, (node) => node.dataset.taskId === "8").length, 0);
});

test("HTTP 400 Work-requirements rejection preserves its draft", async () => {
  const calls = [];
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-planning") {
      return errorResponse("estimated_minutes must be positive", 400, "INVALID_REQUEST");
    }
    return response(overview(task()));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "planning");
  field(form, "estimated_minutes").value = "0";
  field(form, "estimated_minutes").dispatch("input");
  await form.dispatch("submit");
  await settle();

  assert.equal(field(form, "estimated_minutes").value, "0");
  assert.equal(field(form, "estimated_minutes").disabled, false);
  const message = find(form, (node) => node.className === "form-message");
  assert.match(message.textContent, /Work requirements were not saved/);
  assert.equal(elements.overview.hidden, false);
});

test("uncertain Work-requirements outcome locks stale state and never reposts", async () => {
  const calls = [];
  let shown = task();
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-planning") {
      const body = JSON.parse(options.body);
      shown = { ...shown, estimated_minutes: body.estimated_minutes };
      return errorResponse("server failed after commit", 500, "INTERNAL_SERVER_ERROR");
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "planning");
  field(form, "estimated_minutes").value = "50";
  field(form, "estimated_minutes").dispatch("input");
  await form.dispatch("submit");
  await settle();
  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /save result is uncertain/);

  await form.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-planning").length, 1);
  await elements["refresh-button"].dispatch("click");
  await settle();
  assert.equal(field(formFor(elements.tasks, 7, "planning"), "estimated_minutes").value, "50");
  assert.equal(calls.filter((call) => call.path === "/v1/task-planning").length, 1);
});

test("saved Work requirements lock stale state until Refresh succeeds", async () => {
  const calls = [];
  let shown = task();
  let failNextOverview = false;
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-planning") {
      const body = JSON.parse(options.body);
      shown = { ...shown, estimated_minutes: body.estimated_minutes };
      failNextOverview = true;
      return response({ ok: true, result: body });
    }
    if (failNextOverview) {
      failNextOverview = false;
      return errorResponse("overview unavailable", 500, "INTERNAL_SERVER_ERROR");
    }
    return response(overview(shown));
  });
  await settle();

  const form = formFor(elements.tasks, 7, "planning");
  field(form, "estimated_minutes").value = "60";
  field(form, "estimated_minutes").dispatch("input");
  await form.dispatch("submit");
  await settle();
  assert.equal(elements.overview.hidden, true);
  assert.match(elements["state-error"].textContent, /Work requirements were saved/);
  assert.match(elements["state-error"].textContent, /could not refresh/);

  await form.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-planning").length, 1);
  await elements["refresh-button"].dispatch("click");
  await settle();
  assert.equal(field(formFor(elements.tasks, 7, "planning"), "estimated_minutes").value, "60");
  assert.equal(calls.filter((call) => call.path === "/v1/task-planning").length, 1);
});

test("duplicate section submissions are suppressed while a Task save is in flight", async () => {
  const calls = [];
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const elements = createPage(async (path, options = {}) => {
    calls.push({ options, path });
    if (path === "/v1/task-facts") return pending;
    return response(overview([
      task(),
      task({ id: 8, title: "Second task", project_id: null, project_name: null }),
    ]));
  });
  await settle();

  const factsForm = formFor(elements.tasks, 7, "facts");
  const planningForm = formFor(elements.tasks, 7, "planning");
  const otherTaskForm = formFor(elements.tasks, 8, "facts");
  field(factsForm, "title").value = "Draft essay";
  field(factsForm, "title").dispatch("input");
  field(planningForm, "estimated_minutes").value = "45";
  field(planningForm, "estimated_minutes").dispatch("input");
  field(otherTaskForm, "title").value = "Second changed";
  field(otherTaskForm, "title").dispatch("input");
  factsForm.dispatch("submit");
  factsForm.dispatch("submit");
  planningForm.dispatch("submit");
  otherTaskForm.dispatch("submit");
  await settle();
  assert.equal(calls.filter((call) => call.path === "/v1/task-facts").length, 1);
  assert.equal(calls.filter((call) => call.path === "/v1/task-planning").length, 0);

  release(response({ ok: true, result: { task_id: 7 } }));
  await settle();
});

test("active-session display and historical action remain unchanged", async () => {
  const session = {
    id: 3,
    task_id: 7,
    task_title: "Drfat essay",
    planned_minutes: 30,
    selected_action: "Open the draft and revise the introduction.",
    started_at: "2026-10-27T14:00:00.000000Z",
  };
  const calls = [];
  const elements = createPage(async (path) => {
    calls.push(path);
    return response(overview(task(), [project(1, "College")], session));
  });
  await settle();

  assert.equal(find(elements["active-session"], (node) => node.tagName === "H3").textContent, "Drfat essay");
  assert.match(find(elements["active-session"], (node) => node.textContent.startsWith("Action:")).textContent, /revise the introduction/);
  assert.deepEqual(calls, ["/v1/overview"]);
  assert.equal(calls.some((path) => ["/v1/activate", "/v1/capture", "/v1/start"].includes(path)), false);
});
