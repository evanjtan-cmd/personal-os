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

function needsCommitmentProtection(commitment) {
  return commitment.protection_needs_input === true;
}

const PRIORITY_OPTIONS = [
  ["MUST", "High"],
  ["SHOULD", "Medium"],
  ["COULD", "Low"],
  ["UNSPECIFIED", "Not set"],
];

function priorityLabel(value) {
  return Object.fromEntries(PRIORITY_OPTIONS)[value];
}

function list(items, renderItem) {
  const output = element("ul", undefined, "state-list");
  for (const item of items) output.append(renderItem(item));
  return output;
}

const CONFIRMED_REJECTION = "CONFIRMED_REJECTION";
const UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME";
const taskEditorDrafts = new Map();
let preserveDraftsOnRequiredRefresh = false;
let taskSaveInFlight = false;

class PostJsonError extends Error {
  constructor(message, outcome) {
    super(message);
    this.name = "PostJsonError";
    this.outcome = outcome;
  }
}

function caughtMessage(caught, fallback) {
  return caught && typeof caught.message === "string" && caught.message
    ? caught.message
    : fallback;
}

function setTaskDraftSection(taskId, section, values, baseline) {
  const draft = taskEditorDrafts.get(taskId) || {};
  draft[section] = {
    ...values,
    baseline: draft[section]?.baseline || baseline,
    restored: false,
  };
  taskEditorDrafts.set(taskId, draft);
}

function clearTaskDraftSection(taskId, section) {
  const draft = taskEditorDrafts.get(taskId);
  if (!draft) return;
  delete draft[section];
  if (!draft.facts && !draft.planning) taskEditorDrafts.delete(taskId);
}

function prepareTaskDraftsForRestore(result) {
  const tasksById = new Map(result.tasks.map((task) => [task.id, task]));
  const activeProjectIds = new Set(result.projects.map((project) => project.id));
  const warnings = [];
  const priorityValues = new Set(PRIORITY_OPTIONS.map(([value]) => value));

  for (const [taskId, draft] of taskEditorDrafts) {
    const task = tasksById.get(taskId);
    if (!task) {
      taskEditorDrafts.delete(taskId);
      warnings.push(
        `Unsaved edits for Task #${taskId} could not be restored because the Task is no longer editable.`,
      );
      continue;
    }

    if (draft.facts) {
      const projectValue = draft.facts.projectValue;
      const projectId = projectValue === "" ? null : Number(projectValue);
      const baseline = draft.facts.baseline;
      const projectIsSafe = (
        projectId === null
        || (
          Number.isInteger(projectId)
          && projectId > 0
          && (activeProjectIds.has(projectId) || projectId === task.project_id)
        )
      );
      const factsAreSafe = (
        typeof draft.facts.title === "string"
        && priorityValues.has(draft.facts.importance)
        && projectIsSafe
        && baseline !== null
        && typeof baseline === "object"
        && typeof baseline.title === "string"
        && priorityValues.has(baseline.importance)
        && (
          baseline.projectId === null
          || (Number.isInteger(baseline.projectId) && baseline.projectId > 0)
        )
      );
      if (!factsAreSafe) {
        clearTaskDraftSection(taskId, "facts");
        warnings.push(
          `Unsaved Task details for Task #${taskId} could not be restored because a saved choice is no longer valid.`,
        );
      } else if (
        baseline.title !== task.title
        || baseline.importance !== task.importance
        || baseline.projectId !== task.project_id
      ) {
        clearTaskDraftSection(taskId, "facts");
        warnings.push(
          `Unsaved Task details for Task #${taskId} were not restored because the Task changed elsewhere. The latest saved Task details are shown.`,
        );
      } else {
        draft.facts.restored = true;
      }
    }

    if (draft.planning) {
      const baseline = draft.planning.baseline;
      const planningIsSafe = (
        typeof draft.planning.estimatedMinutes === "string"
        && typeof draft.planning.canSplit === "boolean"
        && baseline !== null
        && typeof baseline === "object"
        && ["SPLITTABLE", "ONE_SITTING"].includes(baseline.executionMode)
        && (
          baseline.estimatedMinutes === null
          || (
            Number.isInteger(baseline.estimatedMinutes)
            && baseline.estimatedMinutes > 0
          )
        )
      );
      if (!planningIsSafe) {
        clearTaskDraftSection(taskId, "planning");
        warnings.push(
          `Unsaved Work requirements for Task #${taskId} could not be restored because the draft is no longer valid.`,
        );
      } else if (
        baseline.executionMode !== task.execution_mode
        || baseline.estimatedMinutes !== task.estimated_minutes
      ) {
        clearTaskDraftSection(taskId, "planning");
        warnings.push(
          `Unsaved Work requirements for Task #${taskId} were not restored because the Task changed elsewhere. The latest saved Work requirements are shown.`,
        );
      } else {
        draft.planning.restored = true;
      }
    }
  }
  return warnings;
}

