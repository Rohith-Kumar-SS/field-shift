// Motion helpers. Every one of them stands down when the visitor asks for reduced motion,
// and none of them delays information: values and positions are final in the DOM at once
// where animation is not possible (hidden tab, reduced motion).

import { useEffect, useLayoutEffect, useRef, useState } from "react";

export const reducedMotion = () => typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
const canAnimate = () => !reducedMotion() && !document.hidden;

/** A number that glides to its new value instead of jumping (scores, millimetres). */
export function useTween(value: number, ms = 520): number {
  const [shown, setShown] = useState(value);
  const last = useRef(value);
  useEffect(() => {
    const from = last.current;
    if (!canAnimate() || from === value || !Number.isFinite(from) || !Number.isFinite(value)) {
      last.current = value;
      setShown(value);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const v = from + (value - from) * (1 - Math.pow(1 - k, 3));
      last.current = v;
      setShown(v);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const safety = window.setTimeout(() => {
      last.current = value;
      setShown(value);
    }, ms + 250);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(safety);
    };
  }, [value, ms]);
  return shown;
}

/**
 * FLIP for a list whose order changes: each item slides from where it was to where it now is.
 * Used for the rotation cards, so re-ranking under new priorities is something you can watch.
 */
export function useFlip() {
  const nodes = useRef(new Map<string, HTMLElement>());
  const tops = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const next = new Map<string, number>();
    nodes.current.forEach((el, id) => next.set(id, el.offsetTop));
    if (canAnimate()) {
      nodes.current.forEach((el, id) => {
        const before = tops.current.get(id);
        const dy = before === undefined ? 0 : before - next.get(id)!;
        if (Math.abs(dy) > 2) {
          el.animate([{ transform: `translateY(${dy}px)` }, { transform: "translateY(0)" }], { duration: 460, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" });
        }
      });
    }
    tops.current = next;
  });
  return (id: string) => (el: HTMLElement | null) => {
    if (el) nodes.current.set(id, el);
    else nodes.current.delete(id);
  };
}

/** True once the element has scrolled into view (used to start a drawing animation once). */
export function useSeen<T extends Element>(): [React.RefObject<T>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (!("IntersectionObserver" in window) || !canAnimate()) {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setSeen(true), { threshold: 0.2 });
    io.observe(el);
    const safety = window.setTimeout(() => setSeen(true), 2500);
    return () => {
      io.disconnect();
      window.clearTimeout(safety);
    };
  }, [seen]);
  return [ref, seen];
}
