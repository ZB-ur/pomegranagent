# 幼儿端优先垂直切片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已批准的 Figma 幼儿端十二状态完整落地到原生 HTML/CSS/ES modules，并在不改变 API、状态机和持久化合同的前提下完成安全重锁、主对话区、常驻 PetOrb 与双视口适配。

**Architecture:** 保留 `machine.mjs`、`api.mjs`、`session-store.mjs` 作为行为真源，只重组 `view.mjs` 的语义 DOM、`styles.css` 的视觉投影，并在 `app.mjs` 修复教师帮助关闭路径的服务端重锁边界。所有状态继续由单一 snapshot + `controlsFor(snapshot)` 驱动；PetOrb 只承载当前状态反馈和现有点击式动作，不建立第二套状态。

**Tech Stack:** 原生 HTML、CSS、ES modules、Node `node:test`、pytest、Playwright、FastAPI 隔离测试服务器。

**Spec:** `docs/superpowers/specs/2026-08-30-figma-full-product-interaction-design.md`

## Global Constraints

- 设计真源为 Figma file key `czJ3EIKcXyowhfzBuQt32S`；代表帧 `74:221`（1024×576）和 `74:262`（1280×720）；组件 `70:46` Child/Shell、`553:686` Child/ConversationPanel、`533:435` Child/PetOrb。
- 目标视口仅为 `1024×576` 与 `1280×720`；核心触控目标不小于 `44×44px`；焦点、读屏状态和 `prefers-reduced-motion: reduce` 必须保留。
- 录音交互必须是“点击开始、再次点击结束”，不得改为按住说话。
- 对话对象必须称为“鸭鸭日记本”或“日记本”；不得出现“发给鸭鸭”“鸭鸭正在回答”等把鸭鸭本体当作对话对象的文案。
- 不修改 `app/frontend/child/machine.mjs`、`api.mjs`、`session-store.mjs`、后端 API、数据库模型或 DTO。
- 不实现头像上传、月度多日期批量排班、正式视频/动图交付或教师端页面。
- PetOrb 使用仓库现有、无水印的 `app/frontend/assets/duck-*.png` 作为本批静态 poster；不得提交 Figma 临时媒体 URL 或 Figma 的 generic duck proxy。
- Figma 的 notebook/diary/decor SVG 必须下载为本地精确资产，不手绘替代图标；若下载字节不可验证则停止该资产步骤，不以临时 URL 兜底。
- Teacher Help 在已解锁状态下通过关闭按钮、Escape、明确“立即锁定”、重试麦克风或安全结束离开时，必须先得到 `/api/auth/lock` 返回 `authenticated:false`；锁定失败时弹窗保持打开、敏感输入保持供教师处理、显示固定本地错误且不得泄露服务端原文。
- Teacher Help 在未解锁 PIN 状态关闭时可本地关闭，因为服务端尚未处于已鉴权状态。
- 所有 pytest/browser 命令严格串行；使用项目 `tests/conftest.py` 和隔离浏览器 fixture，不使用旧 `tests/screenshot.py`。
- 不触碰当前主工作区已有 dirty/untracked 路径；所有实施发生在 `codex/p1-child-vertical-slice` 隔离 worktree。

---

### Task 1: Teacher Help fail-closed relock boundary

**Files:**
- Modify: `app/frontend/child/app.mjs:1174-1252`
- Modify: `app/frontend/child/view.mjs:337-659`
- Test: `tests/frontend/child/app-effects.test.mjs`
- Test: `tests/frontend/child/view.test.mjs`
- Test: `tests/browser/test_child_teacher_help.py`

**Interfaces:**
- Consumes: existing `api.teacherLock() -> { configured: boolean, authenticated: boolean }`, `transition(..., {type:'TEACHER_LOCKED'})`, `view.showTeacherHelpError(copy)` and `view.closeTeacherHelp({clearText, restoreFocus})`.
- Produces: internal `performTeacherRelock({ restoreFocus, afterLock }) -> Promise<void>` in `app.mjs`; it is the only path that closes an unlocked Teacher Help dialog.
- Produces: internal view-only `teacherLockPending` flag; it disables every dialog button/input/textarea while a server lock is pending and is cleared only by `showTeacherHelpError`, confirmed `closeTeacherHelp`, or destruction.
- Preserves: the public frozen app surface and the public frozen nine-method view surface exactly as they are now.

