"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarDays, FileText, Plus, Search } from "lucide-react";
import { listCases } from "@/lib/api";
import { usePrefs } from "@/components/app-shell";

export function CasesPage() {
  const { t } = usePrefs(); const [query, setQuery] = useState(""); const { data: items = [], isLoading: loading } = useQuery({ queryKey: ["cases"], queryFn: listCases });
  const filtered = items.filter((item) => `${item.summary} ${item.counterparty_name || ""}`.toLowerCase().includes(query.toLowerCase()));
  return <main className="cases-page"><div className="cases-header"><div><div className="breadcrumb-simple"><Link href="/">Home</Link><span>/</span><b>{t("navCases")}</b></div><span className="eyebrow">YOUR CASE FILES</span><h1>{t("navCases")}</h1><p>Keep each complaint, deadline and next step in one place.</p></div><Link href="/" className="button button-primary"><Plus size={16}/>{t("startCase")}</Link></div>
    {items.length > 0 && <div className="cases-toolbar"><label className="search-box"><Search size={15}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search cases" aria-label="Search cases"/></label><span>{filtered.length} {filtered.length === 1 ? "case" : "cases"}</span></div>}
    {loading ? <div className="cases-skeleton"><i/><i/><i/></div> : filtered.length === 0 ? <div className="cases-empty"><div className="empty-file-icon"><FileText size={23}/></div><h2>{items.length ? "No matching cases" : t("emptyCases")}</h2><p>{items.length ? "Try another word or search by company name." : "Describe your issue and we’ll help you work out the next step."}</p><Link href="/" className="button button-primary">{t("startCase")} <ArrowRight size={15}/></Link></div> : <div className="case-cards">{filtered.map((item, index) => <Link href={`/case/${item.id}`} className="case-list-card" key={item.id}><div className="case-card-index">{String(index + 1).padStart(2, "0")}</div><div className="case-list-main"><div className="case-list-top"><span className="eyebrow">{item.id} · {new Date(item.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</span><span className={`state-pill state-${item.state.toLowerCase()}`}>{item.state.replaceAll("_", " ").toLowerCase()}</span></div><h2>{item.counterparty_name || "Consumer complaint"}</h2><p>{item.summary}</p><div className="case-card-meta"><span><CalendarDays size={14}/>{item.next_deadline ? `Next date · ${new Date(`${item.next_deadline}T12:00:00+05:30`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}` : "No deadline set"}</span><span>Step {item.current_step || "—"}</span></div></div><ArrowRight className="case-card-arrow" size={19}/></Link>)}</div>}
    <p className="cases-note"><span className="case-note-mark">✳</span> Your information is used to organize this demo case. Check official sources before you file.</p>
  </main>;
}
