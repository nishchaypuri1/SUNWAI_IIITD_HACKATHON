"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowRight, AudioLines, Check, ChevronRight, FileImage, FileText, Mic, Paperclip, ShieldCheck, Sparkles, X } from "lucide-react";
import { ApiError, createCase, getScenarios, isMock } from "@/lib/api";
import { scenarios as fallbackScenarios } from "@/lib/content";
import type { Language, Scenario } from "@/lib/types";
import { usePrefs } from "@/components/app-shell";

const HeroScene = dynamic(() => import("@/components/hero-scene").then((module) => module.HeroScene), { ssr: false, loading: () => null });

export function HomePage() {
  const { language, setLanguage, t } = usePrefs(); const router = useRouter();
  const [text, setText] = useState(""); const [files, setFiles] = useState<File[]>([]); const [fileError, setFileError] = useState("");
  const [busy, setBusy] = useState(false); const [stage, setStage] = useState(0); const [error, setError] = useState(""); const [scenarios, setScenarios] = useState<Scenario[]>(fallbackScenarios); const [listening, setListening] = useState(false);
  const [visualTier, setVisualTier] = useState<"full" | "lite" | "off">("full"); const [reducedMotion, setReducedMotion] = useState(false); const [showScene, setShowScene] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null); const heroArtRef = useRef<HTMLDivElement>(null); const recognition = useRef<{ stop: () => void } | null>(null);
  useEffect(() => { void getScenarios().then(setScenarios).catch(() => undefined); }, []);
  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)"); let tier: "full" | "lite" | "off" = "full";
    try { const stored = localStorage.getItem("sunwai.visuals"); if (stored === "full" || stored === "lite" || stored === "off") tier = stored; } catch { /* visual preference is optional */ }
    let hasWebGL2 = false;
    try { const canvas = document.createElement("canvas"); const context = canvas.getContext("webgl2"); hasWebGL2 = Boolean(context); context?.getExtension("WEBGL_lose_context")?.loseContext(); } catch { /* the CSS scene remains available */ }
    setVisualTier(tier); setReducedMotion(motion.matches);
    const reveal = () => { if (hasWebGL2 && !motion.matches && tier !== "off") setShowScene(true); else setShowScene(false); };
    const observer = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) reveal(); }, { rootMargin: "120px" }) : null;
    if (heroArtRef.current && observer) observer.observe(heroArtRef.current); else reveal();
    const visuals = (event: Event) => { const detail = (event as CustomEvent<"full" | "lite" | "off">).detail; tier = detail; setVisualTier(detail); if (!motion.matches && detail !== "off") reveal(); else setShowScene(false); };
    motion.addEventListener("change", reveal); window.addEventListener("sunwai:visuals", visuals);
    return () => { observer?.disconnect(); motion.removeEventListener("change", reveal); window.removeEventListener("sunwai:visuals", visuals); };
  }, []);

  const selectScenario = (scenario: Scenario) => { setText(scenario.text); setLanguage(scenario.language); setError(""); };
  const addFiles = (next: FileList | null) => {
    if (!next) return; setFileError("");
    const candidate = Array.from(next);
    if (files.length + candidate.length > 3) { setFileError("Choose up to 3 images for this case."); return; }
    if (candidate.some((file) => !["image/jpeg", "image/png", "image/webp"].includes(file.type))) { setFileError("Use a JPG, PNG or WebP image."); return; }
    if (candidate.some((file) => file.size > 5 * 1024 * 1024)) { setFileError("Each image must be 5 MB or smaller."); return; }
    setFiles((current) => [...current, ...candidate]);
  };
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (text.trim().length < 10) { setError("Add a little more detail so we can understand what happened."); return; }
    setBusy(true); setError(""); setStage(0);
    const steps = [500, 1300]; const timers = steps.map((time, index) => window.setTimeout(() => setStage(index + 1), time));
    try { const item = await createCase(text.trim(), language, files); timers.forEach(window.clearTimeout); setStage(3); await new Promise((resolve) => window.setTimeout(resolve, 380)); router.push(`/case/${item.id}`); }
    catch (issue) { timers.forEach(window.clearTimeout); setError(issue instanceof ApiError ? issue.message : "We couldn’t read this message. Please try again."); setBusy(false); }
  };
  const toggleVoice = () => {
    if (listening) { recognition.current?.stop(); setListening(false); return; }
    const windowWithSpeech = window as Window & { SpeechRecognition?: new () => { lang: string; interimResults: boolean; onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string }; isFinal: boolean } } }) => void) | null; onend: (() => void) | null; start: () => void; stop: () => void }; webkitSpeechRecognition?: new () => { lang: string; interimResults: boolean; onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string }; isFinal: boolean } } }) => void) | null; onend: (() => void) | null; start: () => void; stop: () => void } };
    const Speech = windowWithSpeech.SpeechRecognition || windowWithSpeech.webkitSpeechRecognition;
    if (!Speech) return;
    const active = new Speech(); active.lang = language === "hi" ? "hi-IN" : "en-IN"; active.interimResults = false;
    active.onresult = (event) => { const result = event.results[0]?.[0]?.transcript || ""; setText((value) => value ? `${value.trim()} ${result}` : result); };
    active.onend = () => { recognition.current = null; setListening(false); }; recognition.current = active; setListening(true); active.start();
  };
  const speechSupported = typeof window !== "undefined" && Boolean((window as Window & { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown }).SpeechRecognition || (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition);

  return <>
    <main className="home-page">
      <section className="home-hero">
        <div className="hero-copy">
          <div className="hero-kicker"><span className="kicker-line"/>{t("homeEyebrow")}<span className="kicker-mark">✳</span></div>
          <h1>{t("homeTitle").split("\n").map((line, index) => <span key={line}>{line}{index === 0 && <br/>}</span>)}</h1>
          <p className="hero-description">{t("homeDescription")}</p>
          <div className="hero-trust-row"><span><ShieldCheck size={16}/>{t("heroTag")}</span><span className="trust-divider"/><span>{isMock() ? "Private local demo" : "Your information stays with your case"}</span></div>
        </div>
        <div ref={heroArtRef} className={`hero-art ${showScene ? "has-scene" : ""}`} aria-hidden="true">
          {showScene && visualTier !== "off" && <HeroScene tier={visualTier} reducedMotion={reducedMotion}/>}
          <div className="hero-art-halo"/><div className="art-caption"><span className="caption-dot"/> YOUR CASE, STEP BY STEP</div>
          <div className="stair-map">
            <div className="stair-line"/>
            <div className="stair-node node-four"><span>04</span><b>Consumer Commission</b><i/></div>
            <div className="stair-node node-three"><span>03</span><b>Consumer Helpline</b><i/></div>
            <div className="stair-node node-two"><span>02</span><b>RBI Ombudsman</b><i/></div>
            <div className="stair-node node-one"><span>01</span><b>Company grievance</b><i/></div>
            <div className="paper-file"><div className="file-tab">YOUR CASE</div><div className="file-lines"><i/><i/><i/></div><div className="file-stamp">READY<br/>TO BEGIN</div><div className="file-clip"/></div>
            <div className="art-orbit orbit-one"/><div className="art-orbit orbit-two"/>
            <div className="art-pin pin-verified"><Check size={12}/></div><div className="art-pin pin-time">30 <small>days</small></div>
          </div>
          <div className="art-footnote"><span>ONE CLEAR NEXT STEP</span><ArrowDown size={14}/><span>THE REST CAN WAIT</span></div>
        </div>
      </section>

      <section className="intake-section" aria-labelledby="intake-title">
        <div className="intake-heading"><div><span className="eyebrow">START WITH YOUR STORY</span><h2 id="intake-title">{t("intakeLabel")}</h2></div><span className="intake-step">A good first step starts with what you know.</span></div>
        <form className="intake-card" onSubmit={submit} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }}>
          <label className="sr-only" htmlFor="intake-message">{t("intakeLabel")}</label>
          {busy ? <div className="intake-processing" aria-live="polite"><div className="processing-file"><FileText size={26}/><span className="processing-spark">✳</span></div><div className="processing-copy"><strong>{t("reading")}</strong><p>Your message stays open in this case.</p><div className="progress-list">{[t("reading"), t("readingImage"), t("readingFacts")].map((item, index) => <span key={item} className={stage > index ? "done" : stage === index ? "active" : ""}>{stage > index ? <Check size={13}/> : <i/>}{item}</span>)}</div></div><span className="processing-wash"/></div> : <textarea id="intake-message" value={text} onChange={(event) => { setText(event.target.value); if (error) setError(""); }} placeholder={t("placeholder")} maxLength={4000} rows={5} aria-describedby="intake-hint" />}
          {!busy && <div className="intake-meta"><p id="intake-hint">{t("intakeHint")}</p><span className={text.length > 3500 ? "char-count near-limit" : "char-count"}>{text.length > 3500 ? `${text.length}/4,000` : ""}</span></div>}
          {!busy && files.length > 0 && <div className="attachment-strip">{files.map((file, index) => <ImageAttachment key={`${file.name}-${file.lastModified}-${index}`} file={file} onRemove={() => setFiles((value) => value.filter((_, current) => current !== index))} />)}</div>}
          {!busy && fileError && <p className="inline-error" role="alert">{fileError}</p>}
          {!busy && error && <p className="inline-error" role="alert">{error}</p>}
          {!busy && <div className="intake-controls"><div className="intake-left-tools">
            {speechSupported && <button type="button" className={`quiet-tool ${listening ? "listening" : ""}`} onClick={toggleVoice}><span className="voice-icon">{listening ? <AudioLines size={16}/> : <Mic size={16}/>}</span>{listening ? "Listening…" : t("voice")}</button>}
            <button type="button" className="quiet-tool" onClick={() => fileInput.current?.click()}><Paperclip size={16}/>{t("attach")}{files.length > 0 && <span className="file-count">{files.length}</span>}</button>
            <input ref={fileInput} className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => { addFiles(event.target.files); event.currentTarget.value = ""; }} />
          </div><div className="intake-submit-group"><label className="language-select"><span>IN</span><select value={language} onChange={(event) => setLanguage(event.target.value as Language)} aria-label="Language of your story"><option value="hinglish">Hinglish</option><option value="en">English</option><option value="hi">हिंदी</option></select></label><button type="submit" className="button button-primary" disabled={text.trim().length < 10}><span>{t("understand")}</span><ArrowRight size={17}/></button></div></div>}
          {!busy && <div className="image-helper"><span>{t("imageNote")}</span><span className="privacy-mark"><ShieldCheck size={14}/> Private to this case</span></div>}
        </form>
        {!busy && <div className="scenario-row"><span className="scenario-label">{t("scenarioLabel")}</span><div className="scenario-chips">{scenarios.map((scenario) => <button key={scenario.id} className="scenario-chip" type="button" onClick={() => selectScenario(scenario)}><span>{scenario.language === "hi" ? "हि" : scenario.language === "hinglish" ? "Hi" : "En"}</span>{language === "hi" ? scenario.title_hi : scenario.title}<ChevronRight size={14}/></button>)}</div></div>}
      </section>

      <section className="next-section"><div className="next-intro"><span className="eyebrow">A SIMPLE PATH THROUGH A COMPLEX PROCESS</span><h2>{t("howNext")}</h2><p>There’s no need to know the system before you begin.</p><Link href="/about" className="inline-link">See how Sunwai works <ArrowRight size={14}/></Link></div><div className="next-steps"><article><span className="step-icon icon-paper"><FileText size={18}/></span><div><strong>01 · {t("stepUnderstand")}</strong><p>We pick out the details that matter, and ask only what’s missing.</p></div></article><article><span className="step-icon icon-stamp"><ShieldCheck size={18}/></span><div><strong>02 · Check the path</strong><p>Each date comes with the rule source and the moment it was checked.</p></div></article><article><span className="step-icon icon-arrow"><ArrowRight size={18}/></span><div><strong>03 · You stay in control</strong><p>The agent can prepare a form. You decide whether and when to submit.</p></div></article></div></section>
      <div className="home-bottom-note"><Sparkles size={15}/><span>Your story is the starting point. Every next step stays yours.</span></div>
    </main>
  </>;
}

function ImageAttachment({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [preview, setPreview] = useState("");
  useEffect(() => { const url = URL.createObjectURL(file); setPreview(url); return () => URL.revokeObjectURL(url); }, [file]);
  return <div className="attachment-chip"><span className="attachment-preview">{preview ? <img src={preview} alt="" /> : <FileImage size={15}/>}</span><span>{file.name}</span><button type="button" aria-label={`Remove ${file.name}`} onClick={onRemove}><X size={14}/></button></div>;
}
