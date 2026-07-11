import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

type SessionDraftCodec<T> = {
  deserialize: (storedValue: unknown) => T;
  serialize: (value: T) => unknown;
};

const jsonCodec = {
  deserialize: <T,>(storedValue: unknown) => storedValue as T,
  serialize: <T,>(value: T) => value,
};

export function setSessionDraftCodec<T extends number | string>(): SessionDraftCodec<Set<T>> {
  return {
    deserialize: (storedValue) => new Set(Array.isArray(storedValue) ? (storedValue as T[]) : []),
    serialize: (value) => Array.from(value),
  };
}

export function useSessionDraftState<T>(
  key: string,
  initialValue: T | (() => T),
  codec: SessionDraftCodec<T> = jsonCodec as SessionDraftCodec<T>,
): [T, Dispatch<SetStateAction<T>>, boolean] {
  const [initial] = useState(() => {
    const fallbackValue = typeof initialValue === "function" ? (initialValue as () => T)() : initialValue;

    try {
      const storedValue = window.sessionStorage.getItem(key);
      if (storedValue === null) {
        return { hasStoredValue: false, value: fallbackValue };
      }

      return { hasStoredValue: true, value: codec.deserialize(JSON.parse(storedValue) as unknown) };
    } catch {
      return { hasStoredValue: false, value: fallbackValue };
    }
  });
  const [value, setValue] = useState<T>(initial.value);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(codec.serialize(value)));
    } catch {
      // Draft persistence is best effort; the workflow remains usable without storage.
    }
  }, [codec, key, value]);

  return [value, setValue, initial.hasStoredValue];
}
