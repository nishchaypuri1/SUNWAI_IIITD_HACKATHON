import type { Metadata, Viewport } from "next";
import { Anek_Latin, Mukta } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import { QueryProvider } from "@/components/query-provider";
import "./globals.css";

const anek = Anek_Latin({ variable: "--font-display", subsets: ["latin"], display: "swap" });
const mukta = Mukta({ variable: "--font-body", subsets: ["latin", "devanagari"], weight: ["400", "500", "600", "700"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "Sunwai — a clearer complaint path", template: "%s · Sunwai" },
  description: "Understand your consumer complaint path, see the rules behind each date, and prepare a form you submit yourself.",
  applicationName: "Sunwai",
  keywords: ["consumer complaint", "grievance", "India", "RBI Ombudsman"],
  robots: { index: true, follow: true },
};

export const viewport: Viewport = { themeColor: "#f2f4f7", width: "device-width", initialScale: 1, maximumScale: 5 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" className={`${anek.variable} ${mukta.variable}`}><body><QueryProvider><AppShell>{children}</AppShell></QueryProvider></body></html>;
}
