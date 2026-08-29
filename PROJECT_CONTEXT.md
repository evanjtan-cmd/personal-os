# Personal OS

## Product Definition

Personal OS is a personal AI system that maintains an evolving model of what I need to do, what I am working toward, what is currently true, and what I should reasonably do next.

It is not primarily a task manager, calendar, chatbot, or NFC system. Those are interfaces or components.

The central system is:

Intake → Interpretation → Structured State → Eligibility/Prioritization → AI Reasoning → Output/Action → Feedback → Updated State

## Primary Use Cases

### Natural-language capture

Input:

“Water John's plants Monday and Wednesday.”

Expected interpretation:

* Type: Day task
* Action: Water John's plants
* Dates: Monday, Wednesday
* Exact time: none

The system must preserve the fact that something belongs on a day without inventing an arbitrary clock time.

Input:

“Call Mike tomorrow at 4 PM.”

Expected interpretation:

* Type: Fixed/timed commitment
* Date: tomorrow
* Time: 4 PM

A bare time such as “at 4” without AM/PM or unambiguous 24-hour notation is
unresolved; the system must not infer which clock hour was intended.

Input:

“I should spend some time on my college list this weekend.”

Expected interpretation:

* Type: Flexible project work
* Project: College
* Window: this weekend
* Exact time: none

### Context-aware recommendation

Input/context:

“I am ready to work.”

Possible triggers:

* Work NFC
* Shortcut
* button
* voice
* UI

The system checks:

* current date/time
* hard calendar commitments
* day obligations
* deadlines
* active projects
* eligible actions
* constraints
* available useful time
* recent work/history
* priorities

It then returns one concrete recommendation such as:

“Call the next five businesses for 35 minutes.”

The system must not treat four free hours as an instruction to work for four hours.

### Session lifecycle

Start:

* selected action
* project
* planned duration
* start time
* reason/context

Finish:

* actual duration
* Finished / Progress / Blocked
* optional natural-language result

The system then:

* logs the session
* updates task/project state
* generates or updates the next action
* learns from actual duration where useful

## State Model

The system should eventually represent:

* Fixed events
* Day tasks
* Windowed tasks
* Deadlines
* Flexible tasks
* Routines
* Projects
* Goals
* Waiting-for items
* Dependencies
* Decisions
* Open questions
* Inbox/unresolved items
* Rules/preferences
* Temporary context
* Session/history data
* Confidence/uncertainty where relevant

## Planning Principles

Hard constraints should be handled deterministically before AI reasoning.

AI should operate primarily on eligible choices rather than being asked to infer the entire schedule from scratch.

Availability and recommended work duration are separate concepts.

Project names are not executable actions. Projects should maintain concrete next actions.

The system should distinguish:

* MUST
* SHOULD
* COULD

It should also be capable of recommending:

* stop;
* take a break;
* nothing currently requires attention.

## Additional Desired Intelligence

Eventually support:

* project health
* stale-item detection
* deadline-risk detection
* waiting-for follow-ups
* dependencies
* decision memory
* open questions
* automatic plan repair
* opportunity batching
* effort/energy matching
* learned duration estimates
* change detection
* restrained proactive notifications

## Current Prototype Assets

An existing Google Sheet called “Personal OS - Tasks, Projects & Sessions” contains early versions of:

* Tasks
* Projects
* Sessions
* Inbox
* Rules
* Calendar Semantics
* State

It is reference material and usable prototype data, but its structure may be replaced if a better architecture emerges.

Google Calendar is an important context source.

Some calendar entries may represent soft planning placeholders rather than hard commitments. Calendar semantics therefore cannot be based only on whether an event has a start/end time.

## Intended Technology Direction

Current tools:

* ChatGPT
* Codex
* Google Calendar
* Google Sheets
* iPhone Shortcuts
* NFC tags
* OpenAI APIs where useful

NFC and Shortcuts should initially remain thin interfaces over the central system.

The implementation should start with the smallest architecture that can demonstrate the complete loop reliably.

## MVP Success Condition

A successful first version lets me:

1. submit a natural-language item and have it structured correctly;
2. maintain a small set of tasks/projects/rules;
3. request “What should I do now?”;
4. receive one sensible context-aware action and duration;
5. start that work session;
6. finish it and report what happened;
7. see the underlying state correctly update.

Everything else is secondary until this loop works.