async function postJson(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "omit",
    });
  } catch (caught) {
    throw new PostJsonError(
      caughtMessage(caught, "The request did not return a response."),
      UNKNOWN_OUTCOME,
    );
  }

  let envelope;
  try {
    envelope = await response.json();
  } catch (caught) {
    throw new PostJsonError(
      caughtMessage(caught, "The server response could not be read."),
      UNKNOWN_OUTCOME,
    );
  }

  const isEnvelope = envelope !== null && typeof envelope === "object";
  const hasResult = isEnvelope && Object.prototype.hasOwnProperty.call(
    envelope,
    "result",
  );
  if (response.ok && isEnvelope && envelope.ok === true && hasResult) {
    return envelope.result;
  }

  const serverMessage = (
    isEnvelope
    && envelope.error !== null
    && typeof envelope.error === "object"
    && typeof envelope.error.message === "string"
    && envelope.error.message
  ) || `Request failed (${response.status})`;
  if (
    response.status === 400
    && isEnvelope
    && envelope.ok === false
    && envelope.error?.code === "INVALID_REQUEST"
  ) {
    throw new PostJsonError(serverMessage, CONFIRMED_REJECTION);
  }
  throw new PostJsonError(serverMessage, UNKNOWN_OUTCOME);
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

async function configureCommitment(commitment, durationMinutes, container) {
  for (const control of container.querySelectorAll("button,input")) control.disabled = true;
  try {
    await postJson("/v1/commitment-protection", {
      commitment_id: commitment.id,
      duration_minutes: durationMinutes,
    });
    await loadOverview();
  } catch (caught) {
    const message = element("p", `${caught.message} Refresh state, then try again.`, "form-message");
    container.after(message);
    for (const control of container.querySelectorAll("button,input")) control.disabled = false;
  }
}

