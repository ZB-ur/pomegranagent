# Figma Child Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the edit-ready Figma file, design foundations, reusable components, all child-facing states, teacher-help recovery, and clickable child prototype flows for 鸭鸭日记本.

**Architecture:** Use one Figma Design file as the design source, with reusable variables and components rather than disconnected screenshots. Build the child experience from the current state machine and view contracts, use a sanitized live welcome capture only as a temporary layout reference, and validate every milestone with Figma metadata plus screenshots before proceeding.

**Tech Stack:** Figma Design, Figma Variables, Components and Prototype reactions; Codex Figma tools (`whoami`, `create_new_file`, `generate_figma_design`, `use_figma`, metadata and screenshot inspection); current native HTML/CSS/JavaScript as implementation reference.

**Spec:** `docs/superpowers/specs/2026-08-30-figma-full-product-interaction-design.md`

## Global Constraints

- Cover both `1024×576` and `1280×720` child viewports.
- Child experience is the first design priority; teacher route design is a separate follow-up plan.
- Use only fictional names and messages; do not upload a database, logs, API keys, environment variables, or real child data.
- Do not modify product code, APIs, database state, tests, the acceptance runner, or historical Lovable evidence in this plan.
- Figma is design truth; current code is runtime behavior truth; browser tests remain release truth.
- Preserve all existing user dirty paths and do not stop or reconfigure the separately authorized local acceptance server.
- Every `use_figma` call must load `figma-use`, return all affected node IDs, use no more than ten logical operations, and validate before the next write.
- New Figma text must load its current or chosen font before mutation; use available `PingFang SC` or `Microsoft YaHei` styles discovered at runtime rather than guessed style names.
- Main actions are at least `44×44px`; text contrast targets `4.5:1`; focus and UI boundaries target `3:1`; reduced-motion alternatives are documented.
- A failed Figma script is atomic: stop, inspect the error, correct it once, then retry.

---

### Task 1: Establish edit-capable Figma file and page skeleton

**Files:**
- External create: one Figma Design file named `鸭鸭日记本 · 全产品交互设计`
- No repository files modified

**Interfaces:**
- Consumes: authenticated Figma account and plan key from `figma_whoami`
- Produces: `fileKey`, file URL, and exact page IDs for all pages in the approved specification

- [ ] **Step 1: Reconfirm Figma identity and edit capability**

Call `figma_whoami` and verify the authenticated handle remains `ZHANGBEIFAN` and the expected plan is returned. If the seat remains `View`, do not claim write access.

- [ ] **Step 2: Obtain an editable design file**

Load `figma-create-new-file` before the call. If the account permits creation, call `create_new_file` with:

```json
{
  "editorType": "design",
  "fileName": "鸭鸭日记本 · 全产品交互设计",
  "planKey": "team::1674739421870096717"
}
```

If creation is denied, stop this task and request one user-created `/design/` URL with edit permission. Do not fall back to FigJam, Slides, Lovable, or a local mock file.

- [ ] **Step 3: Inspect the blank file before writing**

Load `figma-use` and run a read-only script:

```js
return {
  fileKey: figma.fileKey,
  editorType: figma.editorType,
  pages: figma.root.children.map(page => ({ id: page.id, name: page.name }))
};
```

Expected: `editorType === "figma"` and at least one initial page.

- [ ] **Step 4: Create the first eight pages**

In one incremental `use_figma` call, rename the initial page and create only these pages:

```js
const names = [
  '00 Cover & Handoff',
  '01 Foundations',
  '02 Components',
  '10 Child · Core States',
  '11 Child · Recovery & Teacher Help',
  '12 Child · Prototype Flows',
  '20 Teacher · Shell & Auth',
  '21 Teacher · Today'
];
```

Return every created or renamed page ID.

- [ ] **Step 5: Create the remaining eight pages**

In a second incremental `use_figma` call, create:

```js
const names = [
  '22 Teacher · Children',
  '23 Teacher · Ducks',
  '24 Teacher · Roster',
  '25 Teacher · Review',
  '26 Teacher · Growth',
  '27 Teacher · Search',
  '30 Cross-product Flows',
  '90 Code Mapping & Acceptance'
];
```

Return every created page ID.

- [ ] **Step 6: Verify exact file structure**

Run one read-only discovery call that returns all page names and IDs. Expected: exactly the sixteen names above, in numeric order, with no duplicate names.

---

### Task 2: Build design variables and foundational review board

**Files:**
- External modify: Figma page `01 Foundations`
- No repository files modified

**Interfaces:**
- Consumes: Figma `fileKey` and `01 Foundations` page ID
- Produces: primitive and semantic variable collection IDs, text-style IDs, and the Foundations board frame ID

- [ ] **Step 1: Discover fonts and existing variable collections**

On `01 Foundations`, return `listAvailableFontsAsync()` matches for `PingFang SC` and `Microsoft YaHei`, plus all local variable collections. Select an actually available regular and bold style; do not guess `SemiBold` spelling.

- [ ] **Step 2: Create primitive color variables**

