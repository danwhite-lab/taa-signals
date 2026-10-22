"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import TestLoginBadge from "./TestLoginBadge";

const pages = ["Today", "Signals", "Portfolio", "Rebalance Holdings", "Backtest", "Research", "Compare", "Strategy Catalogue"];

export default function TopNavigation() {
  const pathname = usePathname();
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">Signalboard <TestLoginBadge /></div>
        <nav aria-label="Primary navigation" className="primary-nav">
          {pages.map((page) => (
            <Link key={page} href={`/${page.toLowerCase().replaceAll(" ", "-")}/`} aria-current={pathname.replace(/\/$/, "") === `/${page.toLowerCase().replaceAll(" ", "-")}` ? "page" : undefined}>
              {page}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
