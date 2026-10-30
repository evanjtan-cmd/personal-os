"use strict";

const byId = (id) => document.getElementById(id);
const screens = ["idle", "recommendation", "active", "no-work", "closed"];
let recommendation = null;
let recommendationContext = null;
let pending = false;
let capturePending = false;
let restorePending = false;
let restoreToken = 0;
const excludedTaskIds = new Set();

function showScreen(name) {
  for (const screen of screens) byId(screen).hidden = screen !== name;
}

function showError(message) {
  const error = byId("error");
  error.textContent = message;
  error.hidden = false;
}

function clearError() {
  byId("error").hidden = true;
  byId("error").textContent = "";
}

function updateProgress() {
  const progress = byId("progress");
  if (pending) {
    progress.textContent = "Updating...";
    progress.hidden = false;
  } else if (restorePending) {
    progress.textContent = "Checking active work session...";
    progress.hidden = false;
  } else {
    progress.hidden = true;
  }
}

function setPending(value) {
  pending = value;
  updateProgress();
  for (const button of document.querySelectorAll("button:not(#capture-button)")) {
    button.disabled = value;
  }
}

function invalidateRestore() {
  restoreToken += 1;
  if (restorePending) {
    restorePending = false;
    updateProgress();
  }
}

function updateSkippedControls() {
  byId("skipped-controls").hidden = excludedTaskIds.size === 0;
}

function clearSkippedWork() {
  excludedTaskIds.clear();
  updateSkippedControls();
}

function setCapturePending(value) {
  capturePending = value;
  byId("capture-progress").hidden = !value;
  byId("capture-button").disabled = value;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function request(path, body) {
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

async function requestOverview() {
  const response = await fetch("/v1/overview", { credentials: "omit" });
  const envelope = await response.json();
  if (!response.ok || !envelope || typeof envelope !== "object" || envelope.ok !== true) {
    throw new Error(envelope?.error?.message || `Request failed (${response.status})`);
  }
  if (!envelope.result || typeof envelope.result !== "object" || Array.isArray(envelope.result)) {
    throw new Error("Invalid overview response.");
  }
  return envelope.result;
}

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0;
}

function activeSessionFromOverview(overview) {
  if (!Object.hasOwn(overview, "active_session")) {
    throw new Error("Invalid overview response.");
  }
  const session = overview.active_session;
  if (session === null) return null;
  if (
    !session || typeof session !== "object" || Array.isArray(session)
    || !isPositiveInteger(session.session_id)
    || !isPositiveInteger(session.task_id)
    || typeof session.task_title !== "string" || !session.task_title.trim()
    || !isPositiveInteger(session.planned_minutes)
    || (session.selected_action !== null && typeof session.selected_action !== "string")
    || typeof session.started_at !== "string" || Number.isNaN(Date.parse(session.started_at))
  ) {
    throw new Error("Invalid active session in overview response.");
  }
  return session;
}

async function restoreActiveSession() {
  const token = restoreToken;
  restorePending = true;
  updateProgress();
  try {
    const overview = await requestOverview();
    if (token !== restoreToken) return;
    const session = activeSessionFromOverview(overview);
    if (session === null) {
      showScreen("idle");
    } else {
      recommendation = null;
      renderActive(session);
    }
  } catch (error) {
    if (token !== restoreToken) return;
    showError(`Could not restore the active work session: ${error.message} Check the server, then try again.`);
  } finally {
    if (token === restoreToken) {
      restorePending = false;
      updateProgress();
    }
  }
}

function activationInputs() {
  const body = {};
  const cap = byId("time-cap").value;
  if (cap !== "") body.time_cap_minutes = Number(cap);
  return body;
}

function describeCapturedTask(task) {
  const mode = task.execution_mode === "ONE_SITTING"
    ? "one sitting"
    : "splittable";
  const duration = task.estimated_minutes === null
    ? ""
    : `, ${task.estimated_minutes} min`;
  const note = task.planning_note ? ` (${task.planning_note})` : "";
  return `${task.title} — ${mode}${duration}${note}`;
}

function describeCapturedProject(project) {
  if (!project) return null;
  if (!project.deadline) return `Project: ${project.name}`;
  const deadline = project.deadline.kind === "DATE"
    ? project.deadline.date
    : new Date(project.deadline.at).toLocaleString();
  return `Project: ${project.name} — deadline ${deadline}`;
}

function oneSittingNeedsDuration(task) {
  return task.execution_mode === "ONE_SITTING" && task.estimated_minutes === null;
}

function renderDurationQuestion(task, reloadText) {
  const form = document.createElement("form");
  form.className = "inline-form";
  const label = element("label", "Duration in minutes");
  const input = document.createElement("input");
  input.type = "number";
  input.min = "1";
  input.step = "1";
  input.inputMode = "numeric";
  input.required = true;
  label.append(input);
  const save = element("button", "Save", "button primary");
  save.type = "submit";
  const message = element("p", "", "form-message");
  message.hidden = true;
  form.append(label, save, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.hidden = true;
    save.disabled = true;
    try {
      await request("/v1/task-planning", {
        task_id: task.id,
        execution_mode: task.execution_mode,
        estimated_minutes: Number(input.value),
      });
      message.textContent = reloadText;
      message.hidden = false;
      form.replaceChildren(message);
    } catch (error) {
      message.textContent = `${error.message} Refresh state, then try again.`;
      message.hidden = false;
      save.disabled = false;
    }
  });
  return form;
}

