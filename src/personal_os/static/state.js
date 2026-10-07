"use strict";

const byId = (id) => document.getElementById(id);

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function empty(message) {
  return element("p", message, "empty-state");
}

function formatInstant(value) {
  return new Date(value).toLocaleString();
}

function formatSchedule(schedule) {
  if (schedule.mode === "DAY") return `Day: ${schedule.day_date}`;
  if (schedule.mode === "WINDOW") {
    return `Window: ${formatInstant(schedule.window_start)} to ${formatInstant(schedule.window_end)}`;
  }
  return "Flexible";
}

function formatDeadline(deadline) {
  if (!deadline) return null;
  if (deadline.kind === "DATE") return `Deadline: ${deadline.date}`;
  return `Deadline: ${formatInstant(deadline.at)}`;
}

function needsDuration(task) {
  return task.execution_mode === "ONE_SITTING" && task.estimated_minutes === null;
}

function list(items, renderItem) {
  const output = element("ul", undefined, "state-list");
  for (const item of items) output.append(renderItem(item));
  return output;
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "omit",
  });
  const envelope = await response.json();
  if (!response.ok || !envelope.ok) {
    throw new Error(envelope.error?.message || `Request failed (${response.status})`);
  }
  return envelope.result;
}

function renderDurationQuestion(task) {
  const form = document.createElement("form");
  form.className = "inline-form";
  const label = element("label", "Duration in minutes");
  const input = document.createElement("input");
  input.name = "estimated_minutes";
  input.type = "number";
  input.min = "1";
  input.step = "1";
  input.inputMode = "numeric";
  input.required = true;
  label.append(input);
  const message = element("p", "", "form-message");
  message.hidden = true;
  const save = element("button", "Save", "button primary");
  save.type = "submit";
  form.append(label, save, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.hidden = true;
    save.disabled = true;
    try {
      await postJson("/v1/task-planning", {
        task_id: task.id,
        execution_mode: task.execution_mode,
        estimated_minutes: Number(input.value),
      });
      await loadOverview();
    } catch (caught) {
      message.textContent = `${caught.message} Refresh state, then try again.`;
      message.hidden = false;
    } finally {
      save.disabled = false;
    }
  });
  return form;
}

function renderInboxControls(entry) {
  const wrap = element("div", undefined, "resolution-box");
  const form = document.createElement("form");
  form.className = "resolve-form";
  const label = element("label", "Edit & resolve");
  const input = document.createElement("textarea");
  input.name = "raw_text";
  input.rows = 3;
  input.required = true;
  input.value = entry.raw_text;
  label.append(input);
  const actions = element("div", undefined, "inline-actions");
  const resolve = element("button", "Edit & resolve", "button primary");
  resolve.type = "submit";
  const dismiss = element("button", "Dismiss", "button");
  dismiss.type = "button";
  actions.append(resolve, dismiss);
  const message = element("p", "", "form-message");
  message.hidden = true;
  form.append(label, actions, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.hidden = true;
    resolve.disabled = true;
    dismiss.disabled = true;
    try {
      await postJson("/v1/resolve-inbox", {
        inbox_item_id: entry.id,
        raw_text: input.value,
      });
      await loadOverview();
    } catch (caught) {
      message.textContent = `${caught.message} Refresh state, then try again.`;
      message.hidden = false;
    } finally {
      resolve.disabled = false;
      dismiss.disabled = false;
    }
  });
  dismiss.addEventListener("click", async () => {
    message.hidden = true;
    resolve.disabled = true;
    dismiss.disabled = true;
    try {
      await postJson("/v1/dismiss-inbox", { inbox_item_id: entry.id });
      await loadOverview();
    } catch (caught) {
      message.textContent = `${caught.message} Refresh state, then try again.`;
      message.hidden = false;
    } finally {
      resolve.disabled = false;
      dismiss.disabled = false;
    }
  });
  wrap.append(form);
  return wrap;
}

function renderNeedsInput(result) {
  const target = byId("needs-input");
  const items = [];
  for (const entry of result.inbox) {
    items.push({ kind: "inbox", entry });
  }
  for (const task of result.tasks.filter(needsDuration)) {
    items.push({ kind: "duration", task });
  }
  if (!items.length) {
    target.replaceChildren(empty("Nothing needs input."));
    return;
  }
  target.replaceChildren(list(items, (item) => {
    const node = element("li", undefined, "state-item");
    if (item.kind === "inbox") {
      node.append(
        element("p", "Inbox", "item-status"),
        element("h3", item.entry.raw_text),
        element("p", item.entry.unresolved_reason),
        renderInboxControls(item.entry),
      );
    } else {
      node.append(
        element("p", "Duration needed", "item-status"),
        element("h3", item.task.title),
        element("p", "Needs a duration before recommendation."),
        renderDurationQuestion(item.task),
      );
    }
    return node;
  }));
}

function renderActive(session) {
  const target = byId("active-session");
  if (!session) {
    target.replaceChildren(empty("No active session."));
    return;
  }
  const item = element("div", undefined, "state-item");
  item.append(
    element("h3", session.task_title || `Task #${session.task_id}`),
    element("p", `${session.planned_minutes} min planned · Started ${formatInstant(session.started_at)}`),
  );
  if (session.selected_action) {
    item.append(element("p", `Action: ${session.selected_action}`));
  }
  target.replaceChildren(item);
}

