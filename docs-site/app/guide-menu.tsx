"use client";

import { useEffect, useRef } from "react";

export default function GuideMenu({ title, items }: { title: string; items: { id: string; title: string }[] }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) menu.current.open = false;
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && menu.current?.open) {
        menu.current.open = false;
        menu.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  return <details className="guide-menu" ref={menu}>
    <summary>{title}</summary>
    <div className="menu-links">
      {items.map(({ id, title }) => <a key={id} href={`#${id}`} onClick={() => {
        if (menu.current) menu.current.open = false;
      }}>{title}</a>)}
    </div>
  </details>;
}
