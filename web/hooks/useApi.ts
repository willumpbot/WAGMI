import useSWR from 'swr';
import { resolveApiBase } from '../src/api';

export function useApi<T>(path: string, opts?: { refreshInterval?: number; fallbackData?: T }) {
  const apiBase = resolveApiBase();
  const { data, error, isLoading, mutate } = useSWR<T>(
    `${apiBase}${path}`,
    (url: string) => fetch(url).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); }),
    { refreshInterval: opts?.refreshInterval, fallbackData: opts?.fallbackData }
  );
  return { data, error, isLoading, mutate };
}
