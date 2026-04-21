import useSWR from 'swr';
import { resolveApiBase } from '../src/api';

/**
 * useApi — SWR wrapper with null-key support (pass empty string/null/undefined to skip fetching).
 */
export function useApi<T>(
  path: string | null | undefined,
  opts?: { refreshInterval?: number; fallbackData?: T },
) {
  const apiBase = resolveApiBase();
  const key = path ? `${apiBase}${path}` : null;
  const { data, error, isLoading, mutate } = useSWR<T>(
    key,
    (url: string) => fetch(url).then((r) => {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    }),
    { refreshInterval: opts?.refreshInterval, fallbackData: opts?.fallbackData },
  );
  return { data, error, isLoading, mutate };
}
