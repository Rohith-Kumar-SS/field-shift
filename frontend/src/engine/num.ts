// Small numeric helpers that behave like the Python reference engine (engine/*.py),
// so the browser and the tested Python code give the same numbers and the same wording.

export const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
export const MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export type MonthMap = Record<number, number>;

export const clamp = (v: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));

/**
 * Python's round(): the exact binary value is rounded, and only a true tie goes to the even
 * neighbour. (Multiplying by 10^n first, as Math.round tricks do, invents ties: 2.85 is stored
 * as 2.85000000000000008..., which Python rounds to 2.9.)
 */
export function pyRound(x: number, digits = 0): number {
  if (!Number.isFinite(x)) return x;
  const a = Math.abs(x);
  if (a >= 1e15) return x;
  const exact = a.toFixed(Math.min(digits + 30, 100));
  const cut = exact.indexOf(".") + 1 + digits;
  let r: number;
  if (/^50*$/.test(exact.slice(cut))) {
    const head = exact.slice(0, cut);
    const last = Number(head.replace(".", "").slice(-1));
    r = Number((Number(head) + (last % 2 === 0 ? 0 : Math.pow(10, -digits))).toFixed(digits));
  } else {
    r = Number(a.toFixed(digits));
  }
  return x < 0 ? -r : r;
}

/** Python's f"{x:.nf}". */
export const fx = (x: number, digits = 0) => {
  const r = pyRound(x, digits);
  return (Object.is(r, -0) ? 0 : r).toFixed(digits);
};

/** Python's str(float): whole numbers keep their ".0". */
export const pyFloat = (x: number) => (Number.isInteger(x) ? x.toFixed(1) : String(x));

/** Python's built-in sum(): compensated (Neumaier) summation, as CPython 3.12+ does for floats. */
export const sum = (a: number[]) => {
  let hi = 0;
  let lo = 0;
  for (const x of a) {
    const t = hi + x;
    lo += Math.abs(hi) >= Math.abs(x) ? hi - t + x : x - t + hi;
    hi = t;
  }
  return hi + lo;
};

/** numpy's sum(): plain for short arrays, eight running partial sums from 8 values up. */
export function npSum(a: number[]): number {
  const n = a.length;
  if (n < 8) {
    let s = 0;
    for (let i = 0; i < n; i++) s += a[i];
    return s;
  }
  const r = a.slice(0, 8);
  let i = 8;
  for (; i < n - (n % 8); i += 8) for (let j = 0; j < 8; j++) r[j] += a[i + j];
  let res = r[0] + r[1] + (r[2] + r[3]) + (r[4] + r[5] + (r[6] + r[7]));
  for (; i < n; i++) res += a[i];
  return res;
}
export const mean = (a: number[]) => (a.length ? npSum(a) / a.length : NaN);

/** Linear-interpolated quantile, as numpy and pandas compute it by default. */
export function quantile(values: number[], q: number): number {
  const a = [...values].sort((x, y) => x - y);
  if (!a.length) return NaN;
  const pos = (a.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return a[lo] + (a[hi] - a[lo]) * (pos - lo);
}
export const median = (values: number[]) => quantile(values, 0.5);

export const monthMap = (fn: (m: number) => number): MonthMap => {
  const out: MonthMap = {};
  for (const m of MONTHS) out[m] = fn(m);
  return out;
};

export const unique = <T,>(a: T[]) => Array.from(new Set(a));
export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