- [ ] **Step 1: Write failing view tests for unlocked close/cancel and pending UI**

Add focused cases using the existing fake DOM helpers. The observable contract is that removing the delegation or re-enabling an action during the pending lock makes the test fail.

```js
test('unlocked teacher close and cancel request one relock and wait for confirmed close', () => {
  const calls = [];
  const fake = createFakeDOM();
  const view = createChildView(fake.root, actions({
    onLockTeacherHelp: () => calls.push('lock'),
  }), fake.dom);
  view.render(snapshotFor('recovery', { teacherUnlocked: true }));
  view.openTeacherHelp({ unlocked: true });
  const dialog = byId(fake.root, 'teacher-help-dialog');

  dispatch(dialog, 'click', { target: byId(fake.root, 'teacher-help-close') });
  assert.deepEqual(calls, ['lock']);
  assert.equal(dialog.open, true);
  assert.equal(byId(fake.root, 'teacher-help-close').disabled, true);
  assert.equal(byId(fake.root, 'teacher-text').disabled, true);

  view.showTeacherHelpError('老师帮助暂时不可用，请稍后重试');
  assert.equal(dialog.open, true);
  assert.equal(byId(fake.root, 'teacher-help-close').disabled, false);
});
```

Add a second case proving a locked/PIN dialog still closes locally without calling `onLockTeacherHelp`.

- [ ] **Step 2: Write the failing app-effect and browser relock tests**

Add app-effect cases for `retryMicrophone()` and `endWithTeacher()` using existing recovery fixtures. Each test must prove ordering by keeping `teacherLock` deferred: before resolution, speech/completion has not started and the dialog has not closed; after `{authenticated:false}`, the original action begins once, snapshot `teacherUnlocked` is false, and close occurs once. Add a rejection case proving the action does not start and fixed error copy is shown.

```js
const pendingLock = deferred();
fixture.deps.api.teacherLock = () => {
  fixture.calls.api.push('teacherLock');
  return pendingLock.promise;
};
const work = app.retryMicrophone();
await flushMicrotasks();
assert.equal(fixture.calls.speechStart, 0);
assert.equal(fixture.calls.view.some(([kind]) => kind === 'closeTeacherHelp'), false);
pendingLock.resolve({ configured: true, authenticated: false });
await work;
assert.equal(fixture.calls.speechStart, 1);
assert.equal(app.getSnapshot().teacherUnlocked, false);
```

Update `test_teacher_dialog_traps_focus_blocks_global_space_and_restores_on_escape` to assert auth paths `['status', 'lock']` and wait for dialog close only after lock. Add the same observable assertion for the close button and a failure-safe case that keeps the dialog/text visible while showing fixed local error copy.

- [ ] **Step 3: Run all new Task 1 tests and verify RED**

Run:

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs
node --test --test-concurrency=1 tests/frontend/child/app-effects.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_teacher_help.py
```

Expected: the view/browser dismissal cases fail because current code closes locally without `teacherLock`; the handoff case fails because current `commitTeacherHandoff` starts work before any lock call.

- [ ] **Step 4: Implement the minimal view delegation and pending state**

Keep local close behavior only for `teacherMode === 'locked'`. Route unlocked `close`, native `cancel`, explicit `lock`, `retry-microphone`, and `end-session` through a helper shaped as follows:

```js
function requestTeacherLock(callback) {
  if (teacherLockPending || teacherUI === null) return;
  teacherLockPending = true;
  updateTeacherDialogFromSnapshot();
  try {
    callback();
  } catch {
    teacherLockPending = false;
    updateTeacherDialogFromSnapshot();
  }
}
```

When `teacherLockPending` is true, disable `pin`, `unlockButton`, `text`, all teacher action buttons, and the close button. `showTeacherHelpError` must clear pending before rendering fixed copy. `closeTeacherDialog` must clear pending after confirmed lock.

- [ ] **Step 5: Implement `performTeacherRelock` and route every unlocked close path through it**

The helper must validate the auth response, run `afterLock` only after confirmed server lock, commit `TEACHER_LOCKED`, and close. On rejection or malformed status, call `showTeacherHelpError` and leave the dialog/snapshot unlocked. Explicit `lockTeacherHelp()` passes a no-op `afterLock`; `commitTeacherHandoff()` passes the existing event commit + `startWork` continuation. Do not add retries or another API.

- [ ] **Step 6: Run Task 1 Node and browser tests and verify GREEN**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs tests/frontend/child/app-effects.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_teacher_help.py
```

