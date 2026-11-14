/**
 * Coalesces a high-frequency callback (e.g. mousemove during a drag) down to
 * at most once per animation frame, always using the most recent arguments.
 *
 * Without this, dragging fast fires dozens of mousemove events between
 * frames, and if the handler does anything non-trivial (React state update,
 * video.currentTime seek, layout recompute) the browser falls behind and
 * the page appears to freeze.
 */
export function rafThrottle<Args extends unknown[]>(
  fn: (...args: Args) => void
): (...args: Args) => void {
  let scheduled = false;
  let lastArgs: Args | null = null;

  return (...args: Args) => {
    lastArgs = args;
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      if (lastArgs) fn(...lastArgs);
    });
  };
}
