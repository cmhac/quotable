// The per-page work clock and the time-left line of the gold check (spec 016, FR-020a and
// FR-020b). Pure: no DOM, and the time comes from a function the caller can replace.

export function clock(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  const t = Math.floor(seconds);
  const pad = (n) => String(n).padStart(2, "0");
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  return h ? `${h}:${pad(m)}:${pad(t % 60)}` : `${m}:${pad(t % 60)}`;
}

export function roughly(seconds) {
  const m = Math.max(0, Math.round(seconds / 60));
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
}

// seconds is a number, or null for a page finished before timing existed (shown as "--",
// never counted, never started again).
export function makeTimer(now = () => Date.now()) {
  let seconds = 0;
  let since = null;
  const timer = {
    get running() {
      return since !== null;
    },
    elapsed() {
      if (seconds === null) return null;
      return seconds + (since === null ? 0 : (now() - since) / 1000);
    },
    set(value) {
      seconds = value;
      since = null;
    },
    // Stop counting and keep the time; says whether it was running (so a caller can save).
    pause() {
      if (since === null) return false;
      seconds = timer.elapsed();
      since = null;
      return true;
    },
    // Start counting if the page may be timed now (open, not done, window in front).
    run(allowed) {
      if (!allowed || seconds === null || since !== null) return;
      since = now();
    },
    reset() {
      seconds = 0;
      since = null;
    },
  };
  return timer;
}

// records: one {done, seconds} per sampled page. open: {notDone, elapsed} for the page on
// screen. Time left = pages not done x the mean time of the timed done pages, less what the
// open page has used (never more than the mean).
export function progressLine(records, open = { notDone: false, elapsed: 0 }) {
  const total = records.length;
  const done = records.filter((r) => r.done).length;
  const timed = records.filter((r) => r.done && r.seconds > 0).map((r) => r.seconds);
  let text = `${done} of ${total} pages done`;
  if (timed.length) {
    const mean = timed.reduce((a, b) => a + b, 0) / timed.length;
    const used = open.notDone ? Math.min(open.elapsed ?? 0, mean) : 0;
    const left = (total - done) * mean - used;
    text += ` · about ${roughly(left)} left · ${clock(mean)} a page on average (${timed.length} timed)`;
  } else {
    text += " · time estimate after the first timed page is done";
  }
  return { done, total, fraction: total ? done / total : 0, text };
}
