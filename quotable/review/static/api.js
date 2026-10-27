// Talking to the server: JSON in, an ApiError with a readable message out.

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function apiUrl(path, query) {
  const entries = Object.entries(query ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  return entries.length ? `${path}?${new URLSearchParams(entries)}` : path;
}

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new ApiError(
      "Could not reach the review server. Is `quotable review` still running?",
    );
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new ApiError(
      body?.error ?? `The server answered ${response.status}`,
      response.status,
    );
  }
  if (body === null)
    throw new ApiError("The server’s answer was not JSON", response.status);
  return body;
}

export const getJson = (path, query) => request(apiUrl(path, query));

export const sendJson = (method, path, body) =>
  request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