- [ ] **Step 7: Commit Task 1**

```bash
git add app/frontend/child/app.mjs app/frontend/child/view.mjs tests/frontend/child/app-effects.test.mjs tests/frontend/child/view.test.mjs tests/browser/test_child_teacher_help.py
git commit -m "fix: relock teacher help before leaving child flow"
```

---

### Task 2: Child shell, local design assets, and visual tokens

**Files:**
- Create: `app/frontend/assets/notebook-mark.svg`
- Create: `app/frontend/assets/diary-mark.svg`
- Create: `app/frontend/assets/decor-sage.svg`
- Create: `app/frontend/assets/decor-ochre.svg`
- Modify: `app/frontend/child/view.mjs:118-209`
- Replace: `app/frontend/child/styles.css`
- Test: `tests/test_frontend_foundation.py`
- Test: `tests/frontend/child/view.test.mjs`

**Interfaces:**
- Consumes: the current `element`, `button`, `append`, `replaceChildren`, focus map, and delegated root click seam.
- Produces DOM classes: `.child-shell__header`, `.child-shell__brand`, `.child-shell__content`, `.child-state`, `.child-state__header`, `.child-stage`, while retaining `.child-view`, `#app-title`, `#child-status`, `#teacher-help-button`, and `data-state`.
- Produces CSS tokens: `--child-paper:#fff8e8`, `--child-ink:#24352b`, `--child-action:#2e6f86`, `--child-action-border:#244d5c`, `--child-sage:#e4ead8`, `--child-sage-border:#6b8a5b`, `--child-story:#f7e8be`, `--child-muted:#58635d`, `--child-danger:#9f2d20`.

- [ ] **Step 1: Write failing semantic-shell and local-asset tests**

Extend the existing twelve-state render test with invariant assertions:

```js
assert.ok(find(fake.root, node => node.getAttribute?.('class') === 'child-shell__header'));
assert.ok(find(fake.root, node => node.getAttribute?.('class') === 'child-shell__content'));
assert.ok(find(fake.root, node => node.getAttribute?.('class') === 'child-state'));
assert.equal(byId(fake.root, 'teacher-help-button').parentNode.getAttribute('class'), 'child-shell__header');
assert.equal(byId(fake.root, 'app-title').parentNode.getAttribute('class'), 'child-state__header');
```

Add a foundation test that opens each expected SVG path, asserts a single `<svg` root, and rejects `<script`, event attributes, external URL references, and embedded raster data. The production change that makes it fail is replacing a reviewed local glyph with a remote or executable asset.

- [ ] **Step 2: Run semantic-shell and asset tests and verify RED**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_frontend_foundation.py
```

Expected: the view test fails because the shell regions do not exist; the foundation test fails because the four local SVG files do not exist.

- [ ] **Step 3: Download and verify the exact Figma SVG bytes**

Download the four current design assets from the `74:221` design-context response into their named repository paths. The sources are:

```text
notebook-mark.svg  https://www.figma.com/api/mcp/asset/09188684-8e68-4fba-83b1-e94597d03240.svg
diary-mark.svg     https://www.figma.com/api/mcp/asset/ad8e60b7-3fce-4cd3-8283-c174198b9aa9.svg
decor-sage.svg     https://www.figma.com/api/mcp/asset/440da343-798d-4916-a5b2-097a778a57a9.svg
decor-ochre.svg    https://www.figma.com/api/mcp/asset/e231590a-71d9-47af-952b-1f6a53af34ac.svg
```

Verify each file is SVG text, contains one `<svg` root, contains no `<script`, external URL, event handler, or embedded raster data. Record SHA-256 hashes in the Task 2 report; do not add a source manifest to product code.

- [ ] **Step 4: Build the persistent semantic shell in `render()`**

Use native elements only. The stable hierarchy is:

```html
<section class="child-view child-shell" data-state="...">
  <header class="child-shell__header">
    <div class="child-shell__brand"><img alt=""><span>鸭鸭日记本</span></div>
    <button id="teacher-help-button">请老师帮忙</button>
  </header>
  <div class="child-shell__content">
    <section class="child-state">
      <header class="child-state__header">
        <h1 id="app-title"></h1>
        <p class="child-state__lead"></p>
      </header>
      <div class="child-stage"></div>
      <p id="child-status" role="status"></p>
    </section>
  </div>
