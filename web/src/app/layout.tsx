import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Finney · Your finance teammate",
  description: "Source-backed finance operations for hackathon teams.",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="stylesheet" href="/brand/mascot.css" />
      </head>
      <body>{children}</body>
    </html>
  );
}
