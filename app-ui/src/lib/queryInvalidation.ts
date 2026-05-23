import type { QueryClient, QueryKey } from "@tanstack/react-query";

export async function invalidateQueryKeys(queryClient: QueryClient, queryKeys: readonly QueryKey[]): Promise<void> {
  await Promise.all(compactQueryKeys(queryKeys).map((queryKey) => queryClient.invalidateQueries({ queryKey })));
}

export function compactQueryKeys(queryKeys: readonly QueryKey[]): QueryKey[] {
  const compacted: QueryKey[] = [];

  for (const queryKey of queryKeys) {
    if (compacted.some((candidate) => isQueryKeyPrefix(candidate, queryKey))) {
      continue;
    }

    for (let index = compacted.length - 1; index >= 0; index -= 1) {
      if (isQueryKeyPrefix(queryKey, compacted[index])) {
        compacted.splice(index, 1);
      }
    }

    compacted.push(queryKey);
  }

  return compacted;
}

function isQueryKeyPrefix(candidatePrefix: QueryKey, queryKey: QueryKey): boolean {
  return (
    candidatePrefix.length <= queryKey.length &&
    candidatePrefix.every((candidatePart, index) => queryKeyPartEquals(candidatePart, queryKey[index]))
  );
}

function queryKeyPartEquals(first: unknown, second: unknown): boolean {
  if (Object.is(first, second)) {
    return true;
  }
  if (Array.isArray(first) && Array.isArray(second)) {
    return (
      first.length === second.length &&
      first.every((firstValue, index) => queryKeyPartEquals(firstValue, second[index]))
    );
  }
  if (isRecord(first) && isRecord(second)) {
    const firstKeys = Object.keys(first).sort();
    const secondKeys = Object.keys(second).sort();
    return (
      firstKeys.length === secondKeys.length &&
      firstKeys.every(
        (key, index) => key === secondKeys[index] && queryKeyPartEquals(first[key], second[key]),
      )
    );
  }

  return false;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Object.prototype.toString.call(value) === "[object Object]";
}
