"use strict";

const byId = (id) => document.getElementById(id);
const screens = ["idle", "recommendation", "active", "no-work", "closed"];
let recommendation = null;
let recommendationContext = null;
let pending = false;

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
  for (const button of document.querySelectorAll("button")) button.disabled = value;
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
  const timezone = byId("timezone").value.trim();
  const cap = byId("time-cap").value;
  if (timezone) body.timezone = timezone;
  if (cap !== "") body.time_cap_minutes = Number(cap);
  return body;
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
    showError(`${error.message} Check the timezone or server configuration, then try again.`);
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
  if (recommendationContext?.timezone) body.timezone = recommendationContext.timezone;
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
byId("start-button").addEventListener("click", startWork);
byId("feedback-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.submitter?.value) submitFeedback(event.submitter.value);
});
byId("next-button").addEventListener("click", activate);