function renderInboxFollowup(result, rawText) {
  const wrap = element("div", undefined, "resolution-box");
  wrap.append(
    element("p", `Saved to Inbox #${result.inbox_item_id}.`),
    element("p", result.unresolved_reason),
  );
  const form = document.createElement("form");
  form.className = "resolve-form";
  const label = element("label", "Edit & resolve");
  const input = document.createElement("textarea");
  input.rows = 3;
  input.required = true;
  input.value = rawText;
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
      const resolved = await request("/v1/resolve-inbox", {
        inbox_item_id: result.inbox_item_id,
        raw_text: input.value,
      });
      renderCaptureResult(resolved, input.value);
    } catch (error) {
      message.textContent = `${error.message} Refresh state, then try again.`;
      message.hidden = false;
      resolve.disabled = false;
      dismiss.disabled = false;
    }
  });
  dismiss.addEventListener("click", async () => {
    message.hidden = true;
    resolve.disabled = true;
    dismiss.disabled = true;
    try {
      await request("/v1/dismiss-inbox", { inbox_item_id: result.inbox_item_id });
      const output = byId("capture-result");
      output.className = "capture-result";
      output.replaceChildren(element("p", "Dismissed."));
    } catch (error) {
      message.textContent = `${error.message} Refresh state, then try again.`;
      message.hidden = false;
      resolve.disabled = false;
      dismiss.disabled = false;
    }
  });
  wrap.append(form);
  return wrap;
}

function renderCaptureResult(result, rawText) {
  const output = byId("capture-result");
  output.className = "capture-result";
  output.replaceChildren();
  if (result.status === "APPLIED") {
    const created = [
      describeCapturedProject(result.project),
      ...result.tasks.map(describeCapturedTask),
      ...result.commitments.map((commitment) => commitment.title),
    ].filter(Boolean);
    output.append(element("p", created.length
      ? `Captured: ${created.join("; ")}`
      : "Captured."));
    for (const task of result.tasks.filter(oneSittingNeedsDuration)) {
      const followup = element("div", undefined, "resolution-box");
      followup.append(
        element("p", `${task.title} needs a duration before recommendation.`),
        renderDurationQuestion(task, "Duration saved."),
      );
      output.append(followup);
    }
  } else if (result.status === "UNRESOLVED") {
    output.append(renderInboxFollowup(result, rawText));
    output.classList.add("unresolved");
  } else if (result.status === "FAILED") {
    const kind = result.failure_kind ? ` (${result.failure_kind})` : "";
    output.append(element("p", `Capture failed while interpreting this item${kind}. Please try again.`));
    output.classList.add("failed");
  } else {
    throw new Error("Unexpected capture response. Refresh and try again.");
  }
  output.hidden = false;
}

async function captureItem() {
  if (capturePending) return;
  const input = byId("capture-text");
  const rawText = input.value;
  const output = byId("capture-result");
  if (!rawText.trim()) {
    output.textContent = "Enter something to capture.";
    output.className = "capture-result failed";
    output.hidden = false;
    return;
  }
  output.hidden = true;
  setCapturePending(true);
  try {
    const result = await request("/v1/capture", { raw_text: rawText });
    renderCaptureResult(result, rawText);
    if (result.status !== "FAILED") input.value = "";
  } catch (error) {
    output.textContent = "Capture failed while interpreting this item. Please try again.";
    output.className = "capture-result failed";
    output.hidden = false;
  } finally {
    setCapturePending(false);
  }
}

function renderActive(result) {
  clearSkippedWork();
  recommendationContext = null;
  byId("active-title").textContent = result.task_title;
  byId("active-meta").textContent = `${result.planned_minutes} min planned · Started ${new Date(result.started_at).toLocaleString()}`;
  byId("active-action").textContent = result.selected_action || "";
  byId("active-action-wrap").hidden = !result.selected_action;
  byId("result-note").value = "";
  showScreen("active");
}

function noWorkTitle(reason) {
  if (reason === null) return "No work recommended right now.";
  if (typeof reason === "string" && reason.startsWith("ALL_")) {
    return "No unskipped work in this search.";
  }
  return "No feasible work right now.";
}

