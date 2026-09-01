# Teacher Reports Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved teacher Growth and Search surfaces at 1024×768 and 1440×900 as one independently reviewable, reversible UI-only slice.

**Architecture:** Keep both routes in `reports.mjs`, preserving strict DTO parsing, hash navigation, abort cleanup, and sequence isolation. Add pure per-dimension Growth summaries and exhaustive Chinese status labels, then render semantic native DOM/SVG with route-scoped CSS and focused Node/Playwright coverage.

**Tech Stack:** Native HTML DOM APIs, CSS, ES modules, SVG, Node `node:test`, pytest, Playwright, FastAPI isolated browser fixture.

**Spec:** `docs/superpowers/specs/2026-08-30-figma-full-product-interaction-design.md`

## Global Constraints

- Baseline: exact P4 commit `dbfccea158d8d59462bc84bb063c48163837afb4`, branch `codex/p5-teacher-reports-slice`; do not merge or advance `master`.
- Figma truth: Growth `120:2`, `120:154`, `120:343`; Search `122:2`, `122:161`, `122:361`; file `czJ3EIKcXyowhfzBuQt32S`.
- Production scope: only `app/frontend/teacher/views/reports.mjs` and report-scoped rules in `app/frontend/teacher/styles.css`.
- Preserve existing APIs/DTOs, `#growth?child_id=...`, `#search?child_id=...`, `#review?conversation_id=...`, `AbortController`, cleanup, and sequence-token stale-response isolation.
- No backend/schema/database/dependency changes; no chart library; no other routes.
- Growth y-axis is fixed 1–5. Date and numeric score must accompany every point. Summaries are per dimension only: never combine dimensions/children, rank children, or infer improvement, regression, personality, or diagnosis.
- Search is limited to child selection, `查看历史`, and existing `limit=20` plus `before_id` pagination. No keyword/date/sort controls.
- Search shows Chinese status labels. Append failure retains old rows/cursor, re-enables load-more, and recovery appends; null cursor removes load-more.
- Cover loading, unselected, invalid-child, populated, empty, failure, retry, append-loading/failure/recovery, and last page.
- At 1024×768 and 1440×900: no overlap/horizontal document overflow; visible buttons, links, selects are at least 44×44; failures are alerts; loading uses `aria-busy`; populated success is not a live region; no automatic chart/list animation.
- Server data is inserted with safe nodes/`textContent`, never `innerHTML`.
- Run Node/browser commands serially using `/Users/lddmay/AiCoding/pomegranagent/.venv` and the isolated `teacher_browser` fixture.

Preflight:

```bash
test "$(git rev-parse HEAD)" = "dbfccea158d8d59462bc84bb063c48163837afb4"
test "$(git branch --show-current)" = "codex/p5-teacher-reports-slice"
git status --short
```

The first two commands must exit 0; before production edits, status may show only this plan.

---

### Task 1: Growth surface and state matrix

**Files:**
- Modify: `app/frontend/teacher/views/reports.mjs:1-238`
- Modify: `app/frontend/teacher/styles.css:706-990`
- Test: `tests/frontend/teacher/reports.test.mjs`
- Test: `tests/browser/test_teacher_reports.py`

**Interfaces:**
- Consumes: existing `parseGrowth`, `scopeFor`, `navigate`, children/Growth DTOs.
- Produces: `buildGrowthPresentation(result) -> { dates, hasData, series }`; each series has `key`, `name`, sorted `points`, `latest`, `recentMean`, `differenceFromEarliest`, `chronologicalText`.
- Produces: `selectorFor(children, selectedId, labelText, emptyLabel, onChange) -> { field, select }` and `setReportStatus(node, text, role)`.
- Produces hooks `.growth-view`, `.report-hero`, `.growth-summary-stack`, `.growth-summary-grid`, `.growth-workspace`, `.report-chart`, `.growth-data-panel`.

- [ ] **Step 1: Write failing presentation tests**

