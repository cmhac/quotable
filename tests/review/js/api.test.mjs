import assert from "node:assert/strict";
import { test } from "node:test";

const { apiUrl, getJson, ApiError } = await import("../../../quotable/review/static/api.js");

function stubFetch(response) {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    if (response instanceof Error) throw response;
    return response;
  };
  return calls;
}

const reply = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => {
    if (body === undefined) throw new SyntaxError("not json");
    return body;
  },
});

test("apiUrl adds the non-empty query values", () => {
  assert.equal(apiUrl("/api/runs"), "/api/runs");
  assert.equal(apiUrl("/api/runs", { document: "a b", model: "", x: null }), "/api/runs?document=a+b");
});

test("getJson returns the JSON of an answer", async () => {
  const calls = stubFetch(reply(200, { runs: 2 }));
  assert.deepEqual(await getJson("/api/runs", { model: "m" }), { runs: 2 });
  assert.equal(calls[0][0], "/api/runs?model=m");
});

test("an error answer becomes an ApiError with the server's message", async () => {
  stubFetch(reply(404, { error: "no such run" }));
  await assert.rejects(getJson("/api/runs/x"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.message, "no such run");
    assert.equal(err.status, 404);
    return true;
  });
});

test("an error answer without a message says the status", async () => {
  stubFetch(reply(502, undefined));
  await assert.rejects(getJson("/api/runs"), /502/);
});

test("a server that cannot be reached is explained", async () => {
  stubFetch(new TypeError("Failed to fetch"));
  await assert.rejects(getJson("/api/runs"), /could not reach the review server/i);
});

test("an answer that is not JSON is an error", async () => {
  stubFetch(reply(200, undefined));
  await assert.rejects(getJson("/api/runs"), /not JSON/);
});
