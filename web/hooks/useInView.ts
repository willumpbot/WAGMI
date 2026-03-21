import { useEffect, useState, type RefObject } from 'react';

/**
 * Scroll-triggered visibility detection using IntersectionObserver.
 * When `once` is true the hook latches to true after first intersection.
 */
export function useInView(
  ref: RefObject<Element | null>,
  opts?: { once?: boolean; margin?: string },
): boolean {
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          if (opts?.once) observer.disconnect();
        } else if (!opts?.once) {
          setInView(false);
        }
      },
      { rootMargin: opts?.margin ?? '0px' },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, opts?.once, opts?.margin]);

  return inView;
}
