/**
 * Admin panel API client.
 *
 * The client is the only thing standing between the UI and a 401, so the
 * behaviours that matter are: where the token lives, whether it is attached,
 * and whether a failure surfaces the backend's `detail` instead of a generic
 * "Not Found".
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, endpoints, getToken, setToken } from "./api";

/** Minimal Response-shaped stub; jsdom's fetch is not used. */
function jsonResponse(status: number, body: unknown, statusText = "OK") {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
  } as unknown as Response;
}

function mockFetch(result: Response) {
  const fetchMock = vi.fn().mockResolvedValue(result);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// token storage
// ---------------------------------------------------------------------------
describe("token storage", () => {
  it("starts empty", () => {
    expect(getToken()).toBeNull();
  });

  it("round-trips through localStorage", () => {
    setToken("abc123");
    expect(getToken()).toBe("abc123");
    expect(window.localStorage.getItem("soulchat.token")).toBe("abc123");
  });

  it("clearing with null removes the key, not stores 'null'", () => {
    setToken("abc123");
    setToken(null);
    expect(getToken()).toBeNull();
    expect(window.localStorage.getItem("soulchat.token")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// request shaping
// ---------------------------------------------------------------------------
describe("api()", () => {
  it("sends JSON content type and no-store", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { ok: true }));

    await api("/api/v1/settings");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/settings");
    expect(init.cache).toBe("no-store");
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("attaches the bearer token once one is stored", async () => {
    setToken("tok-99");
    const fetchMock = mockFetch(jsonResponse(200, {}));

    await api("/api/v1/topics");

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-99");
  });

  it("omits Authorization entirely when logged out", async () => {
    const fetchMock = mockFetch(jsonResponse(200, {}));

    await api("/api/v1/topics");

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("keeps caller-supplied headers", async () => {
    const fetchMock = mockFetch(jsonResponse(200, {}));

    await api("/api/v1/settings", {
      method: "PUT",
      headers: { "X-Trace": "abc" },
      body: JSON.stringify({ key: "a", value: 1 }),
    });

    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe("PUT");
    expect(init.headers["X-Trace"]).toBe("abc");
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("returns undefined for 204 instead of parsing an empty body", async () => {
    const fetchMock = mockFetch({
      ok: true,
      status: 204,
      statusText: "No Content",
      json: async () => {
        throw new Error("must not be called");
      },
    } as unknown as Response);

    await expect(api("/api/v1/nothing")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// error handling
// ---------------------------------------------------------------------------
describe("error handling", () => {
  it("surfaces the backend detail field", async () => {
    mockFetch(jsonResponse(403, { detail: "Sizda ruxsat yo'q" }, "Forbidden"));

    const error = await api("/api/v1/users").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403);
    expect((error as ApiError).message).toBe("Sizda ruxsat yo'q");
  });

  it("falls back to statusText when the body has no detail", async () => {
    mockFetch(jsonResponse(401, {}, "Unauthorized"));

    const error = (await api("/api/v1/users").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(401);
    expect(error.message).toBe("Unauthorized");
  });

  it("survives a non-JSON error body", async () => {
    mockFetch({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: async () => {
        throw new SyntaxError("Unexpected token <");
      },
    } as unknown as Response);

    const error = (await api("/api/v1/users").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(error.message).toBe("Bad Gateway");
  });

  it("is a real Error so it can be thrown and caught normally", async () => {
    mockFetch(jsonResponse(500, { detail: "boom" }, "Internal Server Error"));

    await expect(api("/api/v1/backup")).rejects.toThrow("boom");
  });
});

// ---------------------------------------------------------------------------
// endpoint builders
// ---------------------------------------------------------------------------
describe("endpoints", () => {
  it("posts credentials as JSON", async () => {
    const fetchMock = mockFetch(
      jsonResponse(200, { access_token: "a", refresh_token: "r", token_type: "bearer" })
    );

    const result = await endpoints.login({ username: "admin", password: "pw" });

    expect(result.access_token).toBe("a");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ username: "admin", password: "pw" });
  });

  it("URL-encodes the status filter", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { items: [], total: 0 }));

    await endpoints.topics("delete pending");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/topics?status=delete%20pending");
  });

  it("omits the query string when no status is given", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { items: [], total: 0 }));

    await endpoints.topics();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/topics");
  });

  it("builds the topic action path from the code", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { id: 1 }));

    await endpoints.topicAction("A-0001", "freeze", "spam");

    const [url, init] = fetchFetchCalls(fetchMock);
    expect(url).toBe("/api/v1/topics/A-0001/freeze");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ reason: "spam" });
  });

  it("unfreeze reaches its own endpoint, not /restore", async () => {
    // freeze and unfreeze are separate routes on the backend; a moderator must
    // not have to borrow the deletion-rescue path to lift a freeze.
    const fetchMock = mockFetch(jsonResponse(200, { id: 1 }));

    await endpoints.topicAction("A-0001", "unfreeze", "toza");

    const [url, init] = fetchFetchCalls(fetchMock);
    expect(url).toBe("/api/v1/topics/A-0001/unfreeze");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ reason: "toza" });
  });

  it("defaults the dashboard window to 30 days", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { stats: {}, daily: [], weekly: [], monthly: [] }));

    await endpoints.dashboard();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/analytics/dashboard?days=30");

    await endpoints.dashboard(7);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/analytics/dashboard?days=7");
  });

  it("sends setting updates as key/value JSON", async () => {
    const fetchMock = mockFetch(jsonResponse(200, { key: "topic.max_per_user", value: 5 }));

    await endpoints.updateSetting("topic.max_per_user", 5);

    const [url, init] = fetchFetchCalls(fetchMock);
    expect(url).toBe("/api/v1/settings");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ key: "topic.max_per_user", value: 5 });
  });
});

function fetchFetchCalls(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  return fetchMock.mock.calls[0] as [string, RequestInit];
}