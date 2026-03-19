/**
 * Shared API utilities — import these instead of duplicating resolveApiBase in every page.
 */

export function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

/**
 * Typed fetch wrapper — resolves the API base, returns null on any failure.
 * Usage: const data = await apiFetch<MyType>('/v1/endpoint?limit=50');
 */
export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T | null> {
  try {
    const base = resolveApiBase();
    const res = await fetch(`${base}${path}`, {
      cache: 'no-store',
      ...options,
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}
