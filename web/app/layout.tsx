import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import TopNavigation from "../components/top-navigation";
import AuthGate from "../components/AuthGate";

export const metadata: Metadata = {
  title: "TAA Signals — migration preview",
  description: "Strategy catalogue from the existing TAA Signals Python engine.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/taa-signals-icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/taa-signals-icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  appleWebApp: { capable: true, title: "TAA Signals", statusBarStyle: "default" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TopNavigation />
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
