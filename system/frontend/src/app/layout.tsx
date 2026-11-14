import type { Metadata } from "next";
import { Fraunces, Manrope } from "next/font/google";
import { SessionPresence } from "@/components/SessionPresence";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
  display: "swap",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nesto Housing Director",
  description: "AI-powered real estate video director",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${manrope.variable} ${fraunces.variable}`}>
      <body className="min-h-screen bg-studio-bg text-studio-text antialiased font-sans">
        <SessionPresence />
        {children}
      </body>
    </html>
  );
}
