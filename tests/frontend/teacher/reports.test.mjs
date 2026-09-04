import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildGrowthPresentation,
  buildSearchRequest,
  createReportRoutes,
  parseGrowth,
  parseHistoryPage,
  parseSearchPage,
  reportStatusCopy,
} from '../../../app/frontend/teacher/views/reports.mjs';


const SEARCH_ITEM = Object.freeze({
  id: 42,
  child: Object.freeze({
    id: 7,
    name: '小雨',
    nickname: '雨雨',
    avatar: '/api/media/avatars/123e4567-e89b-12d3-a456-426614174000',
  }),
  date: '2026-08-23',
  completed_at: '2026-08-23T09:00:00Z',
  status: 'ended',
  end_reason: 'max_rounds',
  message_count: 4,
  round: 2,
  analysis_status: 'succeeded',
  review_status: 'confirmed',
  revision: 3,
});


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


test('search parser enforces exact page, canonical avatars, and opaque cursor', () => {
  const page = parseSearchPage({ items: [SEARCH_ITEM], next_cursor: 'Abc_123-x' });
  assert.equal(page.items[0].child.avatar, SEARCH_ITEM.child.avatar);
  assert.equal(page.next_cursor, 'Abc_123-x');
  for (const value of [
    { items: [SEARCH_ITEM], next_before_id: 42 },
    { items: [{ ...SEARCH_ITEM, child: { ...SEARCH_ITEM.child, avatar: 'https://example.test/a.webp' } }], next_cursor: null },
    { items: [{ ...SEARCH_ITEM, child: { ...SEARCH_ITEM.child, avatar: 'data:image/png;base64,AA' } }], next_cursor: null },
    { items: [{ ...SEARCH_ITEM, child: { ...SEARCH_ITEM.child, avatar: '/api/media/avatars/123E4567-e89b-12d3-a456-426614174000' } }], next_cursor: null },
    { items: [SEARCH_ITEM], next_cursor: 'abc=' },
    { items: [SEARCH_ITEM], next_cursor: '' },
    { items: [SEARCH_ITEM], next_cursor: 'x'.repeat(1025) },
    { items: [SEARCH_ITEM], next_cursor: null, extra: true },
  ]) assert.throws(() => parseSearchPage(value), TypeError);
});


test('search parser requires timezone-aware UTC completion timestamps', () => {
  for (const completedAt of [
    '2026-08-23T09:00:00Z',
    '2026-08-23T09:00:00+00:00',
  ]) {
    const page = parseSearchPage({
      items: [{ ...SEARCH_ITEM, completed_at: completedAt }],
      next_cursor: null,
    });
    assert.equal(page.items[0].completed_at, completedAt);
  }

  for (const completedAt of [
    '2026-08-23',
    '2026-08-23T09:00:00',
    '2026-08-23T09:00:00+08:00',
  ]) {
    assert.throws(() => parseSearchPage({
      items: [{ ...SEARCH_ITEM, completed_at: completedAt }],
      next_cursor: null,
    }), TypeError);
  }
});


test('search request builder normalizes an exact private POST snapshot', () => {
  const snapshot = buildSearchRequest({
    child_id: '8',
    date_from: '2026-08-01',
    date_to: '2026-08-31',
    analysis_status: ['failed', 'succeeded'],
    review_status: ['unavailable', 'confirmed'],
    end_reason: ['manual', 'complete'],
    keyword: '  50%_\\ 私密词  ',
    sort: 'completed_asc',
  });
  assert.deepEqual(snapshot, {
    child_id: 8,
    date_from: '2026-08-01',
    date_to: '2026-08-31',
    analysis_status: ['failed', 'succeeded'],
    review_status: ['unavailable', 'confirmed'],
    end_reason: ['manual', 'complete'],
    keyword: '50%_\\ 私密词',
    sort: 'completed_asc',
    limit: 20,
  });
  assert.equal(Object.prototype.hasOwnProperty.call(snapshot, 'cursor'), false);
  assert.deepEqual(buildSearchRequest({
    child_id: '', date_from: '', date_to: '', analysis_status: [], review_status: [],
    end_reason: [], keyword: '   ', sort: 'completed_desc',
  }), {
    child_id: null, date_from: null, date_to: null, analysis_status: [], review_status: [],
    end_reason: [], keyword: null, sort: 'completed_desc', limit: 20,
  });
});


test('search request builder accepts the backend minimum calendar year', () => {
  assert.deepEqual(buildSearchRequest({
    child_id: '',
    date_from: '0001-01-01',
    date_to: '0001-12-31',
    analysis_status: [],
    review_status: [],
    end_reason: [],
    keyword: '',
    sort: 'completed_desc',
  }), {
    child_id: null,
    date_from: '0001-01-01',
    date_to: '0001-12-31',
    analysis_status: [],
    review_status: [],
    end_reason: [],
    keyword: null,
    sort: 'completed_desc',
    limit: 20,
  });
});


test('search request builder measures keyword length in Unicode code points', () => {
  const base = {
    child_id: '',
    date_from: '',
    date_to: '',
    analysis_status: [],
    review_status: [],
    end_reason: [],
    sort: 'completed_desc',
  };
  const accepted = '🦆'.repeat(100);
  assert.equal(buildSearchRequest({ ...base, keyword: accepted }).keyword, accepted);
  assert.throws(() => buildSearchRequest({ ...base, keyword: `${accepted}🦆` }), TypeError);
});


test('search request builder blocks invalid dates, filters, and hostile records', () => {
  const base = {
    child_id: '', date_from: '', date_to: '', analysis_status: [], review_status: [],
    end_reason: [], keyword: '', sort: 'completed_desc',
  };
  for (const value of [
    { ...base, child_id: '0' },
    { ...base, date_from: '0000-01-01' },
    { ...base, date_from: '2026-02-30' },
    { ...base, date_from: '2026-09-02', date_to: '2026-09-01' },
    { ...base, date_from: '2025-09-01', date_to: '2026-09-02' },
    { ...base, analysis_status: ['failed', 'failed'] },
    { ...base, review_status: ['unknown'] },
    { ...base, end_reason: ['other'] },
    { ...base, keyword: 'x'.repeat(101) },
    { ...base, sort: 'newest' },
    { ...base, extra: true },
    Object.defineProperty({ ...base }, 'keyword', { enumerable: true, get() { throw new Error('secret'); } }),
  ]) assert.throws(() => buildSearchRequest(value), TypeError);
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
