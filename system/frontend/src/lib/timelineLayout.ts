import type { TimelineSegment } from "@/lib/studioApi";

export const PX_PER_SEC = 46;
/** Visual gap between adjacent segment boxes (pixels) — does not affect time mapping. */
export const SEGMENT_GAP_PX = 4;

/** How long the narration occupies within a segment (offset + audio length). */
export function narrationSpan(seg: TimelineSegment): number {
  const audioDur = seg.audio_duration || 0;
  if (audioDur <= 0.1) return 0;
  return (seg.audio_offset || 0) + audioDur;
}

/** Duration of this segment on the Studio layout timeline. */
export function displayDuration(seg: TimelineSegment): number {
  const audioPad = seg.audio_duration > 0 ? seg.audio_duration + 0.4 : 0;
  const base =
    seg.output_duration && seg.output_duration > 0
      ? seg.output_duration
      : Math.max(seg.duration || 0, seg.editing_window || 0, audioPad, 1.2);
  // Never let the layout window be shorter than where narration actually plays,
  // otherwise the playhead hits the next scene while audio is still going.
  return Math.max(base, narrationSpan(seg) + 0.05, 1.2);
}

export interface LaidOutSegment {
  segment: TimelineSegment;
  /** Start time on the non-overlapping Studio layout clock. */
  start: number;
  duration: number;
  left: number;
  width: number;
  /** Start time of this segment on the real MP4 clock. */
  mediaStart: number;
  mediaDuration: number;
}

export interface TimelineLayout {
  items: LaidOutSegment[];
  totalDuration: number;
  totalWidth: number;
}

/**
 * Non-overlapping sequential layout for a clean editor UI.
 * Playhead sync uses mediaStart/mediaDuration + active narration windows to
 * map MP4 time ↔ layout time.
 */
export function layoutTimeline(segments: TimelineSegment[]): TimelineLayout {
  let layoutT = 0;
  let mediaT = 0;
  const items: LaidOutSegment[] = segments.map((seg, index) => {
    const dur = displayDuration(seg);
    // Always chain layout sequentially — never use compressed/overlapping starts.
    const start = layoutT;
    const mediaStart =
      typeof seg.media_start === "number" && seg.media_start >= 0
        ? seg.media_start
        : mediaT;
    const mediaDuration = Math.max(
      typeof seg.media_duration === "number" && seg.media_duration > 0
        ? seg.media_duration
        : dur,
      narrationSpan(seg) + 0.05
    );

    const item: LaidOutSegment = {
      segment: seg,
      start,
      duration: dur,
      left: start * PX_PER_SEC + index * SEGMENT_GAP_PX,
      width: Math.max(dur * PX_PER_SEC, 8),
      mediaStart,
      mediaDuration,
    };
    layoutT = start + dur;
    // Estimate next media cursor only when sidecar timing is missing.
    if (!(typeof seg.media_start === "number" && seg.media_start >= 0)) {
      mediaT = mediaStart + mediaDuration;
    }
    return item;
  });

  let totalDuration = 0;
  for (const item of items) {
    totalDuration = Math.max(totalDuration, item.start + item.duration);
  }

  const gapTotal = Math.max(0, items.length - 1) * SEGMENT_GAP_PX;
  return {
    items,
    totalDuration,
    totalWidth: totalDuration * PX_PER_SEC + gapTotal,
  };
}

export function timeToPx(t: number): number {
  return t * PX_PER_SEC;
}

export function pxToTime(px: number): number {
  return px / PX_PER_SEC;
}

/** Convert a pixel x (within the track content, no gutter) to layout time. */
export function pxToLayoutTime(px: number, layout: TimelineLayout): number {
  if (!layout.items.length) return 0;
  for (const item of layout.items) {
    if (px < item.left + item.width) {
      const localPx = Math.max(0, px - item.left);
      return item.start + localPx / PX_PER_SEC;
    }
  }
  const last = layout.items[layout.items.length - 1];
  return last.start + last.duration;
}

/** Layout time → pixel x including segment gaps. */
export function layoutTimeToPx(t: number, layout: TimelineLayout): number {
  if (!layout.items.length) return timeToPx(t);
  for (let i = 0; i < layout.items.length; i++) {
    const item = layout.items[i];
    if (t <= item.start + item.duration || i === layout.items.length - 1) {
      const local = Math.max(0, Math.min(item.duration, t - item.start));
      return item.left + local * PX_PER_SEC;
    }
  }
  return layout.totalWidth;
}

/**
 * MP4 currentTime → Studio layout time.
 *
 * Critical: while a segment's narration is still audible, keep the playhead on
 * that segment's audio clip — even if a crossfade has already started the next
 * scene in the MP4 (that was jumping Bedroom → Closet too early).
 */
export function videoTimeToLayoutTime(t: number, layout: TimelineLayout): number {
  if (!layout.items.length) return t;

  // 1) Active narration wins — pin playhead to the playing audio block.
  //    Use narration_at (actual mix start, after no-overlap guard) when present.
  for (const item of layout.items) {
    const offset = item.segment.audio_offset || 0;
    const audioDur = item.segment.audio_duration || 0;
    if (audioDur <= 0.1) continue;
    const n0 =
      typeof item.segment.narration_at === "number"
        ? item.segment.narration_at
        : item.mediaStart + offset;
    const n1 = n0 + audioDur;
    if (t + 1e-3 >= n0 && t < n1) {
      return item.start + offset + (t - n0);
    }
  }

  // 2) Follow the picture, but stay for the segment's FULL mediaDuration.
  //    Do not jump at the next segment's mediaStart during a crossfade.
  for (const item of layout.items) {
    if (t + 1e-3 >= item.mediaStart && t < item.mediaStart + item.mediaDuration) {
      const local = Math.max(0, Math.min(item.mediaDuration, t - item.mediaStart));
      // If layout window is longer than media (expanded for audio), clamp.
      return item.start + Math.min(local, item.duration);
    }
  }

  const first = layout.items[0];
  const last = layout.items[layout.items.length - 1];
  if (t < first.mediaStart) return first.start;
  return last.start + last.duration;
}

/** Studio layout time → MP4 seek time. */
export function layoutTimeToVideoTime(t: number, layout: TimelineLayout): number {
  if (!layout.items.length) return t;
  let match = layout.items[0];
  for (const item of layout.items) {
    if (t + 1e-4 >= item.start) match = item;
  }
  const local = Math.max(0, Math.min(match.duration, t - match.start));
  return match.mediaStart + Math.min(local, match.mediaDuration);
}

export function formatTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

/** Segment (if any) whose layout window contains layout time t. */
export function segmentAtTime(layout: TimelineLayout, t: number): LaidOutSegment | null {
  for (const item of layout.items) {
    if (t >= item.start && t < item.start + item.duration) return item;
  }
  return layout.items[layout.items.length - 1] ?? null;
}
