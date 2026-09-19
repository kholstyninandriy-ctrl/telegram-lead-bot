import type { Metadata } from "next";
import { agency } from "@/config/agency";
import "./globals.css";

export const metadata: Metadata = {
  title: `${agency.name} — AI Receptionist`,
  description: `Live chat receptionist for ${agency.name}.`,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={{ ["--brand" as string]: agency.brandColor }}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
