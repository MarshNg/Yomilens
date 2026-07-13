import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "YomiLens Popup Dictionary Docs",
  description:
    "Learn how to install, configure, and use the YomiLens popup dictionary add-on for Anki.",
  icons: {
    icon: "./favicon.svg",
    shortcut: "./favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