```js
test('growth presentation sorts and summarizes each dimension independently', () => {
  const parsed = parseGrowth({
    child_id: 7,
    dimensions: [
      { key: 'language', name: '语言表达能力', points: [
        { date: '2026-08-06', score: 5 }, { date: '2026-08-01', score: 1 },
        { date: '2026-08-02', score: 2 }, { date: '2026-08-03', score: 3 },
        { date: '2026-08-04', score: 4 }, { date: '2026-08-05', score: 5 },
      ] },
      { key: 'empathy', name: '同理心', points: [{ date: '2026-08-06', score: 2 }] },
    ],
  }, 7);
  const result = buildGrowthPresentation(parsed);
  assert.deepEqual(result.dates, ['2026-08-01', '2026-08-02', '2026-08-03', '2026-08-04', '2026-08-05', '2026-08-06']);
  assert.deepEqual(result.series[0].latest, { date: '2026-08-06', score: 5 });
  assert.equal(result.series[0].recentMean, 3.8);
  assert.equal(result.series[0].differenceFromEarliest, 4);
  assert.equal(result.series[1].recentMean, 2);
});

test('growth presentation reports an all-empty DTO without chart data', () => {
  const parsed = parseGrowth({ child_id: 7, dimensions: [{ key: 'language', name: '语言表达能力', points: [] }] }, 7);
  assert.equal(buildGrowthPresentation(parsed).hasData, false);
  assert.equal(buildGrowthPresentation(parsed).series[0].chronologicalText, '暂无已确认数据');
});
```

- [ ] **Step 2: Run RED**

```bash
node --test --test-concurrency=1 tests/frontend/teacher/reports.test.mjs
```

Expected: FAIL because `buildGrowthPresentation` is absent.

- [ ] **Step 3: Implement the pure helper**

```js
export function buildGrowthPresentation(result) {
  const series = result.dimensions.map(dimension => {
    const points = [...dimension.points].sort((left, right) => left.date.localeCompare(right.date));
    const latest = points.at(-1) || null;
    const recent = points.slice(-5);
    return {
      ...dimension, points, latest,
      recentMean: recent.length ? Number((recent.reduce((sum, point) => sum + point.score, 0) / recent.length).toFixed(1)) : null,
      differenceFromEarliest: latest ? latest.score - points[0].score : null,
      chronologicalText: points.length ? points.map(point => `${point.date} ${point.score} 分`).join('；') : '暂无已确认数据',
    };
  });
  const dates = [...new Set(series.flatMap(item => item.points.map(point => point.date)))].sort();
  return { dates, hasData: series.some(item => item.points.length), series };
}
```

- [ ] **Step 4: Write failing browser contracts**

In `test_teacher_reports.py`, preserve current deep-link, hostile-text, retry, and late-response tests; add assertions at both `VIEWPORTS` for:

```python
assert page.get_by_text("看见变化，不替孩子下结论", exact=True).count() == 1
assert page.get_by_text("最近 5 次均值", exact=True).count() == 1
assert page.get_by_text("与最早记录差值", exact=True).count() == 1
assert page.locator(".report-chart [data-axis-score]").evaluate_all("nodes => nodes.map(node => node.textContent)") == ["5", "4", "3", "2", "1"]
assert page.get_by_text("2026-08-06 5 分", exact=False).count() >= 1
assert page.locator("#main script").count() == 0
assert page.locator(".growth-view").get_attribute("aria-busy") is None
assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
assert page.locator("#main button:visible, #main a:visible, #main select:visible").evaluate_all("nodes => nodes.every(node => { const r=node.getBoundingClientRect(); return r.width>=44 && r.height>=44; })")
```

Use six points `[1,2,3,4,5,5]` to assert mean `3.8`, latest date/score, and difference `+4`. Assert chart/data-panel are side-by-side at 1440 and stacked at 1024 using their bounding boxes.

Add exact state cases:

