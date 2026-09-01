import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildGrowthPresentation,
  createReportRoutes,
  parseGrowth,
  parseHistoryPage,
  reportStatusCopy,
} from '../../../app/frontend/teacher/views/reports.mjs';


test('report dependencies are exact own data and trap safe', () => {
  const base = {
    request() {},
    document: { createElement() {}, createElementNS() {} },
    createAbortController() { return new AbortController(); },
    navigate() {},
  };
  const routes = createReportRoutes(base);
  assert.equal(typeof routes.growth, 'function');
  assert.equal(typeof routes.search, 'function');
  assert.throws(() => createReportRoutes({ ...base, extra: true }), TypeError);
  assert.throws(() => createReportRoutes(
    Object.defineProperty({ ...base }, 'navigate', { get() { throw new Error('secret'); } }),
  ), TypeError);
});


test('growth parser accepts only matching strict nested DTO', () => {
  const result = parseGrowth({
    child_id: 7,
    dimensions: [{
      key: 'language', name: '语言表达',
      points: [{ date: '2026-08-23', score: 4 }],
    }],
  }, 7);
  assert.equal(result.dimensions[0].points[0].score, 4);
  for (const value of [
    { child_id: 8, dimensions: [] },
    { child_id: 7, dimensions: [{ key: '', name: '语言', points: [] }] },
    { child_id: 7, dimensions: [{ key: 'x', name: '语言', points: [{ date: 'bad', score: 4 }] }] },
    { child_id: 7, dimensions: [], extra: true },
  ]) assert.throws(() => parseGrowth(value, 7), TypeError);
});


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


test('history parser enforces exact page and canonical item union', () => {
  const item = {
    id: 42,
    child: { id: 7, name: '小雨', nickname: '雨雨', avatar: null },
    date: '2026-08-23', completed_at: '2026-08-23T09:00:00Z',
    status: 'ended', end_reason: 'max_rounds', message_count: 4, round: 2,
    analysis_status: 'succeeded', review_status: 'confirmed', revision: 3,
  };
  const page = parseHistoryPage({ items: [item], next_before_id: 42 });
  assert.equal(page.items[0].id, 42);
  for (const value of [
    { items: [{ ...item, status: 'active' }], next_before_id: null },
    { items: [{ ...item, analysis_status: 'mystery' }], next_before_id: null },
    { items: [item], next_before_id: 41 },
    { items: [item], next_before_id: 43 },
    { items: [item], next_before_id: null, extra: true },
  ]) assert.throws(() => parseHistoryPage(value), TypeError);
});


test('report status copy accepts only own canonical string kinds and values', () => {
  assert.deepEqual(['pending','processing','succeeded','failed'].map(value => reportStatusCopy('analysis', value)), ['等待分析','分析中','分析完成','分析失败']);
  assert.deepEqual(['pending','draft','confirmed','unavailable'].map(value => reportStatusCopy('review', value)), ['等待审阅','审阅草稿','审阅完成','暂不可审阅']);
  assert.throws(() => reportStatusCopy('analysis', 'unknown'), TypeError);
  for (const [kind, value] of [
    ['toString', 'length'],
    ['constructor', 'name'],
    ['__proto__', 'toString'],
    [new String('analysis'), 'pending'],
  ]) assert.throws(() => reportStatusCopy(kind, value), TypeError);
});
