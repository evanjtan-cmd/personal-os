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

function list(items, renderItem) {
  const output = element("ul", undefined, "state-list");
  for (const item of items) output.append(renderItem(item));
  return output;
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
    if (task.estimated_minutes !== null) {
      item.append(element("p", `Estimate: ${task.estimated_minutes} min`));
    }
    return item;
  }));
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