- `#growth`: first option is `请选择幼儿`, visible unselected copy has no live role, no SVG/API Growth call.
- `#growth?child_id=999`: alert copy `所选幼儿不存在，请重新选择。`, selector focused, no Growth call.
- held children/Growth request: `.growth-view[aria-busy=true]` and polite loading copy; busy removed after settlement.
- empty dimensions: `暂无已确认的成长数据` with `role=status`, no SVG.
- initial failure: fixed local copy, no raw server text, focused `重试成长数据`; recovery renders data/empty.

- [ ] **Step 5: Run browser RED**

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_teacher_reports.py -k 'growth'
```

Expected: FAIL on absent hero/metrics/axis/state hooks, old Growth empty option, focus, and responsive breakpoint.

- [ ] **Step 6: Implement Growth DOM/state behavior**

Add `setReportStatus`; when `role === null`, remove `role` and `aria-live`. Change `selectorFor` to return its field/select and accept empty-label copy. Render, in order: hero (`能力成长曲线`, `看见变化，不替孩子下结论`, factual fixed-scale helper, selector), status, per-dimension summary cards, Growth workspace.

For each non-empty dimension show `最新评分`, `最近 5 次均值`, `与最早记录差值`; positive difference is `+N`, hint is `仅表示数值差，不代表结论`. Render no aggregate.

Create SVG only when data exists: 760×320 viewBox, y labels 5→1, union-date x positions, legend swatch+name, and point `<title>` `${series.name}，${date}，${score} 分`. Add SVG title/description plus visible `数据点说明` with chronological text. No animation/library.

Set busy on both loading phases. Unselected is visible/non-live; invalid child alerts/focuses select; failure alerts/focuses retry; populated success clears live status; empty is polite. Keep scope/token checks around every mutation.

- [ ] **Step 7: Implement responsive Growth CSS**

```css
.reports-view { display:grid; gap:16px; min-width:0; }
.report-hero { display:grid; gap:20px; grid-template-columns:minmax(0,1fr) minmax(220px,320px); }
.growth-summary-grid { display:grid; gap:12px; grid-template-columns:repeat(3,minmax(0,1fr)); }
.growth-workspace { display:grid; gap:16px; grid-template-columns:minmax(0,1fr); min-width:0; }
.report-chart svg { display:block; height:auto; max-width:100%; width:100%; }
@media (min-width:1280px) { .growth-workspace { grid-template-columns:minmax(0,2fr) minmax(280px,1fr); } }
@media (max-width:1024px) { .reports-view { gap:12px; } .report-hero { grid-template-columns:minmax(0,1fr); } }
```

Remove old SVG `min-width:620px`; wrap long names; keep grid children `min-width:0`; controls ≥44×44.

- [ ] **Step 8: Run GREEN and commit**

```bash
node --test --test-concurrency=1 tests/frontend/teacher/reports.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_teacher_reports.py -k 'growth'
git add app/frontend/teacher/views/reports.mjs app/frontend/teacher/styles.css tests/frontend/teacher/reports.test.mjs tests/browser/test_teacher_reports.py
git commit -m "feat: implement teacher growth report surface"
```

---

### Task 2: Search surface and resilient pagination

**Files:**
- Modify: `app/frontend/teacher/views/reports.mjs:76-329`
- Modify: `app/frontend/teacher/styles.css:706-990`
- Test: `tests/frontend/teacher/reports.test.mjs`
- Test: `tests/browser/test_teacher_reports.py`

**Interfaces:**
- Consumes: `parseHistoryPage`, `scopeFor`, Task 1 selector/status helpers, existing history API.
- Produces: `reportStatusCopy(kind,value)`: analysis `pending/processing/succeeded/failed` → `等待分析/分析中/分析完成/分析失败`; review `pending/draft/confirmed/unavailable` → `等待审阅/审阅草稿/审阅完成/暂不可审阅`; unknown pair throws `TypeError`.
- Produces local `nextBeforeId`, `loadedPageCount`, `renderedItemCount`, `loadingMore`, mutated only after current parsed success.
- Produces Search hero/filter/results/row/status/pagination hooks.

- [ ] **Step 1: Write failing Node localization test and browser contracts**

```js
test('report status copy localizes every canonical history enum', () => {
  assert.deepEqual(['pending','processing','succeeded','failed'].map(value => reportStatusCopy('analysis', value)), ['等待分析','分析中','分析完成','分析失败']);
  assert.deepEqual(['pending','draft','confirmed','unavailable'].map(value => reportStatusCopy('review', value)), ['等待审阅','审阅草稿','审阅完成','暂不可审阅']);
  assert.throws(() => reportStatusCopy('analysis', 'unknown'), TypeError);
});
```

Update populated browser coverage: select child, click `查看历史`, wait for canonical hash, then assert hero `查找历史日记`, helper `不含关键词、日期范围或排序`, row `会话 #42`, date, rounds, Chinese analysis/review labels, no raw enums, `第 1 页`, `已显示 1 条 · 还有更多`, and link accessible name `打开会话 #42 的审阅` with exact review hash.

