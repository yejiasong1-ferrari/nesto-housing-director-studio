"use client";

import Image from "next/image";

interface Props {
  /** landing: logo + title only; header: compact row */
  size?: "landing" | "header";
  subtitle?: string | null;
}

export default function BrandMark({
  size = "header",
  subtitle = null,
}: Props) {
  if (size === "landing") {
    return (
      <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-6 w-full">
        <Image
          src="/logo.png"
          alt="Nesto"
          width={168}
          height={146}
          className="h-24 sm:h-[118px] w-auto object-contain shrink-0"
          priority
        />
        <p className="max-w-[15rem] sm:max-w-none font-display text-center sm:text-left text-[1.45rem] sm:text-4xl md:text-[2.55rem] font-semibold text-studio-primary tracking-tight leading-tight sm:leading-none">
          Nesto Housing Director
        </p>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 min-w-0">
      <Image
        src="/logo.png"
        alt="Nesto"
        width={88}
        height={77}
        className="h-14 w-auto object-contain shrink-0"
        priority
      />
      <div className="min-w-0">
        <p className="font-display text-[18px] font-semibold text-studio-primary leading-tight tracking-tight">
          Nesto Housing Director
        </p>
        {subtitle && (
          <p className="text-[11px] text-studio-muted leading-tight mt-0.5 truncate">
            {subtitle}
          </p>
        )}
      </div>
    </div>
  );
}
