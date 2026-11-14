"use client";

import { Captions, Mic, Pencil, Video } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import type { TimelineSegment } from "@/lib/studioApi";
import { rafThrottle } from "@/lib/rafThrottle";
import {
  formatTime,
  layoutTimeline,
  layoutTimeToPx,
  layoutTimeToVideoTime,
  pxToLayoutTime,
  pxToTime,
  timeToPx,
  videoTimeToLayoutTime,
  type LaidOutSegment,
} from "@/lib/timelineLayout";

const GUTTER_PX = 96; // matches the w-24 row-label column
const ROW_HEIGHTS = { ruler: 22, video: 56, script: 48, audio: 40, subtitle: 32 };

const ROLE_STYLE: Record<string, string> = {
  HERO: "bg-studio-primary/10 border-studio-primary/50 text-studio-primary",
  SUPPORT: "bg-studio-process/15 border-studio-process/45 text-studio-process",
  TRANSITION: "bg-studio-transition/15 border-studio-transition/40 text-studio-muted",
};

/** Deterministic pseudo-waveform bars so the audio lane doesn't look empty. */
function waveformBars(seed: string, count: number): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 997;
  const bars: number[] = [];
  for (let i = 0; i < count; i++) {
    h = (h * 1103515245 + 12345) % 2147483648;
    bars.push(0.25 + ((h % 1000) / 1000) * 0.7);
  }
  return bars;
}

function tickStep(totalDuration: number): number {
  if (totalDuration <= 20) return 2;
  if (totalDuration <= 60) return 5;
  if (totalDuration <= 180) return 10;
  return 20;
}

function maxAudioOffset(item: LaidOutSegment): number {
  return Math.max(0, item.duration - (item.segment.audio_duration || 0) - 0.02);
}

function RowShell({
  icon,
  label,
  height,
  totalWidth,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  height: number;
  totalWidth: number;
  children: React.ReactNode;
}) {
  return (
    <div className="flex" style={{ height }}>
      <div className="w-24 shrink-0 flex items-center gap-1.5 pr-2 text-[11px] text-studio-muted sticky left-0 bg-studio-panel2 z-10">
        {icon}
        {label}
      </div>
      <div className="relative" style={{ width: totalWidth, height }}>
        {children}
      </div>
    </div>
  );
}

