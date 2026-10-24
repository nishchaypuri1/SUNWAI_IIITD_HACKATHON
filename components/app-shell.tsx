"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Activity, ArrowUpRight, CalendarDays, Check, CircleHelp, Clock3, Languages, Moon, RotateCcw, SlidersHorizontal, Sun, X } from "lucide-react";
import { advanceClock, getClock, getRunOutcome, getSandboxAttempts, isMock, resetSandboxAttempts, setRunOutcome } from "@/lib/api";
import { copy, localeFor } from "@/lib/content";
import type { DemoClock, Language } from "@/lib/types";

type Preferences = { language: Language; setLanguage: (language: Language) => void; theme: "light" | "dark"; toggleTheme: () => void; t: (key: string) => string };
const PrefsContext = createContext<Preferences | null>(null);
export function usePrefs() { const value = useContext(PrefsContext); if (!value) throw new Error("usePrefs must be used inside AppShell"); return value; }

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [language, setLanguageState] = useState<Language>("en");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [demoOpen, setDemoOpen] = useState(false);
  const [clock, setClock] = useState<DemoClock | null>(null);
  const [attempts, setAttempts] = useState({ review_reached: 0, submit_clicked: 0 });
  const [runOutcome, setRunOutcomeState] = useState<"success" | "otp" | "failure">("success");
  const [visualTier, setVisualTier] = useState<"full" | "lite" | "off">("full");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    try { const savedLanguage = localStorage.getItem("sunwai.language"); if (savedLanguage === "en" || savedLanguage === "hi" || savedLanguage === "hinglish") setLanguageState(savedLanguage); const savedTheme = localStorage.getItem("sunwai.theme"); if (savedTheme === "light" || savedTheme === "dark") setTheme(savedTheme); const savedVisuals = localStorage.getItem("sunwai.visuals"); if (savedVisuals === "full" || savedVisuals === "lite" || savedVisuals === "off") setVisualTier(savedVisuals); } catch { /* local preferences are optional */ }
    const shortcuts = (event: KeyboardEvent) => { if (event.key === "Escape") setDemoOpen(false); if (event.shiftKey && event.key.toLowerCase() === "d" && !pathname.startsWith("/sandbox")) { event.preventDefault(); setDemoOpen((value) => !value); } };
    window.addEventListener("keydown", shortcuts); return () => window.removeEventListener("keydown", shortcuts);
  }, [pathname]);
  useEffect(() => { document.documentElement.dataset.theme = theme; document.documentElement.lang = localeFor(language); }, [theme, language]);
  useEffect(() => { if (pathname.startsWith("/sandbox")) return; void getClock().then(setClock); void getSandboxAttempts().then(({ review_reached, submit_clicked }) => setAttempts({ review_reached, submit_clicked })).catch(() => undefined); setRunOutcomeState(getRunOutcome()); }, [pathname]);
  useEffect(() => { const refreshAttempts = () => { if (!pathname.startsWith("/sandbox")) void getSandboxAttempts().then(({ review_reached, submit_clicked }) => setAttempts({ review_reached, submit_clicked })); }; window.addEventListener("sunwai:sandbox-attempts", refreshAttempts); window.addEventListener("storage", refreshAttempts); return () => { window.removeEventListener("sunwai:sandbox-attempts", refreshAttempts); window.removeEventListener("storage", refreshAttempts); }; }, [pathname]);

  const setLanguage = useCallback((value: Language) => { setLanguageState(value); try { localStorage.setItem("sunwai.language", value); } catch { /* local preferences are optional */ } }, []);
  const toggleTheme = useCallback(() => { setTheme((value) => { const next = value === "light" ? "dark" : "light"; try { localStorage.setItem("sunwai.theme", next); } catch { /* local preferences are optional */ } return next; }); }, []);
  const changeVisualTier = (value: "full" | "lite" | "off") => { setVisualTier(value); try { localStorage.setItem("sunwai.visuals", value); } catch { /* local preferences are optional */ } window.dispatchEvent(new CustomEvent("sunwai:visuals", { detail: value })); };
  const t = useCallback((key: string) => (copy[localeFor(language)] as Record<string, string>)[key] || (copy.en as Record<string, string>)[key] || key, [language]);
  const prefs = useMemo(() => ({ language, setLanguage, theme, toggleTheme, t }), [language, setLanguage, theme, toggleTheme, t]);
  const sandbox = pathname.startsWith("/sandbox");
  const refreshDemo = async () => { const [nextClock, nextAttempts] = await Promise.all([getClock(), getSandboxAttempts()]); setClock(nextClock); setAttempts({ review_reached: nextAttempts.review_reached, submit_clicked: nextAttempts.submit_clicked }); };
  const changeClock = async (days: number | "reset") => { setWorking(true); try { setClock(await advanceClock(days)); } finally { setWorking(false); } };

  return <PrefsContext.Provider value={prefs}>
    {!sandbox && <a className="skip-link" href="#main-content">Skip to content</a>}
    {!sandbox && <header className="app-header">
      <Link href="/" className="brand" aria-label="Sunwai home"><span className="brand-mark"><span /><span /><span /></span><span className="brand-name">sunwai</span><span className="brand-hi">सुनवाई</span></Link>
      <nav className="header-nav" aria-label="Main navigation"><Link href="/cases" className={pathname === "/cases" ? "active" : ""}>{t("navCases")}</Link><Link href="/about" className={pathname === "/about" ? "active" : ""}>{t("navAbout")}</Link></nav>
      <div className="header-tools">
        <span className={isMock() ? "connection-chip mock" : "connection-chip live"} title={isMock() ? "Using local demo data. No backend is required." : "Connected to the Sunwai API."}><span className="connection-dot" />{isMock() ? t("mock") : t("live")}</span>
        <div className="language-switch" aria-label={t("language")}><Languages size={15} aria-hidden="true"/><select value={language} onChange={(event) => setLanguage(event.target.value as Language)} aria-label={t("language")}><option value="en">EN</option><option value="hi">हिंदी</option><option value="hinglish">Hi + En</option></select></div>
        <button className="icon-button theme-button" onClick={toggleTheme} aria-label={t("theme")} title={t("theme")}>{theme === "light" ? <Moon size={17}/> : <Sun size={17}/>}</button>
      </div>
    </header>}
    <div id="main-content" className={sandbox ? "app-content sandbox-shell" : "app-content"}>{children}</div>
    {!sandbox && <footer className="app-footer"><p>{t("footerDisclaimer")}</p><Link href="/about">{t("footerAbout")} <ArrowUpRight size={13}/></Link></footer>}
    {!sandbox && <>
      <button className={`demo-toggle ${demoOpen ? "is-open" : ""} ${pathname.startsWith("/case/") ? "above-mobile-nav" : ""}`} onClick={() => { setDemoOpen((value) => !value); void refreshDemo(); }} aria-expanded={demoOpen} aria-controls="demo-panel"><span className="demo-live-indicator"/><span>{t("demoControls")}</span><span className="shortcut">⇧ D</span></button>
      {demoOpen && <aside id="demo-panel" className={`demo-panel ${pathname.startsWith("/case/") ? "above-mobile-nav" : ""}`} aria-label={t("demoControls")}>
        <div className="panel-heading"><div><span className="eyebrow">SUNWAI · WALKTHROUGH</span><h2>{t("demoControls")}</h2></div><button className="icon-button" onClick={() => setDemoOpen(false)} aria-label={t("close")}><X size={18}/></button></div>
        <div className="panel-mode"><span className="connection-dot"/>{isMock() ? "Local demo adapter" : "Connected API"}<span className="panel-mode-state">{isMock() ? "No backend needed" : "Live"}</span></div>
        <section className="panel-section"><div className="panel-section-title"><Clock3 size={15}/><h3>{t("clock")}</h3></div><div className="clock-display"><CalendarDays size={17}/><strong>{clock ? formatDemoDate(clock.today, language) : "—"}</strong>{clock?.simulated && <span className="simulated-pill">{t("simulated")}</span>}</div><div className="clock-actions"><button onClick={() => void changeClock(1)} disabled={working}>{t("plusDay")}</button><button onClick={() => void changeClock(7)} disabled={working}>{t("plusWeek")}</button><button className="accent" onClick={() => void changeClock(30)} disabled={working}>{t("plusMonth")}</button><button className="reset-clock" onClick={() => void changeClock("reset")} disabled={working} title={t("resetClock")}><RotateCcw size={14}/></button></div><p className="panel-hint">{clock?.simulated ? "Dates are simulated for this demo." : "Use the demo clock to move a case forward."}</p></section>
        <section className="panel-section"><div className="panel-section-title"><Activity size={15}/><h3>{t("runOutcome")}</h3></div><div className="outcome-select" role="group" aria-label={t("runOutcome")}><button className={runOutcome === "success" ? "selected" : ""} onClick={() => { setRunOutcomeState("success"); setRunOutcome("success"); }}><Check size={13}/>{t("outcomeSuccess")}</button><button className={runOutcome === "otp" ? "selected" : ""} onClick={() => { setRunOutcomeState("otp"); setRunOutcome("otp"); }}>{t("outcomeOtp")}</button><button className={runOutcome === "failure" ? "selected" : ""} onClick={() => { setRunOutcomeState("failure"); setRunOutcome("failure"); }}>{t("outcomeFailure")}</button></div><p className="panel-hint">Set the next agent run to rehearse the hand-off and retry paths.</p></section>
        <section className="panel-section"><div className="panel-section-title"><SlidersHorizontal size={15}/><h3>{t("visuals")}</h3></div><label className="visual-tier-select"><span>{t("visualQuality")}</span><select value={visualTier} onChange={(event) => changeVisualTier(event.target.value as "full" | "lite" | "off")}><option value="full">{t("visualFull")}</option><option value="lite">{t("visualLite")}</option><option value="off">{t("visualOff")}</option></select></label><p className="panel-hint">Reduced motion and unavailable WebGL automatically use the static staircase.</p></section>
        <section className="panel-section"><div className="panel-section-title"><CircleHelp size={15}/><h3>{t("counters")}</h3></div><div className="counter-grid"><div><strong>{attempts.review_reached}</strong><span>{t("reviewCount")}</span></div><div><strong className={attempts.submit_clicked === 0 ? "zero" : "danger-number"}>{attempts.submit_clicked}</strong><span>{t("submitCount")}</span></div></div><div className="counter-foot"><span className={attempts.submit_clicked === 0 ? "safe-label" : "unsafe-label"}>{attempts.submit_clicked === 0 ? t("submitClicksZero") : `${attempts.submit_clicked} submit clicks`}</span><button className="text-button" onClick={async () => { await resetSandboxAttempts(); await refreshDemo(); }}>{t("resetCounters")}</button></div></section>
        <div className="panel-footer"><span>Shift + D</span><span>ESC to close</span></div>
      </aside>}
    </>}
  </PrefsContext.Provider>;
}

function formatDemoDate(value: string, language: Language) { const date = new Date(`${value}T12:00:00+05:30`); return new Intl.DateTimeFormat(language === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short", year: "numeric" }).format(date); }