</section>
```

The brand image is decorative (`alt=""`); the visible brand text owns the name. Keep `#app-title` as the route/state focus target and preserve the single delegated click listener.

- [ ] **Step 5: Implement the exact two-viewport shell geometry and tokens**

At 1024×576: header `x=40 y=20 w=944 h=64`; content `x=40 y=96 w=944 h=460`; state `x=80 y=128 w=864 h=404` in viewport coordinates. At 1280×720: header `x=40 y=20 w=1200 h=64`; content `x=40 y=96 w=1200 h=604`; state `x=80 y=128 w=1120 h=540`. Use CSS grid/flex for internal relations and media queries only for the compact/wide dimensions; do not scale the entire compact layout.

Use `Noto Sans SC`, `PingFang SC`, `Microsoft YaHei`, sans-serif; title 32/42, body 20/30, label 18/26, caption 14/21. Preserve 4px visible focus ring and reduced-motion override.

- [ ] **Step 6: Run Task 2 tests and verify GREEN**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_frontend_foundation.py
```

- [ ] **Step 7: Commit Task 2**

```bash
git add app/frontend/assets/notebook-mark.svg app/frontend/assets/diary-mark.svg app/frontend/assets/decor-sage.svg app/frontend/assets/decor-ochre.svg app/frontend/child/view.mjs app/frontend/child/styles.css tests/test_frontend_foundation.py tests/frontend/child/view.test.mjs
git commit -m "feat: add child shell and approved visual foundation"
```

---

### Task 3: ConversationPanel and persistent PetOrb across core states

**Files:**
- Modify: `app/frontend/child/view.mjs:86-306,891-938`
- Modify: `app/frontend/child/styles.css`
- Test: `tests/frontend/child/view.test.mjs`
- Test: `tests/browser/test_child_shell.py`

**Interfaces:**
- Produces helpers `conversationPanel(snapshot, transcriptState)` and `petOrb(snapshot, controls)` returning native DOM nodes.
- ConversationPanel retains `role="log"`, `aria-live="polite"`, `aria-relevant="additions text"`, `aria-label="对话记录"`; diary rows remain left-aligned and child rows right-aligned.
- PetOrb owns exactly one existing action button when the state allows it: start/stop, retry, reset, or initial start. Busy states expose no forged action.
- `statusFor(snapshot)` remains the live-region source; visible lead text comes from a local state-presentation mapping and never from server error fields.

- [ ] **Step 1: Write failing component and copy tests**

For all twelve states assert exactly one `.child-pet-orb` and, for conversation states, one `.child-conversation-panel`. Add literal copy assertions:

```js
view.render(snapshotFor('submitting'));
assert.equal(byId(fake.root, 'child-status').textContent, '这句话正在发给鸭鸭日记本');
assert.equal(fake.root.textContent.includes('发给鸭鸭'), false);

view.render(snapshotFor('speaking'));
assert.equal(byId(fake.root, 'child-status').textContent, '鸭鸭日记本正在回答');
assert.equal(fake.root.textContent.includes('鸭鸭正在回答'), false);
```

For ready/listening assert the same PetOrb action node changes label from `开始说话` to `结束说话`, and no `mousedown`, pointer-hold, or press-and-hold contract is introduced.

- [ ] **Step 2: Run view tests and verify RED**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs
```

- [ ] **Step 3: Implement ConversationPanel**

