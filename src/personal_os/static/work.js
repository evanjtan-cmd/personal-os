"use strict";

const byId = (id) => document.getElementById(id);
const screens = ["idle", "recommendation", "active", "no-work", "closed"];
let recommendation = null;
let recommendationContext = null;
let pending = false;
let capturePending = false;

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

function setPending(value) {
  pending = value;
  byId("progress").hidden = !value;
  for (const button of document.querySelectorAll("button:not(#capture-button)")) {
    button.disabled = value;
  }
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
      result.project?.name,
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
  byId("active-title").textContent = result.task_title;
  byId("active-meta").textContent = `${result.planned_minutes} min planned · Started ${new Date(result.started_at).toLocaleString()}`;
  byId("active-action").textContent = result.selected_action || "";
  byId("active-action-wrap").hidden = !result.selected_action;
  byId("result-note").value = "";
  showScreen("active");
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
  } else if (result.kind === "NO_WORK") {
    recommendation = null;
    byId("no-work-explanation").textContent = result.explanation;
    showScreen("no-work");
  } else {
    throw new Error("Unexpected activation response. Refresh and try again.");
  }
}

async function activate() {
  if (pending) return;
  const context = activationInputs();
  clearError();
  setPending(true);
  try {
    const result = await request("/v1/activate", context);
    recommendationContext = context;
    renderActivation(result);
    byId("activate-button").textContent = "Refresh work";
  } catch (error) {
    showError(`${error.message} Check the server configuration, then try again.`);
  } finally {
    setPending(false);
  }
}

async function startWork() {
  if (pending || !recommendation) return;
  const body = {
    task_id: recommendation.task_id,
    planned_minutes: recommendation.duration_minutes,
    selected_action: recommendation.action,
  };
  if (recommendationContext?.time_cap_minutes !== undefined) {
    body.available_minutes = recommendationContext.time_cap_minutes;
  }
  clearError();
  setPending(true);
  try {
    const result = await request("/v1/start", body);
    recommendation = null;
    renderActive(result);
  } catch (error) {
    showError(`${error.message} The recommendation may have changed. Find work again to refresh it.`);
  } finally {
    setPending(false);
  }
}

async function submitFeedback(outcome) {
  if (pending) return;
  const body = { outcome };
  const note = byId("result-note").value;
  if (note.trim()) body.result_note = note;
  clearError();
  setPending(true);
  try {
    const result = await request("/v1/feedback", body);
    byId("closed-title").textContent = `${result.task_title}: ${result.outcome.toLowerCase()}`;
    byId("closed-meta").textContent = `Task status: ${result.task_status.toLowerCase()}`;
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
byId("feedback-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.submitter?.value) submitFeedback(event.submitter.value);
});
byId("next-button").addEventListener("click", activate);