function renderTasks(tasks) {
  const target = byId("tasks");
  if (!tasks.length) {
    target.replaceChildren(empty("No open or blocked tasks."));
    return;
  }
  target.replaceChildren(list(tasks, (task) => {
    const item = element(
      "li",
      undefined,
      `state-item${task.status === "BLOCKED" ? " blocked" : ""}`,
    );
    const facts = [];
    if (task.project_name) facts.push(task.project_name);
    if (task.importance !== "UNSPECIFIED") facts.push(task.importance);
    if (task.schedule.mode !== "FLEXIBLE") facts.push(formatSchedule(task.schedule));
    const deadline = formatDeadline(task.deadline);
    if (deadline) facts.push(deadline);
    if (task.execution_mode === "ONE_SITTING") facts.push("ONE_SITTING");
    if (task.estimated_minutes !== null) facts.push(`${task.estimated_minutes} min`);
    if (task.status === "BLOCKED") facts.push("BLOCKED");
    item.append(
      element("h3", task.title),
      element("p", facts.join(" · ") || "Open", "meta"),
    );
    item.append(renderTaskActions(task));
    item.append(renderPlanningEditor(task));
    return item;
  }));
}

function renderTaskActions(task) {
  const actions = element("div", undefined, "inline-actions");
  const done = element("button", "Done", "button primary");
  done.type = "button";
  const remove = element("button", "Remove", "button");
  remove.type = "button";
  actions.append(done, remove);
  if (task.status === "BLOCKED") {
    const unblock = element("button", "Unblock", "button");
    unblock.type = "button";
    unblock.addEventListener("click", () => correctTaskStatus(task, "OPEN", actions));
    actions.append(unblock);
  }
  done.addEventListener("click", () => correctTaskStatus(task, "COMPLETED", actions));
  remove.addEventListener("click", () => correctTaskStatus(task, "CANCELLED", actions));
  return actions;
}

async function correctTaskStatus(task, status, container) {
  for (const button of container.querySelectorAll("button")) button.disabled = true;
  try {
    await postJson("/v1/task-status", { task_id: task.id, status });
    await loadOverview();
  } catch (caught) {
    const message = element("p", `${caught.message} Refresh state, then try again.`, "form-message");
    container.after(message);
    for (const button of container.querySelectorAll("button")) button.disabled = false;
  }
}

function renderPlanningEditor(task) {
  const details = document.createElement("details");
  details.className = "planning-editor";
  details.append(element("summary", "More"));

  const form = document.createElement("form");
  form.dataset.taskId = String(task.id);

  const modeLabel = element("label", "Can this be split across work sessions?");
  const modeSelect = document.createElement("select");
  modeSelect.name = "execution_mode";
  for (const [value, text] of [
    ["SPLITTABLE", "Yes"],
    ["ONE_SITTING", "No, it needs one sitting"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    option.selected = task.execution_mode === value;
    modeSelect.append(option);
  }
  modeLabel.append(modeSelect);

  const minutesLabel = element("label", "About how long total?");
  const minutesInput = document.createElement("input");
  minutesInput.name = "estimated_minutes";
  minutesInput.type = "number";
  minutesInput.min = "1";
  minutesInput.step = "1";
  minutesInput.inputMode = "numeric";
  minutesInput.placeholder = "Minutes";
  minutesInput.value = task.estimated_minutes === null ? "" : String(task.estimated_minutes);
  minutesLabel.append(minutesInput);

  const message = element("p", "", "form-message");
  message.hidden = true;
  const actions = element("div", undefined, "planning-actions");
  const save = element("button", "Save planning", "button primary");
  save.type = "submit";
  actions.append(save);
  form.append(modeLabel, minutesLabel, actions, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const minutes = minutesInput.value.trim();
    const body = {
      task_id: task.id,
      execution_mode: modeSelect.value,
      estimated_minutes: minutes === "" ? null : Number(minutes),
    };
    message.hidden = true;
    save.disabled = true;
    try {
      await postJson("/v1/task-planning", body);
      await loadOverview();
    } catch (caught) {
      message.textContent = `${caught.message} Refresh state, then try again.`;
      message.hidden = false;
    } finally {
      save.disabled = false;
    }
  });
  details.append(form);
  return details;
}

function renderProjects(projects) {
  const target = byId("projects");
  if (!projects.length) {
    target.replaceChildren(empty("No active projects."));
    return;
  }
  target.replaceChildren(list(projects, (project) => {
    const item = element("li", undefined, "state-item");
    item.append(element("h3", project.name));
    if (project.description) item.append(element("p", project.description));
    return item;
  }));
}

async function loadOverview() {
  const button = byId("refresh-button");
  const error = byId("state-error");
  button.disabled = true;
  error.hidden = true;
  byId("state-progress").hidden = false;
  try {
    const response = await fetch("/v1/overview", { credentials: "omit" });
    const envelope = await response.json();
    if (!response.ok || !envelope.ok) {
      throw new Error(envelope.error?.message || `Request failed (${response.status})`);
    }
    renderNeedsInput(envelope.result);
    renderActive(envelope.result.active_session);
    renderTasks(envelope.result.tasks);
    renderProjects(envelope.result.projects);
    byId("overview").hidden = false;
  } catch (caught) {
    error.textContent = `${caught.message} Check the server, then try again.`;
    error.hidden = false;
  } finally {
    byId("state-progress").hidden = true;
    button.disabled = false;
  }
}

byId("refresh-button").addEventListener("click", loadOverview);
loadOverview();