function renderActivation(result) {
  if (result.kind === "ACTIVE_SESSION") {
    recommendation = null;
    renderActive(result);
  } else if (result.kind === "RECOMMEND") {
    recommendation = result;
    byId("recommendation-title").textContent = result.task_title;
    byId("recommendation-meta").textContent = [result.project_name, `${result.duration_minutes} min`].filter(Boolean).join(" · ");
    byId("recommendation-action").textContent = result.action;
    byId("recommendation-explanation").textContent = result.explanation;
    showScreen("recommendation");
    updateSkippedControls();
  } else if (result.kind === "NO_WORK") {
    recommendation = null;
    byId("no-work-title").textContent = noWorkTitle(result.reason);
    byId("no-work-explanation").textContent = result.explanation;
    showScreen("no-work");
    updateSkippedControls();
  } else {
    throw new Error("Unexpected activation response. Refresh and try again.");
  }
}

async function activate({
  preserveExclusions = false,
  contextOverride = null,
  failureMessage = null,
} = {}) {
  if (pending) return false;
  invalidateRestore();
  const previousExcludedTaskIds = preserveExclusions ? null : [...excludedTaskIds];
  if (!preserveExclusions) clearSkippedWork();
  const context = contextOverride === null ? activationInputs() : { ...contextOverride };
  const body = { ...context };
  if (preserveExclusions && excludedTaskIds.size > 0) {
    body.excluded_task_ids = [...excludedTaskIds];
  }
  clearError();
  setPending(true);
  try {
    const result = await request("/v1/activate", body);
    recommendationContext = context;
    renderActivation(result);
    byId("activate-button").textContent = "New search";
    return true;
  } catch (error) {
    if (previousExcludedTaskIds !== null) {
      excludedTaskIds.clear();
      for (const taskId of previousExcludedTaskIds) excludedTaskIds.add(taskId);
      updateSkippedControls();
    }
    showError(failureMessage === null
      ? `${error.message} Check the server configuration, then try again.`
      : `${failureMessage}: ${error.message} The current recommendation is still available.`);
    return false;
  } finally {
    setPending(false);
  }
}

async function declineRecommendation() {
  if (pending || !recommendation) return;
  const declinedTaskId = recommendation.task_id;
  excludedTaskIds.add(declinedTaskId);
  updateSkippedControls();
  const succeeded = await activate({
    preserveExclusions: true,
    contextOverride: recommendationContext || {},
    failureMessage: "Could not find different work",
  });
  if (!succeeded) {
    excludedTaskIds.delete(declinedTaskId);
    updateSkippedControls();
  }
}

async function resetSkippedWork() {
  if (pending) return;
  const context = recommendationContext || activationInputs();
  await activate({ contextOverride: context });
}

async function startWork() {
  if (pending || !recommendation) return;
  invalidateRestore();
  const body = {
    task_id: recommendation.task_id,
    planned_minutes: recommendation.duration_minutes,
    selected_action: recommendation.action,
  };
  if (recommendationContext?.time_cap_minutes !== undefined) {
    body.available_minutes = recommendationContext.time_cap_minutes;
  }
  if (recommendation.lower_priority_authorization !== undefined) {
    body.lower_priority_authorization = recommendation.lower_priority_authorization;
  }
  clearError();
  setPending(true);
  try {
    const result = await request("/v1/start", body);
    recommendation = null;
    renderActive(result);
  } catch (error) {
    showError(`${error.message} The recommendation may have changed. Start a new search.`);
  } finally {
    setPending(false);
  }
}

async function submitFeedback(outcome) {
  if (pending) return;
  invalidateRestore();
  const body = { outcome };
  const note = byId("result-note").value;
  if (note.trim()) body.result_note = note;
  clearError();
  setPending(true);
  try {
    const result = await request("/v1/feedback", body);
    clearSkippedWork();
    recommendationContext = null;
    const outcomeCopy = {
      FINISHED: [`${result.task_title}: finished`, "Task completed."],
      PROGRESS: [`${result.task_title}: progress recorded`, "Session ended. Task remains open."],
      BLOCKED: [`${result.task_title}: blocked`, "Session ended. Task is blocked."],
    }[result.outcome];
    byId("closed-title").textContent = outcomeCopy[0];
    byId("closed-meta").textContent = outcomeCopy[1];
    showScreen("closed");
  } catch (error) {
    showError(`${error.message} Refresh the work state before trying again.`);
  } finally {
    setPending(false);
  }
}

byId("activate-form").addEventListener("submit", (event) => {
  event.preventDefault();
  activate();
});
byId("capture-form").addEventListener("submit", (event) => {
  event.preventDefault();
  captureItem();
});
byId("start-button").addEventListener("click", startWork);
byId("not-now-button").addEventListener("click", declineRecommendation);
byId("reset-skipped-button").addEventListener("click", resetSkippedWork);
byId("feedback-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.submitter?.value) submitFeedback(event.submitter.value);
});
byId("next-button").addEventListener("click", activate);
restoreActiveSession();