function renderCommitmentProtectionQuestion(commitment) {
  const box = element("div", undefined, "resolution-box");
  box.append(element("p", "Should this reserve time from work recommendations?"));
  const actions = element("div", undefined, "inline-actions");
  for (const minutes of [30, 60, 90]) {
    const button = element("button", `${minutes} min`, "button");
    button.type = "button";
    button.addEventListener("click", () => configureCommitment(commitment, minutes, box));
    actions.append(button);
  }
  const no = element("button", "No", "button");
  no.type = "button";
  no.addEventListener("click", () => configureCommitment(commitment, null, box));
  actions.append(no);

  const form = document.createElement("form");
  form.className = "inline-form";
  const label = element("label", "Custom minutes");
  const input = document.createElement("input");
  input.name = "duration_minutes";
  input.type = "number";
  input.min = "1";
  input.step = "1";
  input.inputMode = "numeric";
  input.required = true;
  label.append(input);
  const save = element("button", "Custom", "button primary");
  save.type = "submit";
  form.append(label, save);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await configureCommitment(commitment, Number(input.value), box);
  });
  box.append(actions, form);
  return box;
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
  for (const commitment of result.commitments.filter(needsCommitmentProtection)) {
    items.push({ kind: "commitment", commitment });
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
    } else if (item.kind === "duration") {
      node.append(
        element("p", "Duration needed", "item-status"),
        element("h3", item.task.title),
        element("p", "Needs a duration before recommendation."),
        renderDurationQuestion(item.task),
      );
    } else {
      node.append(
        element("p", "Protection needs input", "item-status"),
        element("h3", item.commitment.title),
        element("p", formatCommitmentTime(item.commitment)),
        renderCommitmentProtectionQuestion(item.commitment),
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

function renderTaskDetailsEditor(task, projects) {
  const existingDraft = taskEditorDrafts.get(task.id);
  const details = document.createElement("details");
  details.className = "planning-editor task-details-editor";
  details.open = Boolean(existingDraft?.facts || existingDraft?.planning);
  details.append(element("summary", "Edit details"));
  details.append(element(
    "p",
    "Task details and work requirements save separately.",
    "editor-help",
  ));

  const factsSection = element("section", undefined, "editor-section");
  factsSection.append(element("h4", "Task details"));
  const factsForm = document.createElement("form");
  factsForm.className = "editor-form task-facts-form";
  factsForm.dataset.taskId = String(task.id);
  factsForm.dataset.section = "facts";

  const titleLabel = element("label", "Task name");
  const titleInput = document.createElement("input");
  titleInput.name = "title";
  titleInput.type = "text";
  titleInput.required = true;
  titleInput.value = task.title;
  titleLabel.append(titleInput);

  const priorityFieldset = document.createElement("fieldset");
  priorityFieldset.className = "priority-fieldset";
  priorityFieldset.append(element("legend", "Priority"));
  const priorityChoices = element("div", undefined, "priority-choices");
  const priorityRadios = [];
  for (const [value, label] of PRIORITY_OPTIONS) {
    const choice = element("label", undefined, "priority-choice");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = `task-${task.id}-priority`;
    radio.id = `task-${task.id}-priority-${value.toLowerCase()}`;
    radio.value = value;
    radio.checked = task.importance === value;
    choice.htmlFor = radio.id;
    choice.append(radio, element("span", label));
    priorityChoices.append(choice);
    priorityRadios.push(radio);
  }
  priorityFieldset.append(priorityChoices);
  const priorityHelp = element(
    "p",
    "When any High-priority Task is feasible, recommendations are limited to feasible High-priority Tasks.",
    "meta",
  );

  const projectControl = element("label", "Project");
  const projectSelect = document.createElement("select");
  projectSelect.name = "project_id";
  const noProject = document.createElement("option");
  noProject.value = "";
  noProject.textContent = "No project";
  projectSelect.append(noProject);
  const activeProjectIds = new Set();
  for (const project of projects) {
    activeProjectIds.add(project.id);
    const option = document.createElement("option");
    option.value = String(project.id);
    option.textContent = project.name;
    projectSelect.append(option);
  }
  const currentProjectIsInactive = (
    task.project_id !== null && !activeProjectIds.has(task.project_id)
  );
  if (currentProjectIsInactive) {
    const current = document.createElement("option");
    current.value = String(task.project_id);
    current.textContent = `${task.project_name || `Project #${task.project_id}`} (inactive, current)`;
    current.disabled = true;
    projectSelect.append(current);
  }
  projectSelect.value = task.project_id === null ? "" : String(task.project_id);
  projectControl.append(projectSelect);

  const factsDraftStatus = element("p", "", "draft-status");
  factsDraftStatus.hidden = true;
  const factsMessage = element("p", "", "form-message");
  factsMessage.hidden = true;
  const factsActions = element("div", undefined, "planning-actions");
  const saveFacts = element("button", "Save task details", "button primary");
  saveFacts.type = "submit";
  saveFacts.disabled = true;
  const cancelFacts = element("button", "Cancel", "button");
  cancelFacts.type = "button";
  factsActions.append(saveFacts, cancelFacts);

  factsForm.append(titleLabel, priorityFieldset, priorityHelp, projectControl);
  if (currentProjectIsInactive) {
    factsForm.append(element(
      "p",
      "The current Project is inactive. Choose an active Project or No project to correct this relationship.",
      "planning-warning",
    ));
  }
  factsForm.append(factsDraftStatus, factsActions, factsMessage);
  factsSection.append(factsForm);

  const planningSection = element("section", undefined, "editor-section");
  planningSection.append(element("h4", "Work requirements"));
  const planningForm = document.createElement("form");
  planningForm.className = "editor-form task-planning-form";
  planningForm.dataset.taskId = String(task.id);
  planningForm.dataset.section = "planning";

  const minutesLabel = element("label", "Estimated duration (minutes)");
  const minutesInput = document.createElement("input");
  minutesInput.name = "estimated_minutes";
  minutesInput.type = "number";
  minutesInput.min = "1";
  minutesInput.step = "1";
  minutesInput.inputMode = "numeric";
  minutesInput.placeholder = "Minutes";
  minutesInput.value = task.estimated_minutes === null ? "" : String(task.estimated_minutes);
  minutesLabel.append(minutesInput);

  const splitLabel = element("label", undefined, "checkbox-field");
  const splitInput = document.createElement("input");
  splitInput.name = "can_split";
  splitInput.type = "checkbox";
  splitInput.checked = task.execution_mode === "SPLITTABLE";
  splitLabel.append(splitInput, element("span", "Can be split across sessions"));

  const durationWarning = element(
    "p",
    "A one-sitting Task needs an estimated duration before it can be recommended.",
    "planning-warning",
  );
  const planningDraftStatus = element("p", "", "draft-status");
  planningDraftStatus.hidden = true;
  const planningMessage = element("p", "", "form-message");
  planningMessage.hidden = true;
  const planningActions = element("div", undefined, "planning-actions");
  const savePlanning = element("button", "Save work requirements", "button primary");
  savePlanning.type = "submit";
  savePlanning.disabled = true;
  const cancelPlanning = element("button", "Cancel", "button");
  cancelPlanning.type = "button";
  planningActions.append(savePlanning, cancelPlanning);
  planningForm.append(
    minutesLabel,
    splitLabel,
    durationWarning,
    planningDraftStatus,
    planningActions,
    planningMessage,
  );
  planningSection.append(planningForm);

  details.append(factsSection, planningSection);

  let submitting = false;
  let needsAuthoritativeRefresh = false;
  let editorReplaced = false;

  function setSelectedPriority(value) {
    for (const radio of priorityRadios) radio.checked = radio.value === value;
  }

  function selectedPriority() {
    return priorityRadios.find((radio) => radio.checked)?.value || task.importance;
  }

  function selectedProjectId() {
    return projectSelect.value === "" ? null : Number(projectSelect.value);
  }

  function factsBody() {
    const body = { task_id: task.id };
    if (titleInput.value.trim() !== task.title) body.title = titleInput.value;
    if (selectedPriority() !== task.importance) {
      body.importance = selectedPriority();
    }
    const projectId = selectedProjectId();
    if (projectId !== task.project_id) body.project_id = projectId;
    return body;
  }

  function planningBody() {
    const minutes = minutesInput.value.trim();
    return {
      task_id: task.id,
      execution_mode: splitInput.checked ? "SPLITTABLE" : "ONE_SITTING",
      estimated_minutes: minutes === "" ? null : Number(minutes),
    };
  }

  function setEditorDisabled(disabled) {
    titleInput.disabled = disabled;
    for (const radio of priorityRadios) radio.disabled = disabled;
    projectSelect.disabled = disabled;
    minutesInput.disabled = disabled;
    splitInput.disabled = disabled;
    saveFacts.disabled = disabled;
    cancelFacts.disabled = disabled;
    savePlanning.disabled = disabled;
    cancelPlanning.disabled = disabled;
  }

  function lockUntilAuthoritativeRefresh(text) {
    needsAuthoritativeRefresh = true;
    preserveDraftsOnRequiredRefresh = true;
    setEditorDisabled(true);
    byId("overview").hidden = true;
    const error = byId("state-error");
    error.textContent = text;
    error.hidden = false;
  }

  function setDraftStatus(target, draft) {
    target.hidden = !draft;
    target.textContent = draft
      ? (draft.restored ? "Unsaved changes restored after refresh." : "Unsaved changes.")
      : "";
  }

  function updateFactsState(restoring = false) {
    const changed = Object.keys(factsBody()).length > 1;
    const currentDraft = taskEditorDrafts.get(task.id)?.facts;
    if (!changed) {
      clearTaskDraftSection(task.id, "facts");
    } else if (!restoring || !currentDraft) {
      setTaskDraftSection(task.id, "facts", {
        title: titleInput.value,
        importance: selectedPriority(),
        projectValue: projectSelect.value,
      }, {
        title: task.title,
        importance: task.importance,
        projectId: task.project_id,
      });
    }
    setDraftStatus(factsDraftStatus, taskEditorDrafts.get(task.id)?.facts);
    saveFacts.disabled = !changed || submitting || needsAuthoritativeRefresh;
  }

  function updateDurationWarning() {
    durationWarning.hidden = splitInput.checked || minutesInput.value.trim() !== "";
  }

  function updatePlanningState(restoring = false) {
    const body = planningBody();
    const changed = (
      body.execution_mode !== task.execution_mode
      || body.estimated_minutes !== task.estimated_minutes
    );
    const currentDraft = taskEditorDrafts.get(task.id)?.planning;
    if (!changed) {
      clearTaskDraftSection(task.id, "planning");
    } else if (!restoring || !currentDraft) {
      setTaskDraftSection(task.id, "planning", {
        estimatedMinutes: minutesInput.value,
        canSplit: splitInput.checked,
      }, {
        executionMode: task.execution_mode,
        estimatedMinutes: task.estimated_minutes,
      });
    }
    setDraftStatus(planningDraftStatus, taskEditorDrafts.get(task.id)?.planning);
    savePlanning.disabled = !changed || submitting || needsAuthoritativeRefresh;
    updateDurationWarning();
  }

  if (existingDraft?.facts) {
    titleInput.value = existingDraft.facts.title;
    setSelectedPriority(existingDraft.facts.importance);
    projectSelect.value = existingDraft.facts.projectValue;
  }
  if (existingDraft?.planning) {
    minutesInput.value = existingDraft.planning.estimatedMinutes;
    splitInput.checked = existingDraft.planning.canSplit;
  }

  for (const control of [titleInput, projectSelect]) {
    control.addEventListener("input", () => updateFactsState());
    control.addEventListener("change", () => updateFactsState());
  }
  for (const radio of priorityRadios) {
    radio.addEventListener("change", () => updateFactsState());
  }
  minutesInput.addEventListener("input", () => updatePlanningState());
  minutesInput.addEventListener("change", () => updatePlanningState());
  splitInput.addEventListener("change", () => updatePlanningState());

  cancelFacts.addEventListener("click", () => {
    titleInput.value = task.title;
    setSelectedPriority(task.importance);
    projectSelect.value = task.project_id === null ? "" : String(task.project_id);
    clearTaskDraftSection(task.id, "facts");
    factsMessage.hidden = true;
    factsMessage.textContent = "";
    updateFactsState(true);
  });

  cancelPlanning.addEventListener("click", () => {
    minutesInput.value = task.estimated_minutes === null ? "" : String(task.estimated_minutes);
    splitInput.checked = task.execution_mode === "SPLITTABLE";
    clearTaskDraftSection(task.id, "planning");
    planningMessage.hidden = true;
    planningMessage.textContent = "";
    updatePlanningState(true);
  });

  async function saveSection(section, path, body, message, label) {
    if (submitting || taskSaveInFlight || needsAuthoritativeRefresh) return;
    const changed = section === "facts"
      ? Object.keys(body).length > 1
      : (
        body.execution_mode !== task.execution_mode
        || body.estimated_minutes !== task.estimated_minutes
      );
    if (!changed) return;
    message.hidden = true;
    submitting = true;
    taskSaveInFlight = true;
    setEditorDisabled(true);
    try {
      await postJson(path, body);
      clearTaskDraftSection(task.id, section);
      if (!await loadOverview({ preserveDrafts: true })) {
        lockUntilAuthoritativeRefresh(
          `The ${label} were saved, but the authoritative display could not refresh. Use Refresh to reload the current state.`,
        );
      } else {
        editorReplaced = true;
      }
    } catch (caught) {
      if (caught?.outcome === CONFIRMED_REJECTION) {
        message.textContent = `${caught.message} The ${label} were not saved. Review this section, then try again.`;
        message.hidden = false;
      } else {
        clearTaskDraftSection(task.id, section);
        lockUntilAuthoritativeRefresh(
          `The ${label} save result is uncertain: ${caughtMessage(caught, "the request did not complete normally")} The changes may have been saved. Use Refresh to reload authoritative state before editing again.`,
        );
      }
    } finally {
      submitting = false;
      taskSaveInFlight = false;
      if (!needsAuthoritativeRefresh && !editorReplaced) {
        setEditorDisabled(false);
        updateFactsState(true);
        updatePlanningState(true);
      }
    }
  }

  factsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveSection(
      "facts",
      "/v1/task-facts",
      factsBody(),
      factsMessage,
      "Task details",
    );
  });

  planningForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveSection(
      "planning",
      "/v1/task-planning",
      planningBody(),
      planningMessage,
      "Work requirements",
    );
  });

  updateFactsState(true);
  updatePlanningState(true);
  return details;
}