Load `figma-generate-library` and its required design-system references. Create `Primitives / Color` with one `Default` mode and exact values:

```text
paper/child = #FFFDF5
ink/child = #242421
blue/600 = #1D5FB0
blue/700 = #0B4F9C
yellow/500 = #FFBF24
brown/700 = #7A4700
danger/700 = #9F2D20
white = #FFFFFF
disabled/bg = #D7DDE2
disabled/ink = #38424C
disabled/border = #67717D
```

Set explicit variable scopes for fills, text, or strokes; never leave `ALL_SCOPES`.

- [ ] **Step 3: Create semantic child variables**

Create `Semantic / Child` with one `Default` mode and aliases:

```text
surface/page -> paper/child
text/default -> ink/child
action/primary -> blue/600
focus/ring -> blue/700
accent/child-card -> yellow/500
border/child-card -> brown/700
feedback/danger -> danger/700
```

Create spacing variables `space/100=4`, `200=8`, `300=12`, `400=16`, `600=24`, `800=32`; radius variables `control=14`, `message=16`, `round=999`; and target variable `control/min=44`.

- [ ] **Step 4: Create the Foundations review board**

Build one auto-layout board named `Child Foundations` containing color swatches, type samples, spacing/radius samples, 44px target examples, a 4px focus ring example, status/error examples, and a reduced-motion note. Return all created node IDs and a screenshot.

- [ ] **Step 5: Validate variables and board**

Read back collection names, mode names, variable counts, scopes, aliases, board hierarchy and bounds. Expected: no `Mode 1`, no `ALL_SCOPES`, no zero-width text, and no overlapping board sections.

---

### Task 3: Create reusable child components

**Files:**
- External modify: Figma page `02 Components`
- No repository files modified

**Interfaces:**
- Consumes: child variables and discovered font names from Task 2
- Produces: component IDs for shell, buttons, record control, child card, message bubble, status, draft, and teacher-help dialog

- [ ] **Step 1: Create action components**

Create component sets with explicit variant properties:

```text
Child/Button: hierarchy=primary|secondary|danger, state=default|focused|disabled
Child/Record: state=ready|listening|disabled
Child/ChildCard: state=default|focused|selected|disabled
```

Use auto layout, bind semantic variables, enforce minimum `44×44px`, and return component-set and variant IDs.

- [ ] **Step 2: Create feedback components**

Create:

```text
Child/Status: tone=neutral|busy|success|danger
Child/Message: speaker=child|duck
Child/PendingDraft: state=present|retryable
Child/EmptyRoster
```

Text uses height auto-resize with explicit nonzero width. Return all component IDs.

- [ ] **Step 3: Create shell and dialog components**

Create `Child/Shell` for each viewport and `Child/TeacherHelpDialog` variants:

```text
mode=locked|unlocked
state=default|busy|error
```

Include labels, PIN field, teacher text area, recovery actions and close/lock actions without embedding real data.

- [ ] **Step 4: Verify components visually and structurally**

Return variant-property definitions, node dimensions, bound-variable summaries and screenshots. Expected: every required component exists once, variants have unique property combinations, text is unclipped, and controls meet minimum target size.

---

### Task 4: Build all child core-state frames

**Files:**
- External modify: Figma page `10 Child · Core States`
- External temporary layout reference: captured child welcome frame in the same Figma file
- No repository files modified

**Interfaces:**
- Consumes: Task 3 component IDs and current child state contract in `app/frontend/child/machine.mjs` and `view.mjs`
- Produces: twenty-four review frames, one per state and viewport, plus a state coverage result

- [ ] **Step 1: Capture a sanitized live welcome reference**

Load `figma-generate-design`. Use `generate_figma_design` against the existing local child welcome page only; do not click Start or expose roster data. In parallel, use `use_figma` to inspect the design-system components. Treat the capture as temporary layout reference, record its returned node ID, and do not use captured text as authoritative copy.

- [ ] **Step 2: Build the first six states at `1024×576`**

Using component instances and auto layout, create frames named:

```text
Child/1024/welcome
Child/1024/loading_roster
Child/1024/selecting_child
Child/1024/opening
Child/1024/ready
Child/1024/listening
```

Use fictional children `小雨` and `乐乐`; return all frame IDs and a composite screenshot.

- [ ] **Step 3: Build the remaining six states at `1024×576`**

Create:

```text
Child/1024/submitting
Child/1024/speaking
Child/1024/submission_failed
Child/1024/saving_conversation
Child/1024/completed
Child/1024/recovery
```

The failure frame must visibly preserve the fictional draft `我今天给小鸭添了水`; no success copy may appear before the saved/completed states.

- [ ] **Step 4: Create `1280×720` mirrors**

Create twelve `Child/1280/<state>` frames from the same components. Adapt spacing and maximum widths; do not merely scale the 1024 frames as flattened artwork.

- [ ] **Step 5: Delete the temporary capture**

After visual comparison, delete only the temporary captured layout node returned in Step 1. Keep all component-built review frames.

- [ ] **Step 6: Validate exact coverage**

