"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import navigation from "../content/navigation.json";
import TestLoginBadge from "./TestLoginBadge";

const normalizedPath = (path: string) => path.replace(/\/$/, "") || "/";

export default function TopNavigation() {
  const pathname = usePathname();
  const [isOpen, setIsOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const firstLink = useRef<HTMLAnchorElement>(null);
  const previousPath = useRef(pathname);

  useEffect(() => {
    if (!window.matchMedia) return;
    const query = window.matchMedia("(max-width: 760px)");
    const updateViewport = () => setIsMobile(query.matches);
    updateViewport();
    query.addEventListener("change", updateViewport);
    return () => query.removeEventListener("change", updateViewport);
  }, []);

  useEffect(() => {
    if (previousPath.current !== pathname) {
      previousPath.current = pathname;
      setIsOpen(false);
    }
  }, [pathname]);

  useEffect(() => {
    if (!isOpen) return;
    firstLink.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isOpen]);

  const closeMenu = () => setIsOpen(false);

  return (
    <>
      <header className="mobile-nav-header">
        <div className="brand">{navigation.brand} <TestLoginBadge /></div>
        <button
          ref={menuButton}
          className="mobile-nav-toggle"
          type="button"
          aria-label={navigation.openMenu}
          aria-expanded={isOpen}
          aria-controls="primary-navigation-drawer"
          onClick={() => setIsOpen(true)}
        >
          <span aria-hidden="true">☰</span>
        </button>
      </header>
      {isOpen && <button className="sidebar-overlay" type="button" aria-label={navigation.closeMenu} onClick={closeMenu} />}
      <aside
        id="primary-navigation-drawer"
        className={`app-sidebar${isOpen ? " is-open" : ""}`}
        aria-hidden={isMobile && !isOpen ? true : undefined}
        inert={isMobile && !isOpen ? true : undefined}
      >
        <div className="sidebar-heading">
          <div className="brand">{navigation.brand} <TestLoginBadge /></div>
          <button className="sidebar-close" type="button" aria-label={navigation.closeMenu} onClick={() => { closeMenu(); menuButton.current?.focus(); }}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <nav aria-label={navigation.ariaLabel} className="primary-nav">
          {navigation.pages.map((page, index) => (
            <Link
              ref={index === 0 ? firstLink : undefined}
              key={page.href}
              href={page.href}
              aria-current={normalizedPath(pathname) === normalizedPath(page.href) ? "page" : undefined}
              onClick={closeMenu}
            >
              {page.label}
            </Link>
          ))}
        </nav>
      </aside>
    </>
  );
}