Render a stable panel header (`对话记录` + state pill) and scrollable message list. At compact size the panel is `608×308`, inner width `584`, message row `584×116`, and two complete rows remain visible before scrolling. At wide size it is `760×396`, inner width `728`. Pending draft and send failure are styled rows within the panel, not separate page-level cards.

Use local diary SVG only for diary sender; child sender label is `你` or `childLabel(snapshot.child)`. Continue writing hostile dynamic text via text nodes only.

- [ ] **Step 4: Implement persistent PetOrb state projection**

Map existing local posters without creating media URLs:

```js
const PET_POSTER_BY_STATE = Object.freeze({
  welcome: '/assets/duck-front-512.png',
  loading_roster: '/assets/duck-front-512.png',
  selecting_child: '/assets/duck-side-512.png',
  opening: '/assets/duck-encouraging.png',
  ready: '/assets/duck-front-512.png',
  listening: '/assets/duck-listening.png',
  submitting: '/assets/duck-listening.png',
  speaking: '/assets/duck-encouraging.png',
  submission_failed: '/assets/duck-front-512.png',
  saving_conversation: '/assets/duck-listening.png',
  completed: '/assets/duck-happy.png',
  recovery: '/assets/duck-front-512.png',
});
```

Give the poster informative alt text only when it communicates state; otherwise `alt=""` and use adjacent visible/live text. The visual region and action remain one `.child-pet-orb`, matching the approved desktop-pet model.

- [ ] **Step 5: Write and run the failing browser geometry test**

Add a ready-state test that reads `getBoundingClientRect()` for `.child-shell__header`, `.child-shell__content`, `.child-state`, `.child-conversation-panel`, and `.child-pet-orb`. Assert each expected rectangle with `pytest.approx(..., abs=1)`. Assert panel/orb do not overlap and every listed element is in the initial viewport without `scroll_into_view_if_needed()`.

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_shell.py
```

Expected: the new geometry test fails because the current panel/orb regions and approved dimensions do not exist.

- [ ] **Step 6: Implement exact ready-state stage geometry**

At 1024×576: ConversationPanel viewport bounds `x=80 y=224 w=608 h=308`; PetOrb `x=712 y=224 w=232 h=308`. At 1280×720: ConversationPanel `x=116 y=240 w=760 h=396`; PetOrb `x=900 y=240 w=264 h=396`. Other states reuse the same two-column stage where applicable so entering/leaving a session does not move the persistent IP region unpredictably.

- [ ] **Step 7: Run browser test and verify GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_shell.py
```

- [ ] **Step 8: Run the full Task 3 focused gate**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs tests/frontend/child/machine.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_shell.py
```

- [ ] **Step 9: Commit Task 3**

```bash
git add app/frontend/child/view.mjs app/frontend/child/styles.css tests/frontend/child/view.test.mjs tests/browser/test_child_shell.py
git commit -m "feat: center child conversation around persistent pet orb"
```

---

### Task 4: Roster, failures, recovery, and full P1 acceptance

**Files:**
- Modify: `app/frontend/child/view.mjs:236-306,376-659`
- Modify: `app/frontend/child/styles.css`
- Test: `tests/frontend/child/view.test.mjs`
- Test: `tests/browser/test_child_shell.py`
- Test: `tests/browser/test_child_faults.py`
- Test: `tests/browser/test_child_teacher_help.py`

**Interfaces:**
- Roster cards consume only validated `snapshot.roster`; this batch does not render the unconstrained `avatar` string as an image URL.
- Empty roster, submission failure, and recovery consume fixed local copy only; raw `snapshot.error.message` remains unrendered.
- Teacher Help remains a native `<dialog>` with current focus trap and action IDs; Task 4 changes visual grouping, not its public action contract.

- [ ] **Step 1: Write failing roster, recovery, and initial-viewport tests**

Add assertions that roster buttons contain a local visual fallback and visible child name, while no `<img src>` is derived from `child.avatar`:

```js
const hostile = snapshotFor('selecting_child', {
  roster: [{ id: 7, name: '小雨', nickname: null, avatar: 'javascript:alert(1)' }],
});
view.render(hostile);
const card = byId(fake.root, 'child-card-7');
assert.equal(card.textContent.includes('小雨'), true);
assert.equal(findAll(card, node => node.tagName === 'IMG').length, 0);
```

Assert submission failure renders the preserved draft inside `.child-conversation-panel`, has one retry action when authorized, and never duplicates the draft in a second page-level card. Assert every approved error code still maps to fixed local copy.

Strengthen `test_projection_is_reachable_without_horizontal_or_control_clipping`: do not call `scroll_into_view_if_needed()` before asserting the ready state. In both viewports assert title, ConversationPanel, PetOrb, record action, teacher help, and status are already inside the viewport. Add roster/recovery cases whose visible rectangles do not intersect and whose documents have no horizontal overflow.

- [ ] **Step 2: Run view and browser tests and verify RED**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_shell.py tests/browser/test_child_faults.py
```