interface Props {
  segments: TimelineSegment[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onEditNarration: (id: string) => void;
  onApplyOffset: (id: string, offset: number) => void;
  playheadTime: number;
  onScrub: (time: number, opts?: { immediate?: boolean }) => void;
  /** When provided, the playhead tracks video.currentTime every animation frame while playing. */
  videoRef?: RefObject<HTMLVideoElement | null>;
  /** Bumps when the <video> element remounts so we re-bind playhead sync. */
  mediaKey?: string | number;
  disabled?: boolean;
}

export default function Timeline({
  segments,
  selectedId,
  onSelect,
  onEditNarration,
  onApplyOffset,
  playheadTime,
  onScrub,
  videoRef,
  mediaKey,
  disabled,
}: Props) {
  const layout = useMemo(() => layoutTimeline(segments), [segments]);
  const waveformById = useMemo(() => {
    const map = new Map<string, number[]>();
    for (const item of layout.items) {
      const dur = item.segment.audio_duration || 0;
      map.set(item.segment.id, waveformBars(item.segment.id, Math.max(4, Math.round(dur * 3))));
    }
    return map;
  }, [layout.items]);

  const contentRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const clipElsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const labelElRef = useRef<HTMLSpanElement | null>(null);
  const scrubbingRef = useRef(false);

  const [scrubbing, setScrubbing] = useState(false);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const audioDragRef = useRef<{
    id: string;
    item: LaidOutSegment;
    grabDeltaPx: number;
    startOffset: number;
    liveOffset: number;
  } | null>(null);

  scrubbingRef.current = scrubbing;

  const paintPlayhead = useCallback(
    (videoTime: number) => {
      const el = playheadRef.current;
      if (!el) return;
      const layoutTime = videoTimeToLayoutTime(videoTime, layout);
      const clamped = Math.max(0, Math.min(layout.totalDuration || layoutTime, layoutTime));
      el.style.left = `${GUTTER_PX + layoutTimeToPx(clamped, layout)}px`;
    },
    [layout]
  );

  // While the video plays, drive the playhead from currentTime every frame
  // (DOM only — no React re-renders). Browser `timeupdate` is too sparse (~4/s).
  useEffect(() => {
    const video = videoRef?.current;
    if (!video) return;

    let raf = 0;
    let running = false;

    const tick = () => {
      if (!scrubbingRef.current) paintPlayhead(video.currentTime);
      raf = requestAnimationFrame(tick);
    };
    const start = () => {
      if (running) return;
      running = true;
      raf = requestAnimationFrame(tick);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
      if (!scrubbingRef.current) paintPlayhead(video.currentTime);
    };

    const onSeeked = () => {
      if (!scrubbingRef.current) paintPlayhead(video.currentTime);
    };

    video.addEventListener("play", start);
    video.addEventListener("playing", start);
    video.addEventListener("pause", stop);
    video.addEventListener("ended", stop);
    video.addEventListener("seeked", onSeeked);
    // Native control scrubbing while paused still needs a sync point.
    video.addEventListener("timeupdate", onSeeked);

    if (!video.paused && !video.ended) start();
    else paintPlayhead(video.currentTime);

    return () => {
      stop();
      video.removeEventListener("play", start);
      video.removeEventListener("playing", start);
      video.removeEventListener("pause", stop);
      video.removeEventListener("ended", stop);
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("timeupdate", onSeeked);
    };
  }, [videoRef, paintPlayhead, mediaKey]);

  // Scrub / external playheadTime updates (layout clock when paused).
  useLayoutEffect(() => {
    const video = videoRef?.current;
    if (video && !video.paused && !scrubbing) return;
    const el = playheadRef.current;
    if (!el) return;
    el.style.left = `${GUTTER_PX + layoutTimeToPx(playheadTime, layout)}px`;
  }, [playheadTime, layout, videoRef, scrubbing]);

  const timeFromClientX = useCallback(
    (clientX: number) => {
      const el = contentRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      const px = clientX - rect.left;
      return Math.max(0, Math.min(layout.totalDuration, pxToLayoutTime(px, layout)));
    },
    [layout]
  );

  const paintAudioOffset = useCallback((id: string, offset: number) => {
    const clip = clipElsRef.current.get(id);
    if (clip) clip.style.transform = `translateX(${timeToPx(offset)}px)`;
    const label = labelElRef.current;
    if (label) {
      label.style.transform = `translateX(${Math.max(0, timeToPx(offset) - 6)}px)`;
      label.textContent = `${offset.toFixed(1)}s in`;
    }
  }, []);

  useEffect(() => {
    if (!scrubbing) return;
    const move = rafThrottle((e: MouseEvent) => onScrub(timeFromClientX(e.clientX)));
    const up = (e: MouseEvent) => {
      onScrub(timeFromClientX(e.clientX), { immediate: true });
      setScrubbing(false);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [scrubbing, onScrub, timeFromClientX]);

  useEffect(() => {
    if (!draggingId) return;

    const move = rafThrottle((e: MouseEvent) => {
      const drag = audioDragRef.current;
      if (!drag) return;
      const el = contentRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const mouseXInLane = e.clientX - rect.left - drag.item.left;
      const rawOffset = pxToTime(mouseXInLane - drag.grabDeltaPx);
      const clamped = Math.max(0, Math.min(rawOffset, maxAudioOffset(drag.item)));
      const rounded = Math.round(clamped * 10) / 10;
      if (rounded === drag.liveOffset) return;
      drag.liveOffset = rounded;
      paintAudioOffset(drag.id, rounded);
    });

    const up = () => {
      const drag = audioDragRef.current;
      audioDragRef.current = null;
      setDraggingId(null);
      if (drag && drag.liveOffset !== drag.startOffset) {
        onApplyOffset(drag.id, drag.liveOffset);
      }
    };

    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [draggingId, onApplyOffset, paintAudioOffset]);

  const startAudioDrag = (item: LaidOutSegment, e: React.MouseEvent) => {
    if ((item.segment.audio_duration || 0) <= 0.1) return;
    e.preventDefault();
    e.stopPropagation();
    onSelect(item.segment.id);
    const el = contentRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const mouseXInLane = e.clientX - rect.left - item.left;
    const clipEl = clipElsRef.current.get(item.segment.id);
    let startOffset = item.segment.audio_offset || 0;
    if (clipEl) {
      const match = /translateX\(([-\d.]+)px\)/.exec(clipEl.style.transform || "");
      if (match) startOffset = pxToTime(parseFloat(match[1]));
    }
    const currentOffsetPx = timeToPx(startOffset);
    audioDragRef.current = {
      id: item.segment.id,
      item,
      grabDeltaPx: mouseXInLane - currentOffsetPx,
      startOffset,
      liveOffset: startOffset,
    };
    setDraggingId(item.segment.id);
  };

  const step = tickStep(layout.totalDuration);
  const ticks = useMemo(() => {
    const list: number[] = [];
    for (let t = 0; t <= layout.totalDuration; t += step) list.push(t);
    return list;
  }, [layout.totalDuration, step]);

  const totalHeight =
    ROW_HEIGHTS.ruler +
    ROW_HEIGHTS.video +
    ROW_HEIGHTS.script +
    ROW_HEIGHTS.audio +
    ROW_HEIGHTS.subtitle +
    4 * 8;

  return (
    <section className="border border-studio-border rounded-lg bg-studio-panel overflow-hidden studio-panel-topline">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-studio-border px-4 py-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-studio-muted">
            Timeline
          </p>
          <p className="text-sm font-medium text-studio-primary">
            {segments.length} scenes · {formatTime(layout.totalDuration)}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-studio-muted">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-studio-primary/35 border border-studio-primary/40" />
            Hero
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-studio-process/35 border border-studio-process/40" />
            Support
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm bg-studio-transition/35 border border-studio-transition/40" />
            Transition
          </span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <div className="py-3 pl-3 pr-4 min-w-max">
          <div className="relative space-y-2" style={{ width: GUTTER_PX + layout.totalWidth }}>
            <RowShell icon={null} label="" height={ROW_HEIGHTS.ruler} totalWidth={layout.totalWidth}>
              <div
                ref={contentRef}
                className="absolute inset-0 cursor-pointer"
                onMouseDown={(e) => {
                  if (disabled) return;
                  setScrubbing(true);
                  onScrub(timeFromClientX(e.clientX));
                }}
              >
                {ticks.map((t) => (
                  <div
                    key={t}
                    className="absolute top-0 bottom-0 flex items-end"
                    style={{ left: layoutTimeToPx(t, layout) }}
                  >
                    <div className="w-px h-2 bg-studio-border" />
                    <span className="text-[10px] text-studio-muted ml-1 -translate-y-0.5">
                      {formatTime(t)}
                    </span>
                  </div>
                ))}
              </div>
            </RowShell>

            <RowShell
              icon={<Video size={13} />}
              label="Video"
              height={ROW_HEIGHTS.video}
              totalWidth={layout.totalWidth}
            >
              {layout.items.map((item) => {
                const seg = item.segment;
                return (
                  <button
                    key={seg.id}
                    disabled={disabled}
                    onClick={() => onSelect(seg.id)}
                    style={{ left: item.left, width: item.width - 2, top: 2, height: ROW_HEIGHTS.video - 4 }}
                    className={`absolute border rounded-md flex flex-col items-start justify-center px-2 text-left transition-all ${
                      ROLE_STYLE[seg.role] || ROLE_STYLE.SUPPORT
                    } ${
                      selectedId === seg.id
                        ? "ring-2 ring-studio-accent ring-offset-1 ring-offset-studio-panel2"
                        : "opacity-90 hover:opacity-100"
                    }`}
                  >
                    <span className="text-[9.5px] opacity-60 absolute top-1 right-1.5">
                      {formatTime(item.start)}
                    </span>
                    <span className="text-[11px] font-medium truncate w-full">
                      {seg.room_type || seg.id}
                    </span>
                    <span className="text-[10px] opacity-70">{seg.role}</span>
                  </button>
                );
              })}
            </RowShell>

            <RowShell
              icon={<Pencil size={13} />}
              label="Script"
              height={ROW_HEIGHTS.script}
              totalWidth={layout.totalWidth}
            >
              {layout.items.map((item) => {
                const seg = item.segment;
                return (
                  <button
                    key={seg.id}
                    disabled={disabled}
                    onClick={() => onEditNarration(seg.id)}
                    style={{ left: item.left, width: item.width - 2, top: 2, height: ROW_HEIGHTS.script - 4 }}
                    className={`absolute border rounded-md px-2 py-1.5 text-left bg-[#C8A96E]/12 border-studio-accent/35 hover:border-studio-accent group ${
                      selectedId === seg.id ? "border-studio-accent ring-1 ring-studio-accent/40" : ""
                    }`}
                  >
                    <span className="text-[10.5px] text-studio-primary/90 line-clamp-2 leading-tight">
                      {seg.narration_text || "No narration"}
                    </span>
                    <span className="absolute top-1 right-1.5 text-[9px] text-studio-accent opacity-0 group-hover:opacity-100">
                      Edit
                    </span>
                  </button>
                );
              })}
            </RowShell>

            <RowShell
              icon={<Mic size={13} />}
              label="Audio"
              height={ROW_HEIGHTS.audio}
              totalWidth={layout.totalWidth}
            >
              {layout.items.map((item) => {
                const seg = item.segment;
                const hasAudio = (seg.audio_duration || 0) > 0.1;
                const isDraggingThis = draggingId === seg.id;
                const clipWidthPx = Math.max(timeToPx(seg.audio_duration || 0), 8);
                const bars = waveformById.get(seg.id) || [];
                const offset = seg.audio_offset || 0;

                return (
                  <div
                    key={seg.id}
                    onClick={() => onSelect(seg.id)}
                    style={{
                      left: item.left,
                      width: item.width - 2,
                      top: 1,
                      height: ROW_HEIGHTS.audio - 2,
                      backgroundImage:
                        "repeating-linear-gradient(135deg, rgba(255,255,255,0.045) 0px 5px, transparent 5px 10px)",
                    }}
                    className={`absolute rounded-md border bg-studio-bg/50 border-studio-border overflow-hidden ${
                      selectedId === seg.id ? "border-studio-accent/60" : ""
                    }`}
                  >
                    {hasAudio ? (
                      <div
                        ref={(node) => {
                          if (node) clipElsRef.current.set(seg.id, node);
                          else clipElsRef.current.delete(seg.id);
                        }}
                        onMouseDown={(e) => startAudioDrag(item, e)}
                        style={{
                          left: 0,
                          top: 2,
                          bottom: 2,
                          width: clipWidthPx,
                          transform: `translateX(${timeToPx(offset)}px)`,
                          willChange: isDraggingThis ? "transform" : undefined,
                        }}
                        className={`absolute rounded-[4px] border flex items-center gap-[2px] px-1.5 cursor-grab active:cursor-grabbing select-none ${
                          isDraggingThis
                            ? "border-studio-accent bg-studio-accent2/30"
                            : "border-studio-accent2/50 bg-studio-accent2/15 hover:bg-studio-accent2/25"
                        }`}
                        title="Drag to move when this narration plays — length never changes"
                      >
                        {bars.map((h, i) => (
                          <div
                            key={i}
                            className="flex-1 rounded-full bg-studio-accent2"
                            style={{ height: `${h * 100}%` }}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center">
                        <span className="text-[9.5px] text-studio-muted/50">no audio</span>
                      </div>
                    )}
                    {isDraggingThis && (
                      <span
                        ref={labelElRef}
                        className="absolute -top-5 px-1.5 py-0.5 rounded bg-studio-accent text-studio-primary text-[10px] font-medium whitespace-nowrap z-20 pointer-events-none"
                        style={{
                          transform: `translateX(${Math.max(0, timeToPx(offset) - 6)}px)`,
                        }}
                      >
                        {offset.toFixed(1)}s in
                      </span>
                    )}
                  </div>
                );
              })}
            </RowShell>

            <RowShell
              icon={<Captions size={13} />}
              label="Subtitle"
              height={ROW_HEIGHTS.subtitle}
              totalWidth={layout.totalWidth}
            >
              {layout.items.map((item) => {
                const seg = item.segment;
                return (
                  <div
                    key={seg.id}
                    style={{ left: item.left, width: item.width - 2, top: 1, height: ROW_HEIGHTS.subtitle - 2 }}
                    className="absolute border border-studio-border/70 rounded-md bg-studio-bg/40 px-2 flex items-center"
                  >
                    <span className="text-[10px] text-studio-muted truncate">
                      {seg.subtitle_enabled ? seg.narration_text || "—" : "off"}
                    </span>
                  </div>
                );
              })}
            </RowShell>

            <div
              ref={playheadRef}
              className="absolute top-0 pointer-events-none z-20"
              style={{ left: GUTTER_PX + layoutTimeToPx(playheadTime, layout), height: totalHeight }}
            >
              <div className="w-px h-full bg-studio-accent" />
              <div className="absolute -top-0.5 -left-[5px] w-[11px] h-[11px] rotate-45 bg-studio-accent" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
