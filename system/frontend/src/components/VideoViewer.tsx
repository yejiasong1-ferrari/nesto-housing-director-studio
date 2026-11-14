"use client";

import { useEffect, useState, type ReactNode, type RefObject } from "react";

export type PreviewMode = "final" | "draft" | "source";

interface Props {
  sourceUrl: string;
  draftUrl: string | null;
  finalUrl: string | null;
  refreshKey: number;
  mode: PreviewMode;
  onModeChange: (mode: PreviewMode) => void;
  videoRef: RefObject<HTMLVideoElement>;
  onLoadedMetadata?: () => void;
  /** Compact chip shown to the right of the preview mode tabs (non-blocking). */
  trailing?: ReactNode;
}

export default function VideoViewer({
  sourceUrl,
  draftUrl,
  finalUrl,
  refreshKey,
  mode,
  onModeChange,
  videoRef,
  onLoadedMetadata,
  trailing,
}: Props) {
  const [loadState, setLoadState] = useState<
    "loading" | "ready" | "waiting" | "error"
  >("loading");
  const [retryKey, setRetryKey] = useState(0);
  const available: { key: PreviewMode; label: string; url: string }[] = [
    ...(finalUrl ? [{ key: "final" as PreviewMode, label: "Final cut", url: finalUrl }] : []),
    ...(draftUrl ? [{ key: "draft" as PreviewMode, label: "Draft preview", url: draftUrl }] : []),
    { key: "source" as PreviewMode, label: "Original footage", url: sourceUrl },
  ];
  const current = available.find((a) => a.key === mode) ?? available[0];

  useEffect(() => {
    setLoadState("loading");
  }, [current.url, refreshKey]);

  return (
    <section className="flex flex-col w-full min-w-0 rounded-lg border border-studio-border bg-studio-panel p-3 studio-panel-topline">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-studio-muted">
            Preview
          </p>
          <p className="text-sm font-medium text-studio-primary">{current.label}</p>
        </div>
        {trailing ? <div className="shrink-0">{trailing}</div> : null}
      </div>
      <div className="relative w-full rounded-lg overflow-hidden border border-studio-accent/45 bg-studio-video">
        <video
          ref={videoRef}
          key={`${current.url}-${refreshKey}-${retryKey}`}
          src={current.url}
          controls
          playsInline
          preload="metadata"
          onLoadStart={() => setLoadState("loading")}
          onLoadedMetadata={() => {
            setLoadState("ready");
            onLoadedMetadata?.();
          }}
          onCanPlay={() => setLoadState("ready")}
          onWaiting={() => setLoadState("waiting")}
          onError={() => setLoadState("error")}
          className="w-full max-h-[52vh] object-contain bg-studio-video"
        />
        <span className="absolute top-2 left-2 px-2 py-0.5 rounded text-[10px] font-medium bg-black/55 text-white border border-studio-accent/30">
          {current.label.toUpperCase()}
        </span>
        {loadState !== "ready" ? (
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 bg-black/70 px-3 py-2 text-xs text-white">
            <span>
              {loadState === "error"
                ? "Video could not be loaded."
                : loadState === "waiting"
                  ? "Buffering video…"
                  : "Loading video details…"}
            </span>
            {loadState === "error" ? (
              <button
                type="button"
                className="underline"
                onClick={() => {
                  setLoadState("loading");
                  setRetryKey((n) => n + 1);
                }}
              >
                Retry
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="flex items-center justify-between gap-3 mt-2.5 min-h-[32px]">
        <div className="flex gap-1.5 flex-wrap">
          {available.map((a) => (
            <button
              key={a.key}
              onClick={() => onModeChange(a.key)}
              className={`px-3 py-1 rounded-full text-[11px] border ${
                mode === a.key
                  ? "bg-studio-accent text-studio-primary border-studio-accent font-medium"
                  : "bg-studio-panel2 text-studio-muted border-studio-border hover:text-studio-primary"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
