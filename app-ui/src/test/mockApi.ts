import { vi } from "vitest";

type Method = "DELETE" | "GET" | "PATCH" | "POST";
type RouteMatcher = RegExp | string;

type MockApiRequest = {
  init?: RequestInit;
  match: RegExpMatchArray | null;
  url: string;
};

type MockApiHandler = (request: MockApiRequest) => Promise<Response> | Response;

type MockApiRoute = {
  handler: MockApiHandler;
  matcher: RouteMatcher;
  method: Method;
};

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return {
    ok: init.status === undefined || (init.status >= 200 && init.status < 300),
    status: init.status ?? 200,
    json: async () => body,
  } as Response;
}

export function emptyResponse(init: ResponseInit = {}): Response {
  return {
    ok: init.status === undefined || (init.status >= 200 && init.status < 300),
    status: init.status ?? 200,
  } as Response;
}

export function blobResponse(blob: Blob, init: ResponseInit = {}): Response {
  return {
    headers: new Headers(init.headers),
    ok: init.status === undefined || (init.status >= 200 && init.status < 300),
    status: init.status ?? 200,
    blob: async () => blob,
  } as Response;
}

export function failUnexpectedFetch(url: string, init?: RequestInit): never {
  throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
}

export function createMockApi() {
  const routes: MockApiRoute[] = [];

  function add(method: Method, matcher: RouteMatcher, handler: MockApiHandler) {
    routes.push({ handler, matcher, method });
    return api;
  }

  const api = {
    delete: (matcher: RouteMatcher, handler: MockApiHandler) => add("DELETE", matcher, handler),
    get: (matcher: RouteMatcher, handler: MockApiHandler) => add("GET", matcher, handler),
    patch: (matcher: RouteMatcher, handler: MockApiHandler) => add("PATCH", matcher, handler),
    post: (matcher: RouteMatcher, handler: MockApiHandler) => add("POST", matcher, handler),
    mockFetch: () =>
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method ?? "GET").toUpperCase() as Method;

        for (const route of routes) {
          if (route.method !== method) {
            continue;
          }

          if (typeof route.matcher === "string") {
            if (route.matcher === url) {
              return route.handler({ init, match: null, url });
            }
            continue;
          }

          const match = url.match(route.matcher);
          if (match) {
            return route.handler({ init, match, url });
          }
        }

        failUnexpectedFetch(url, init);
      }),
  };

  return api;
}
