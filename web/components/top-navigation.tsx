"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const pages = ["Today", "Signals", "Portfolio", "Rebalance Holdings", "Backtest", "Research", "Compare", "Rules"];

export default function TopNavigation() {
  const pathname = usePathname();
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">TAA Signals <span className="preview-badge">Preview</span></div>
        <nav aria-label="Primary navigation" className="primary-nav">
          {pages.map((page) => ["Rules", "Portfolio", "Signals", "Backtest", "Rebalance Holdings"].includes(page) ? (
            <Link key={page} href={`/${page.toLowerCase().replaceAll(" ", "-")}/`} aria-current={pathname.replace(/\/$/, "") === `/${page.toLowerCase().replaceAll(" ", "-")}` ? "page" : undefined}>
              {page}
            </Link>
          ) : (
            <span key={page} aria-disabled="true" title="Not migrated yet">{page}</span>
          ))}
        </nav>
      </div>
    </header>
  );
}
