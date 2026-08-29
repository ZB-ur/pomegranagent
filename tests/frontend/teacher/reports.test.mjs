import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createReportRoutes,
  parseGrowth,
  parseHistoryPage,
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