Expected: roster fallback and grouped failure assertions fail against current DOM; the no-scroll/overlap assertions fail until compact/wide recovery layout is implemented.

- [ ] **Step 3: Implement roster cards and recovery grouping**

Build child cards with a CSS-only round fallback containing the first visible grapheme of nickname/name, plus the full visible label. Use a responsive two-column grid where two cards fit without overlap; retain native buttons, IDs, `data-child-id`, and delegated selection.

Place empty roster and recovery explanation in the main state column while PetOrb remains at its persistent position. Keep “请老师帮忙” in the shell header as the only teacher-help action; do not duplicate another teacher-help button inside an error card.

- [ ] **Step 4: Restyle the native Teacher Help dialog to the approved child visual system**

Use a bounded, scrollable dialog with clear locked/unlocked sections, fixed error region, 44px controls, visible focus, and no overlap at 1024×576. Preserve all existing IDs, label associations, focus trap, clear-on-confirmed-close behavior, and native Escape cancel handling from Task 1.

- [ ] **Step 5: Run the focused Task 4 tests and verify GREEN**

```bash
node --test --test-concurrency=1 tests/frontend/child/view.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_shell.py tests/browser/test_child_faults.py
```

- [ ] **Step 6: Run the three browser suites and fix only demonstrated failures**

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_child_shell.py tests/browser/test_child_teacher_help.py tests/browser/test_child_faults.py
```

- [ ] **Step 7: Run the full P1 Node gate serially**

```bash
node --test --test-concurrency=1 tests/frontend/shared/api-client.test.mjs tests/frontend/child/*.test.mjs
```

- [ ] **Step 8: Run the foundation and browser P1 gate serially**

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_frontend_foundation.py tests/browser/test_child_shell.py tests/browser/test_child_teacher_help.py tests/browser/test_child_faults.py
```

- [ ] **Step 9: Capture review screenshots outside the repository**

Using the isolated browser fixture or a temporary local server, capture ready, listening, submitting, submission_failed, completed, recovery, and Teacher Help unlocked at both target viewports into this plan's `.superpowers/sdd/...` workspace. Screenshots are review evidence, not committed product files. Confirm no real child data appears.

- [ ] **Step 10: Verify scope and commit Task 4**

Confirm `git diff --name-only` contains only the plan, the listed child production/assets files, and listed tests; confirm `machine.mjs`, `api.mjs`, `session-store.mjs`, backend, teacher frontend, and main-worktree dirty paths are absent.

```bash
git add app/frontend/child/view.mjs app/frontend/child/styles.css tests/frontend/child/view.test.mjs tests/browser/test_child_shell.py tests/browser/test_child_faults.py tests/browser/test_child_teacher_help.py
git commit -m "feat: complete child roster and recovery visual slice"
```

---

## Final branch gate

Run only after all task reviews are clean:

```bash
node --test --test-concurrency=1 tests/frontend/shared/api-client.test.mjs tests/frontend/child/*.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_frontend_foundation.py tests/browser/test_child_shell.py tests/browser/test_child_teacher_help.py tests/browser/test_child_faults.py
git status --short
git diff --check 941c71048b3f04a5b35124610d7420f758c57309..HEAD
```

The branch is ready for user visual review only when the commands above are freshly green, the implementation worktree is clean, and the screenshot matrix shows no overlap or clipping. This P1 result does not change historical Lovable evidence or declare the full product release-ready.