function renderTasks(tasks, projects) {
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
    if (task.importance !== "UNSPECIFIED") {
      facts.push(`Priority: ${priorityLabel(task.importance)}`);
    }
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
    item.append(renderTaskDetailsEditor(task, projects));
    return item;
  }));
}

function formatCommitmentTime(commitment) {
  const start = formatInstant(commitment.start_at);
  if (commitment.end_at) return `${start} to ${formatInstant(commitment.end_at)}`;
  return start;
}

function protectionLabel(commitment) {
  if (commitment.status === "CANCELLED") return "Does not reserve work time";
  if (commitment.protection_needs_input) return "Protection needs input";
  if (commitment.hardness === "HARD") return "Reserves work time";
  if (commitment.hardness === "SOFT") return "Does not reserve work time";
  return "Protection unknown";
}

async function cancelCommitment(commitment, container) {
  for (const button of container.querySelectorAll("button")) button.disabled = true;
  try {
    await postJson("/v1/cancel-commitment", { commitment_id: commitment.id });
    await loadOverview();
  } catch (caught) {
    const message = element("p", `${caught.message} Refresh state, then try again.`, "form-message");
    container.after(message);
    for (const button of container.querySelectorAll("button")) button.disabled = false;
  }
}

function renderCommitments(commitments) {
  const target = byId("commitments");
  if (!commitments.length) {
    target.replaceChildren(empty("No upcoming commitments."));
    return;
  }
  target.replaceChildren(list(commitments, (commitment) => {
    const item = element("li", undefined, "state-item");
    const actions = element("div", undefined, "inline-actions");
    const cancel = element("button", "Cancel", "button");
    cancel.type = "button";
    cancel.addEventListener("click", () => cancelCommitment(commitment, actions));
    actions.append(cancel);
    item.append(
      element("p", commitment.temporal_status, "item-status"),
      element("h3", commitment.title),
      element("p", `${formatCommitmentTime(commitment)} · ${protectionLabel(commitment)}`, "meta"),
      actions,
    );
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

function renderProjects(projects) {
  const target = byId("projects");
  if (!projects.length) {
    target.replaceChildren(empty("No active projects."));
    return;
  }
  target.replaceChildren(list(projects, (project) => {
    const item = element("li", undefined, "state-item");
    const facts = [];
    const deadline = formatDeadline(project.deadline);
    if (deadline) facts.push(deadline);
    item.append(element("h3", project.name));
    if (project.description) item.append(element("p", project.description));
    if (facts.length) item.append(element("p", facts.join(" · "), "meta"));
    return item;
  }));
}

function renderHistory(result) {
  const target = byId("history");
  const items = [];
  for (const task of result.task_history) items.push({ kind: "task", task });
  for (const commitment of result.commitment_history) {
    items.push({ kind: "commitment", commitment });
  }
  if (!items.length) {
    target.replaceChildren(empty("No completed or cancelled history."));
    return;
  }
  const details = document.createElement("details");
  details.open = true;
  details.append(element("summary", `Recent history (${items.length})`));
  details.append(list(items, (entry) => {
    const item = element("li", undefined, "state-item");
    if (entry.kind === "task") {
      const label = entry.task.status === "CANCELLED" ? "Removed" : "Completed";
      const actions = element("div", undefined, "inline-actions");
      const reopen = element("button", "Reopen", "button");
      reopen.type = "button";
      reopen.addEventListener("click", () => correctTaskStatus(entry.task, "OPEN", actions));
      actions.append(reopen);
      item.append(
        element("p", label, "item-status"),
        element("h3", entry.task.title),
        element("p", entry.task.project_name || "Task", "meta"),
        actions,
      );
    } else {
      const label = entry.commitment.status === "CANCELLED" ? "Cancelled" : "Past commitment";
      item.append(
        element("p", label, "item-status"),
        element("h3", entry.commitment.title),
        element("p", `${formatCommitmentTime(entry.commitment)} · ${protectionLabel(entry.commitment)}`, "meta"),
      );
    }
    return item;
  }));
  target.replaceChildren(details);
}

async function loadOverview({ preserveDrafts = false } = {}) {
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
    let draftWarnings = [];
    if (preserveDrafts) {
      draftWarnings = prepareTaskDraftsForRestore(envelope.result);
    } else {
      taskEditorDrafts.clear();
    }
    renderNeedsInput(envelope.result);
    renderActive(envelope.result.active_session);
    renderCommitments(envelope.result.commitments);
    renderTasks(envelope.result.tasks, envelope.result.projects);
    renderProjects(envelope.result.projects);
    renderHistory(envelope.result);
    byId("overview").hidden = false;
    if (draftWarnings.length) {
      error.textContent = draftWarnings.join(" ");
      error.hidden = false;
    }
    return true;
  } catch (caught) {
    error.textContent = `${caught.message} Check the server, then try again.`;
    error.hidden = false;
    return false;
  } finally {
    byId("state-progress").hidden = true;
    button.disabled = false;
  }
}

async function refreshOverview() {
  const succeeded = await loadOverview({
    preserveDrafts: preserveDraftsOnRequiredRefresh,
  });
  if (succeeded) preserveDraftsOnRequiredRefresh = false;
}

byId("refresh-button").addEventListener("click", refreshOverview);
loadOverview();
