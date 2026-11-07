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
  const drawer = useRef<HTMLElement>(null);
  const restoreMenuFocus = useRef(false);
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
    const content = document.querySelector<HTMLElement>(".app-content");
    const backgroundIsInert = isMobile && isOpen;
    content?.toggleAttribute("inert", backgroundIsInert);
    return () => content?.removeAttribute("inert");
  }, [isMobile, isOpen]);

  useEffect(() => {
    if (!isOpen && restoreMenuFocus.current) {
      restoreMenuFocus.current = false;
      menuButton.current?.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !isMobile) return;
    firstLink.current?.focus();
    const containFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(drawer.current?.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]") ?? []);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!drawer.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", containFocus);
    return () => document.removeEventListener("keydown", containFocus);
  }, [isMobile, isOpen]);

  function closeMenu() {
    restoreMenuFocus.current = true;
    setIsOpen(false);
  }

  return (
    <>
      <header className="mobile-nav-header" inert={isMobile && isOpen ? true : undefined}>
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
      {isOpen && <button className="sidebar-overlay" type="button" tabIndex={-1} aria-label={navigation.closeMenu} onClick={closeMenu} />}
      <aside
        ref={drawer}
        id="primary-navigation-drawer"
        className={`app-sidebar${isOpen ? " is-open" : ""}`}
        aria-hidden={isMobile && !isOpen ? true : undefined}
        inert={isMobile && !isOpen ? true : undefined}
      >
        <div className="sidebar-heading">
          <div className="brand">{navigation.brand} <TestLoginBadge /></div>
          <button className="sidebar-close" type="button" aria-label={navigation.closeMenu} onClick={closeMenu}>
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