Add append failure/recovery with responses: item 42/cursor 42; 503 raw body; item 41/null cursor. Assert item 42 stays, raw body is hidden, button is re-enabled/focused, retry sends identical `limit=20&child_id=8&before_id=42`, item 41 appends, two rows remain, load-more disappears.

Add state assertions: held first page exposes busy/loading; invalid child alerts/focuses select and makes no history request; initial failure focuses retry and recovery renders empty/results; empty is polite `暂无历史记录`.

- [ ] **Step 2: Run RED**

```bash
node --test --test-concurrency=1 tests/frontend/teacher/reports.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_teacher_reports.py -k 'history or search'
```

Expected: missing localization helper, hero/form/metadata, and retained-results recovery cause failures.

- [ ] **Step 3: Implement localization and Search form**

```js
const REPORT_STATUS_COPY = Object.freeze({
  analysis: Object.freeze({ pending:'等待分析', processing:'分析中', succeeded:'分析完成', failed:'分析失败' }),
  review: Object.freeze({ pending:'等待审阅', draft:'审阅草稿', confirmed:'审阅完成', unavailable:'暂不可审阅' }),
});
export function reportStatusCopy(kind, value) {
  const table = REPORT_STATUS_COPY[kind];
  if (!table || !Object.prototype.hasOwnProperty.call(table, value)) throw invalid();
  return table[value];
}
```

Render hero `明细检索`/`查找历史日记` and exact scope helper. Form contains only selector (`全部幼儿`) and `查看历史`; select change does not navigate. Submit navigates to selected child hash or `#search`; router cleanup owns the transition.

- [ ] **Step 4: Implement rows/cursor state**

Each row safely renders ID, child, ISO date, rounds, two Chinese text chips, and:

```js
h('a', { class:'report-review-link', href:`#review?conversation_id=${item.id}`, 'aria-label':`打开会话 #${item.id} 的审阅`, text:'打开审阅 →' })
```

Initial success replaces rows and sets page/count. Append success appends then commits counters/cursor. Non-null cursor shows `已显示 N 条 · 还有更多`; null shows `已显示 N 条 · 已全部加载` and removes load-more.

Append start retains rows, disables button, announces loading, sets busy. Failure retains rows/cursor/count, alerts `更多历史记录加载失败，已保留当前结果。请重试。`, restores/enables/focuses button, removes busy. Retry uses same cursor; recovery appends and clears live status. Initial populated success is quiet; empty is polite; invalid/failure focus recovery controls. Preserve scope/token guards.

- [ ] **Step 5: Implement responsive Search CSS**

```css
.search-filter { align-items:end; display:grid; gap:12px; grid-template-columns:minmax(0,1fr) auto; }
.report-history-row { align-items:center; display:grid; gap:16px; grid-template-columns:minmax(0,1fr) auto auto; min-width:0; }
.report-history-statuses { display:flex; flex-wrap:wrap; gap:8px; }
.report-status-tag { align-items:center; border-radius:999px; display:inline-flex; min-height:30px; padding:4px 10px; }
.report-review-link,.report-load-more,.search-filter button { min-height:44px; min-width:44px; }
@media (max-width:1024px) { .report-history-row { grid-template-columns:minmax(0,1fr) auto; } .report-review-link { grid-column:1/-1; width:100%; } }
```

Use existing teacher status colors with text labels, `min-width:0`, wrapping, no fixed overflow width, no animation.

- [ ] **Step 6: Run GREEN and commit**

```bash
node --test --test-concurrency=1 tests/frontend/teacher/reports.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q tests/browser/test_teacher_reports.py -k 'history or search'
git add app/frontend/teacher/views/reports.mjs app/frontend/teacher/styles.css tests/frontend/teacher/reports.test.mjs tests/browser/test_teacher_reports.py
git commit -m "feat: implement teacher history search surface"
```

---

### Task 3: Final verification and reversible handoff

**Files:**
- Commit this plan if not already committed.
- Modify tests only for proven contract violations; never weaken existing assertions.

- [ ] **Step 1: Verify scope and ancestry**

```bash
git merge-base --is-ancestor dbfccea158d8d59462bc84bb063c48163837afb4 HEAD
git diff --name-status dbfccea158d8d59462bc84bb063c48163837afb4...HEAD
git status --short
```

Expected: only `reports.mjs`, teacher `styles.css`, both Reports tests, and this plan.

- [ ] **Step 2: Run release gates serially**

```bash
node --test --test-concurrency=1 tests/frontend/shared/api-client.test.mjs tests/frontend/teacher/*.test.mjs
PYTHONDONTWRITEBYTECODE=1 /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/browser/test_teacher_reports.py \
  tests/browser/test_teacher_routing.py \
  tests/browser/test_teacher_accessibility.py \
  tests/browser/test_release_viewports.py
```

Expected: all pass; do not combine `tests/e2e.py` or `tests/test_api.py` with other suites.

- [ ] **Step 3: Visual/state review against all six Figma nodes**

At both viewports verify hero hierarchy, Growth 1–5/date-score/factual per-dimension summaries/no empty SVG, Search localized rows/review hashes/page-count/retained append recovery, all state roles/focus, no overlap/clipping/overflow/undersized target/automatic animation.

- [ ] **Step 4: Independent review and remediation**

Reject on backend/API/DTO drift, unsafe DOM, stale mutation, cross-dimension aggregation/narrative inference, raw enum, lost cursor/rows, broken review hash, missing state/focus/live semantics, viewport regression, or unrelated file. Fix concrete findings, rerun the narrow test, then rerun Step 2.

- [ ] **Step 5: Commit plan if needed and prove clean**

```bash
git status --short docs/superpowers/plans/2026-09-01-teacher-reports-vertical-slice.md
git add docs/superpowers/plans/2026-09-01-teacher-reports-vertical-slice.md
git diff --cached --check
git commit -m "docs: record teacher reports vertical slice plan"
git status --short
```

If the plan is already committed, skip the empty commit and run final status only. Expected final status: empty.

- [ ] **Step 6: Hand off without merge/push**

Report branch, exact HEAD, P4 parent, changed files, test totals, review verdict, and routes `/teacher.html#growth`, `/teacher.html#growth?child_id=7`, `/teacher.html#search`, `/teacher.html#search?child_id=7`. State that `master` was not advanced and rollback is dropping P5 or reverting only its commits after later merge.

## Expected Change Size

- Production: 2 files, approximately 280–480 changed lines; no backend/schema/DTO/dependency/database change.
- Tests: 2 files, approximately 180–320 changed lines.
- Plan: 1 file.
- Risk: medium in shared `reports.mjs` and report-scoped CSS; low in persistence/API behavior.
