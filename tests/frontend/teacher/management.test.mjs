import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createManagementRoutes,
  parseChildren,
  parseDucks,
  parseRosterRows,
  validateArchive,
  validateChildAck,
  validateDeactivationAck,
  validateDuckAck,
  validateDailyRosterAck,
  validateAutoRosterAck,
} from '../../../app/frontend/teacher/views/management.mjs';


const child = {
  id: 7, name: '小雨', nickname: '雨雨', avatar: null, active: true,
  deactivated_at: null, future_roster_entries: 2, has_active_conversation: false,
};
const duck = {
  id: 8, name: '小黄', avatar: null, status: '健康', note: null, active: true,
  deactivated_at: null, historical_feeding_log_count: 3,
};


test('management dependencies are exact own data and trap safe', () => {
  const base = {
    request() {},
    document: { createElement() {} },
    createAbortController() { return new AbortController(); },
    createRequestId() { return 'c30a6409-58b8-48f0-96f0-8ff679bebed7'; },
  };
  assert.equal(typeof createManagementRoutes(base).children, 'function');
  for (const bad of [
    { ...base, extra: true },
    Object.defineProperty({ ...base }, 'request', { get() { throw new Error('secret'); } }),
    new Proxy(base, { ownKeys() { throw new Error('secret'); } }),
  ]) assert.throws(() => createManagementRoutes(bad), TypeError);
  assert.throws(() => createManagementRoutes({ ...base, createRequestId: 'uuid' }), TypeError);
});


test('enriched child and duck lists reject extra malformed or accessor data', () => {
  assert.deepEqual(parseChildren([child]), [child]);
  assert.deepEqual(parseDucks([duck]), [duck]);
  for (const value of [
    [{ ...child, extra: true }],
    [{ ...child, id: 0 }],
    [child, { ...child, name: '重复幼儿' }],
    [Object.defineProperty({ ...child }, 'name', { get() { throw new Error('secret'); } })],
  ]) assert.throws(() => parseChildren(value), TypeError);
  for (const value of [
    [{ ...duck, active: 'yes' }],
    [{ ...duck, historical_feeding_log_count: -1 }],
    [duck, { ...duck, name: '重复小鸭' }],
    new Proxy([duck], { getOwnPropertyDescriptor() { throw new Error('secret'); } }),
  ]) assert.throws(() => parseDucks(value), TypeError);
});


test('create and edit acknowledgements must match normalized submitted identity', () => {
  assert.deepEqual(validateChildAck(
    { id: 7, name: '小雨', nickname: null, avatar: 'rain.png', active: true },
    { expectedId: 7, name: '小雨', nickname: null, avatar: 'rain.png', active: true },
  ), { id: 7, name: '小雨', nickname: null, avatar: 'rain.png', active: true });
  assert.deepEqual(validateDuckAck(
    { id: 8, name: '小黄', avatar: null, status: '健康', note: null },
    { expectedId: 8, name: '小黄', avatar: null, status: '健康', note: null },
  ).id, 8);
  assert.throws(() => validateChildAck(
    { id: 7, name: '别人', nickname: null, avatar: 'rain.png', active: true },
    { expectedId: 7, name: '小雨', nickname: null, avatar: 'rain.png', active: true },
  ), TypeError);
  assert.throws(() => validateChildAck(
    { id: 7, name: '小雨', nickname: null, avatar: 'rain.png', active: false },
    { expectedId: 7, name: '小雨', nickname: null, avatar: 'rain.png', active: true },
  ), TypeError);
  assert.throws(() => validateDuckAck(
    { id: 8, name: '小黄', avatar: null, status: '健康', note: null, extra: true },
    { expectedId: 8, name: '小黄', avatar: null, status: '健康', note: null },
  ), TypeError);
});


test('deactivation and archive acknowledgements are strict and matching', () => {
  const stopped = {
    id: 7, kind: 'child', name: '小雨', active: false,
    deactivated_at: '2026-08-29T01:00:00Z', affected_future_roster_entries: 2,
    changed: true,
  };
  assert.deepEqual(validateDeactivationAck(stopped, {
    id: 7, kind: 'child', name: '小雨', active: false,
  }), stopped);
  assert.deepEqual(validateArchive({ duck_id: 8, summary: null }, 8), { duck_id: 8, summary: null });
  assert.equal(validateArchive({ duck_id: 8, summary: '<img onerror=secret>' }, 8).summary, '<img onerror=secret>');
  assert.throws(() => validateDeactivationAck({ ...stopped, active: true }, {
    id: 7, kind: 'child', name: '小雨', active: false,
  }), TypeError);
  assert.throws(() => validateArchive({ duck_id: 9, summary: 'secret' }, 8), TypeError);
  assert.throws(() => validateArchive({ duck_id: 8, summary: 'x'.repeat(20_001) }, 8), TypeError);
});


test('roster rows and both idempotent acknowledgements are exact', () => {
  assert.deepEqual(parseRosterRows([
    { id: 1, cycle: '2026-W34', date: '2026-08-29', child_id: 7 },
  ])[0].child_id, 7);
  assert.throws(() => parseRosterRows([
    { id: 1, cycle: '', date: '2026-02-30', child_id: 7 },
  ]), TypeError);
  const dailyExpected = {
    requestId: 'c30a6409-58b8-48f0-96f0-8ff679bebed7',
    date: '2026-08-29', cycle: '2026-W34', childIds: [7, 9],
  };
  assert.equal(validateDailyRosterAck({
    request_id: dailyExpected.requestId, date: dailyExpected.date,
    cycle: dailyExpected.cycle, child_ids: [7, 9], replayed: true,
  }, dailyExpected).replayed, true);
  assert.throws(() => validateDailyRosterAck({
    request_id: dailyExpected.requestId, date: dailyExpected.date,
    cycle: dailyExpected.cycle, child_ids: [9, 7], replayed: false,
  }, dailyExpected), TypeError);
  const autoExpected = {
    requestId: dailyExpected.requestId,
    startDate: '2026-08-31', days: 2,
    activeChildIds: [7, 8, 9, 10],
  };
  assert.equal(validateAutoRosterAck({
    request_id: autoExpected.requestId,
    schedule: [
      { date: '2026-08-31', child_ids: [7, 9] },
      { date: '2026-09-01', child_ids: [8, 10] },
    ],
    replayed: false,
  }, autoExpected).schedule.length, 2);
  assert.throws(() => validateAutoRosterAck({
    request_id: autoExpected.requestId,
    schedule: [{ date: '2026-08-30', child_ids: [7, 9] }],
    replayed: false,
  }, autoExpected), TypeError);
  for (const schedule of [
    [{ date: '2026-08-31', child_ids: [7, 9] }],
    [
      { date: '2026-08-31', child_ids: [7, 7] },
      { date: '2026-09-01', child_ids: [8, 10] },
    ],
    [
      { date: '2026-08-31', child_ids: [7, 99] },
      { date: '2026-09-01', child_ids: [8, 10] },
    ],
    [
      { date: '2026-08-31', child_ids: [7, 9] },
      { date: '2026-09-02', child_ids: [8, 10] },
    ],
  ]) assert.throws(() => validateAutoRosterAck({
    request_id: autoExpected.requestId,
    schedule,
    replayed: false,
  }, autoExpected), TypeError);
});
