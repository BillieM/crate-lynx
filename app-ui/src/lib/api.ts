export const endpoints = {
  api: (path: `/${string}`) => `/api${path}`,
};

export async function fetchJson<T>(input: RequestInfo | URL): Promise<T> {
  const response = await fetch(input);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}
