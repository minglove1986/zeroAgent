"use client";
import { useEffect, useState } from "react";

export function ThemeSwitcher() {
  const [theme, setTheme] = useState<"light" | "dark" | "auto">("auto");

  useEffect(() => {
    const saved = localStorage.getItem("zeroagent-theme") || "auto";
    setTheme(saved as any);
    apply(saved);
  }, []);

  function apply(t: string) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  }

  function toggle() {
    const next = theme === "auto" ? "dark" : theme === "light" ? "auto" : "light";
    setTheme(next);
    localStorage.setItem("zeroagent-theme", next);
    apply(next);
  }

  return (
    <button className="btn btn-outline" onClick={toggle} title="切换主题">
      🌓
    </button>
  );
}