import type { z } from "zod";

export const endpoints = {
  api: (path: `/${string}`) => `/api${path}`,
};

type JsonSchema<T> = z.ZodType<T>;

type JsonRequestOptions<T> = {
  body?: unknown;
  errorMessage?: string;
  schema?: JsonSchema<T>;
};

export class ApiRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(`${message} with status ${status}`);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

async function parseJson<T>(response: Response, schema?: JsonSchema<T>): Promise<T> {
  if (response.status === 204 || typeof response.json !== "function") {
    return undefined as T;
  }

  const data = (await response.json()) as unknown;
  return schema ? schema.parse(data) : (data as T);
}

function requestError(errorMessage: string | undefined, status: number) {
  return new ApiRequestError(errorMessage ?? "Request failed", status);
}

export async function fetchJson<T>(
  input: RequestInfo | URL,
  schema?: JsonSchema<T>,
): Promise<T> {
  const response = await fetch(input);

  if (!response.ok) {
    throw requestError(undefined, response.status);
  }

  return parseJson(response, schema);
}

async function requestJson<T>(
  method: "DELETE" | "PATCH" | "POST",
  input: RequestInfo | URL,
  options: JsonRequestOptions<T> = {},
): Promise<T> {
  const init: RequestInit = {
    method,
  };

  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
    init.headers = {
      "Content-Type": "application/json",
    };
  }

  const response = await fetch(input, init);

  if (!response.ok) {
    throw requestError(options.errorMessage, response.status);
  }

  return parseJson(response, options.schema);
}

export function postJson<T>(
  input: RequestInfo | URL,
  options?: JsonRequestOptions<T>,
): Promise<T> {
  return requestJson("POST", input, options);
}

export function patchJson<T>(
  input: RequestInfo | URL,
  options?: JsonRequestOptions<T>,
): Promise<T> {
  return requestJson("PATCH", input, options);
}

export function deleteJson<T>(
  input: RequestInfo | URL,
  options?: JsonRequestOptions<T>,
): Promise<T> {
  return requestJson("DELETE", input, options);
}

export async function fetchBlob(
  input: RequestInfo | URL,
  errorMessage?: string,
): Promise<{ blob: Blob; response: Response }> {
  const response = await fetch(input);

  if (!response.ok) {
    throw requestError(errorMessage, response.status);
  }

  return {
    blob: await response.blob(),
    response,
  };
}
