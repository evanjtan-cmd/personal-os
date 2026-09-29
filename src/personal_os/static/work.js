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

function renderCaptureResult(result) {
  const output = byId("capture-result");
  output.className = "capture-result";
  if (result.status === "APPLIED") {
    const created = [
      result.project?.name,
      ...result.tasks.map((task) => task.title),
      ...result.commitments.map((commitment) => commitment.title),
    ].filter(Boolean);
    output.textContent = created.length
      ? `Captured #${result.capture_id}: ${created.join("; ")}`
      : `Captured #${result.capture_id}.`;
  } else if (result.status === "UNRESOLVED") {
    output.textContent = `Saved to Inbox #${result.inbox_item_id}: ${result.unresolved_reason}`;
    output.classList.add("unresolved");
  } else if (result.status === "FAILED") {
    output.textContent = `Capture #${result.capture_id} failed (${result.failure_kind}): ${result.failure_reason}`;
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
    renderCaptureResult(result);
    if (result.status !== "FAILED") input.value = "";
  } catch (error) {
    output.textContent = `${error.message} Check the server configuration, then try again.`;
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
