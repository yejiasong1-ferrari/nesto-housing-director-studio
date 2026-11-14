"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Clock3, KeyRound, Loader2, ShieldCheck } from "lucide-react";
import BrandMark from "@/components/BrandMark";
import { verifyInviteCode } from "@/lib/saasApi";
import { clearSessionCookie, getOrCreateDeviceId, setSessionCookie } from "@/lib/session";

const heroWords = "Real estate walkthroughs, directed like a tour.".split(" ");
const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export default function InvitePage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [verified, setVerified] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [forceLogoutOpen, setForceLogoutOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const reason = new URLSearchParams(window.location.search).get("reason");
    if (reason === "revoked" || reason === "expired" || reason === "session") {
      clearSessionCookie();
    }
    if (reason === "revoked") {
      setForceLogoutOpen(true);
      window.history.replaceState({}, "", "/invite");
    } else if (reason === "expired" || reason === "session") {
      window.history.replaceState({}, "", "/invite");
    }
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = code.trim().toUpperCase();
    if (!trimmed) {
      setError("Please enter an invite code.");
      return;
    }
    setSubmitting(true);
    try {
      const device_id = getOrCreateDeviceId();
      const result = await verifyInviteCode({ code: trimmed, device_id });
      if (!result.success || !result.token) {
        const msg = result.message || "Invalid code";
        if (msg === "Already used") setError("This invite code has already been used.");
        else if (msg === "Expired") setError("This invite code has expired.");
        else if (msg === "Revoked")
          setError("This invite was revoked by an administrator.");
        else setError("Invalid invite code.");
        return;
      }
      setSessionCookie(result.token, result.expires);
      setVerified(true);
      await wait(420);
      setLeaving(true);
      await wait(520);
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      if (!verified) setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center studio-shell-bg px-4 sm:px-6 py-12">
      <div className="relative w-full max-w-5xl">
        <div className="invite-brand-sequence">
          <BrandMark size="landing" />
        </div>
        <div className="mt-7 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_25rem] gap-5 items-stretch">
          <section
            className={`p-1 md:py-7 md:pr-6 flex flex-col justify-center ${
              leaving ? "studio-exit-left" : "studio-glide-left"
            }`}
            style={{ animationDelay: leaving ? "0ms" : "320ms" }}
          >
            <div>
              <p
                className="text-[11px] uppercase tracking-wide text-studio-muted studio-reveal-up"
                style={{ animationDelay: "420ms" }}
              >
                Private beta
              </p>
              <h1 className="mt-2 font-display text-3xl md:text-4xl font-semibold text-studio-primary tracking-tight">
                {heroWords.map((word, index) => (
                  <span
                    key={`${word}-${index}`}
                    className="inline-block studio-reveal-up mr-[0.24em]"
                    style={{ animationDelay: `${500 + index * 46}ms` }}
                  >
                    {word}
                  </span>
                ))}
              </h1>
              <p
                className="mt-3 max-w-xl text-sm leading-6 text-studio-muted studio-reveal-up"
                style={{ animationDelay: "820ms" }}
              >
                Upload a property video, choose the narration language, then review the cut in Studio.
              </p>
            </div>
            <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
              {[
                [KeyRound, "Invite only"],
                [Clock3, "3-hour access"],
                [ShieldCheck, "One device"],
              ].map(([Icon, label], index) => (
                <div
                  key={String(label)}
                  className="border-t border-studio-border px-1 py-3 studio-reveal-up"
                  style={{ animationDelay: `${900 + index * 70}ms` }}
                >
                  <Icon size={16} className="mb-2 text-studio-accent" />
                  <p className="font-medium text-studio-primary">{String(label)}</p>
                </div>
              ))}
            </div>
          </section>

          <div
            className={`rounded-lg border border-studio-border bg-studio-panel studio-panel-topline p-7 space-y-6 ${
              leaving ? "studio-exit-right" : "studio-glide-right"
            }`}
            style={{ animationDelay: leaving ? "0ms" : "720ms" }}
          >
            <div className="text-center space-y-1">
              <p className="text-[11px] uppercase tracking-wide text-studio-muted">
                Private beta
              </p>
              <h1 className="font-display text-2xl font-semibold text-studio-primary tracking-tight">
                Enter invite code
              </h1>
            <p className="mx-auto max-w-[18rem] text-sm leading-5 text-studio-muted">
                Access lasts 3 hours after activation. Each code works on one device.
              </p>
            </div>

            <form onSubmit={onSubmit} className="space-y-4">
              <label className="block space-y-1.5">
                <span className="text-[11px] uppercase tracking-wide text-studio-muted">
                  Invite code
                </span>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="NESTO-XXXXXXXX"
                  autoComplete="off"
                spellCheck={false}
                className="w-full rounded-lg border border-studio-border bg-studio-panel2 px-4 py-3 text-sm text-studio-primary tracking-wider uppercase placeholder:normal-case placeholder:tracking-normal focus:outline-none focus:border-studio-accent focus:bg-white"
                  disabled={submitting || verified}
                />
              </label>

              {error ? (
                <p className="text-sm text-studio-danger" role="alert">
                  {error}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={submitting || verified}
                className={`w-full flex items-center justify-center gap-2 rounded-lg text-studio-primary text-sm font-medium py-3 disabled:opacity-90 motion-fast ${
                  verified
                    ? "bg-studio-accent2 text-white"
                    : "bg-studio-accent hover:bg-studio-accentHover"
                }`}
              >
                {verified ? (
                  <>
                    <CheckCircle2 size={16} />
                    Invitation verified
                  </>
                ) : submitting ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Verifying…
                  </>
                ) : (
                  "Verify"
                )}
              </button>
            </form>
          </div>
        </div>
      </div>

      {forceLogoutOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-6 bg-studio-primary/45 backdrop-blur-[2px]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="force-logout-title"
        >
          <div className="w-full max-w-md rounded-lg border border-studio-border bg-studio-panel shadow-panel p-7 space-y-4">
            <p className="text-[11px] uppercase tracking-wide text-studio-muted">
              Session ended
            </p>
            <h2
              id="force-logout-title"
              className="font-display text-2xl text-studio-primary tracking-tight"
            >
              You’ve been signed out
            </h2>
            <p className="text-sm text-studio-muted leading-relaxed">
              An administrator ended this beta session (force logout). Your invite
              access is no longer active on this device. Contact Nesto if you need a
              new invite code.
            </p>
            <button
              type="button"
              onClick={() => setForceLogoutOpen(false)}
              className="w-full rounded-lg bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium py-3 transition-colors"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
