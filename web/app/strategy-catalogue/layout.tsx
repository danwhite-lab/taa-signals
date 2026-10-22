import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Strategy Catalogue" };

export default function StrategyCatalogueLayout({ children }: { children: ReactNode }) {
  return children;
}
