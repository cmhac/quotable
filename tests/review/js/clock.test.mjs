import assert from "node:assert/strict";
import { test } from "node:test";

import { clock, makeTimer, progressLine, roughly } from "../../../quotable/review/static/clock.js";

const fake = () => {
  const t = { at: 0 };
  return { t, now: () => t.at * 1000 };
};

test("a clock shows minutes and seconds, hours when needed, and -- for no time", () => {
  assert.equal(clock(0), "0:00");
  assert.equal(clock(75.9), "1:15");
  assert.equal(clock(3725), "1:02:05");
  assert.equal(clock(null), "--");
  assert.equal(clock(undefined), "--");
  assert.equal(roughly(29), "0m");
  assert.equal(roughly(150), "3m");
  assert.equal(roughly(3 * 3600 + 120), "3h 2m");
  assert.equal(roughly(-50), "0m");
});

test("the timer counts only while it runs and keeps the time when paused", () => {
  const { t, now } = fake();
  const timer = makeTimer(now);
  timer.run(true);
  t.at = 10;
  assert.equal(timer.elapsed(), 10);
  assert.equal(timer.pause(), true);
  t.at = 100;
  assert.equal(timer.elapsed(), 10);
  assert.equal(timer.pause(), false); // already paused: nothing to save
  timer.run(true);
  t.at = 105;
  assert.equal(timer.elapsed(), 15);
});

test("a page that may not be timed does not start", () => {
  const { t, now } = fake();
  const timer = makeTimer(now);
  timer.run(false); // done page, hidden tab or a window not in front
  t.at = 50;
  assert.equal(timer.elapsed(), 0);
  assert.equal(timer.running, false);
});

test("a page finished before timing shows null and is never started", () => {
  const { t, now } = fake();
  const timer = makeTimer(now);
  timer.set(null);
  timer.run(true);
  t.at = 30;
  assert.equal(timer.elapsed(), null);
  assert.equal(timer.running, false);
});

test("stored seconds are resumed and reset sets the time back to zero", () => {
  const { t, now } = fake();
  const timer = makeTimer(now);
  timer.set(40);
  timer.run(true);
  t.at = 5;
  assert.equal(timer.elapsed(), 45);
  timer.reset();
  assert.equal(timer.elapsed(), 0);
  assert.equal(timer.running, false);
});

test("before any timed page is done the line promises an estimate", () => {
  const line = progressLine([{ done: false }, { done: true, seconds: null }]);
  assert.equal(line.text, "1 of 2 pages done · time estimate after the first timed page is done");
  assert.equal(line.fraction, 0.5);
});

test("time left is the pages not done times the mean, less the open page's time", () => {
  const records = [
    { done: true, seconds: 120 },
    { done: true, seconds: 180 },
    { done: true, seconds: null }, // not timed: left out of the mean
    { done: false },
    { done: false },
  ];
  const line = progressLine(records, { notDone: true, elapsed: 60 });
  // mean 150 s; 2 pages left = 300 s, less 60 s used = 240 s = 4m
  assert.equal(line.text, "3 of 5 pages done · about 4m left · 2:30 a page on average (2 timed)");
});

test("the open page's time is capped at the mean and ignored when it is done", () => {
  const records = [{ done: true, seconds: 120 }, { done: false }, { done: false }];
  assert.match(progressLine(records, { notDone: true, elapsed: 900 }).text, /about 2m left/);
  assert.match(progressLine(records, { notDone: false, elapsed: 900 }).text, /about 4m left/);
});

test("no pages gives an empty fraction, not NaN", () => {
  assert.equal(progressLine([]).fraction, 0);
});