Return frame names, dimensions, instance counts and screenshots. Expected: exactly twelve unique states at each viewport, no duplicate names, no horizontal overflow, and no temporary capture node remaining.

---

### Task 5: Build recovery and teacher-help states

**Files:**
- External modify: Figma page `11 Child · Recovery & Teacher Help`
- No repository files modified

**Interfaces:**
- Consumes: teacher-help and child feedback components from Task 3
- Produces: recovery matrix frames and teacher-help modal state frames for both viewports

- [ ] **Step 1: Create child failure matrix**

Create fictional frames for microphone denied, speech failure, network timeout with preserved draft, local-storage failure, empty roster, multiple active conversations, and generic safe recovery. Each frame must show one clear next action and a teacher-help route.

- [ ] **Step 2: Create locked teacher-help matrix**

Create first PIN setup, existing PIN unlock, invalid PIN, authentication unavailable and locked-safe states. Annotate focus entry, Escape behavior and focus restoration.

- [ ] **Step 3: Create unlocked teacher-help matrix**

Create allowed/disabled variants for text submission, draft saving, retrying recovery, retrying microphone, safe ending and immediate relock. Use the same preserved fictional draft across related frames.

- [ ] **Step 4: Validate action availability**

Return frame names and visible/disabled action labels. Expected: unsafe actions are never presented as enabled, every error retains a path to safety, and both viewports use the same action contract.

---

### Task 6: Connect clickable child prototype flows

**Files:**
- External modify: Figma page `12 Child · Prototype Flows`
- No repository files modified

**Interfaces:**
- Consumes: core and recovery frame IDs from Tasks 4–5
- Produces: four named prototype-flow start nodes and transition map

- [ ] **Step 1: Compose the happy-path flow**

Connect `welcome → loading_roster → selecting_child → opening → ready → listening → submitting → speaking → ready`. Use click/keyboard-equivalent annotations and reduced-motion notes; do not use decorative auto-advance where the runtime requires explicit action.

- [ ] **Step 2: Compose retry and preservation flow**

Connect `ready → listening → submitting → submission_failed → submitting → speaking`, preserving the same draft and request-identity annotation.

- [ ] **Step 3: Compose completion flow**

Connect `speaking → saving_conversation → completed → welcome`, with success copy only after the completion frame.

- [ ] **Step 4: Compose teacher-recovery flow**

Connect child recovery to locked teacher help, PIN unlock, safe teacher action, relock and the correct child state.

- [ ] **Step 5: Verify prototype graph**

Return named start nodes, all reactions and unreachable-frame findings. Expected: four starts, no broken target IDs, no state that falsely claims success, and every failure path reaches a safe action.

---

### Task 7: Record code mapping and child-design evidence

**Files:**
- External modify: Figma pages `00 Cover & Handoff` and `90 Code Mapping & Acceptance`
- Create: `docs/figma/prototype-reference.md`
- No product code modified

**Interfaces:**
- Consumes: final Figma file URL, file key, page IDs, component IDs, prototype starts and screenshots
- Produces: reviewed child-design handoff and repository reference for the later teacher plan

- [ ] **Step 1: Create the Figma handoff board**

On `00 Cover & Handoff`, record the approved spec path, tested code HEAD, child coverage, viewport matrix, fictional-data statement, design version time and review status.

- [ ] **Step 2: Create the code mapping board**

On `90 Code Mapping & Acceptance`, map at minimum:

```text
Child state variants -> app/frontend/child/machine.mjs
Visible copy/components -> app/frontend/child/view.mjs
Async/retry/help flow -> app/frontend/child/app.mjs
Speech feedback -> app/frontend/child/speech.mjs
TTS feedback -> app/frontend/child/tts.mjs
Draft/recovery -> app/frontend/child/session-store.mjs
Visual tokens -> app/frontend/child/styles.css
```

- [ ] **Step 3: Write the repository reference**

Create `docs/figma/prototype-reference.md` with exact file URL/key, page/node IDs, four prototype start nodes, two viewport counts, child component/variable summaries, fictional-data declaration, open design questions and review date. Do not call this release evidence or GO.

- [ ] **Step 4: Verify design evidence**

Check the Figma file metadata and screenshots against the reference document. Run `git diff --check` and confirm only `docs/figma/prototype-reference.md` is a new repository path for this task.

- [ ] **Step 5: Commit the child-design reference**

```bash
git add -- docs/figma/prototype-reference.md
git diff --cached --check
git commit -m "docs: record Figma child experience design"
```

Expected: one documentation path in the commit; historical Lovable and Task 9 artifacts remain unchanged.

---

## Plan completion criteria

- One edit-capable Figma Design file with the sixteen approved pages.
- Foundations and reusable child components use variables and variants, not flattened screenshots.
- Exactly twelve child states at both target viewports.
- Recovery and teacher-help matrices preserve safe actions and fictional drafts.
- Four clickable child prototype flows have valid targets.
- Temporary live capture is deleted after comparison.
- `docs/figma/prototype-reference.md` truthfully records the file and child-phase evidence.
- No product code, tests, runner, database, historical Lovable evidence or unrelated dirty path is modified.
