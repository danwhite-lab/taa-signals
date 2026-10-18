import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import TopNavigation from "../components/top-navigation";

export const metadata: Metadata = {
  title: "TAA Signals — migration preview",
  description: "Strategy catalogue from the existing TAA Signals Python engine.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TopNavigation />
        {children}
      </body>
    </html>
  );
}
