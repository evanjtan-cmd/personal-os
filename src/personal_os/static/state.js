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

function formatPlanning(task) {
  const split = task.execution_mode === "ONE_SITTING"
    ? "Needs one sitting"
    : "Can be split across work sessions";
  const duration = task.estimated_minutes === null
    ? "Duration not set"
    : `${task.estimated_minutes} min total`;
  return `${split} · ${duration}`;
}

function planningWarning(task) {
  return task.execution_mode === "ONE_SITTING" && task.estimated_minutes === null
    ? "Needs a duration before it can be recommended."
    : null;
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
    const context = [task.importance, task.project_name].filter(Boolean).join(" · ");
    item.append(
      element("p", task.status, "item-status"),
      element("h3", task.title),
      element("p", context || "No project or importance set"),
      element("p", formatSchedule(task.schedule)),
    );
    const deadline = formatDeadline(task.deadline);
    if (deadline) item.append(element("p", deadline));
    item.append(element("p", formatPlanning(task)));
    const warning = planningWarning(task);
    if (warning) item.append(element("p", warning, "planning-warning"));
    item.append(renderPlanningEditor(task));
    return item;
  }));
}

function renderPlanningEditor(task) {
  const details = document.createElement("details");
  details.className = "planning-editor";
  details.append(element("summary", "Edit planning"));

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

function renderInbox(items) {
  const target = byId("inbox");
  if (!items.length) {
    target.replaceChildren(empty("No unresolved inbox items."));
    return;
  }
  target.replaceChildren(list(items, (entry) => {
    const item = element("li", undefined, "state-item");
    item.append(
      element("h3", entry.raw_text),
      element("p", entry.unresolved_reason),
    );
    return item;
  }));
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
    renderActive(envelope.result.active_session);
    renderTasks(envelope.result.tasks);
    renderInbox(envelope.result.inbox);
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
