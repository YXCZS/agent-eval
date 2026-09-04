"use client";

import { useState } from "react";
import { AgentsView } from "./agents-view";
import { DatasetsView } from "./datasets-view";
import { ReportsView } from "./reports-view";
import { RunsView } from "./runs-view";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  ArrowUpRight,
  Bot,
  Boxes,
  Braces,
  ChevronDown,
  CircleCheck,
  CircleDashed,
  Database,
  FileChartColumn,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  Layers3,
  Plus,
  Play,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Workflow,
  XCircle,
} from "lucide-react";

type ViewKey = "overview" | "agents" | "datasets" | "evaluators" | "runs" | "reports" | "traces";

type NavItem = {
  key: ViewKey;
  label: string;
  icon: LucideIcon;
};

const navItems: NavItem[] = [
  { key: "overview", label: "Overview", icon: Gauge },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "datasets", label: "Datasets", icon: Database },
  { key: "evaluators", label: "Evaluators", icon: FlaskConical },
  { key: "runs", label: "Evaluation runs", icon: Activity },
  { key: "reports", label: "Reports", icon: FileChartColumn },
  { key: "traces", label: "Traces", icon: Workflow },
];

const viewMeta: Record<Exclude<ViewKey, "overview">, { title: string; eyebrow: string; description: string }> = {
  agents: {
    title: "Agents",
    eyebrow: "Execution targets",
    description: "Register prompt runners and HTTP agents, then pin the version used by each run.",
  },
  datasets: {
    title: "Datasets",
    eyebrow: "Evaluation inputs",
    description: "Versioned cases for prompt, RAG, tool and multi-turn agent evaluations.",
  },
  evaluators: {
    title: "Evaluators",
    eyebrow: "Scoring definitions",
    description: "Compose deterministic checks, judges and adapter-backed metrics.",
  },
  runs: {
    title: "Evaluation runs",
    eyebrow: "Experiments",
    description: "Track queued work, sample failures and reproducible configuration snapshots.",
  },
  reports: {
    title: "Reports",
    eyebrow: "Quality signals",
    description: "Compare metrics, inspect failure clusters and export machine-readable results.",
  },
  traces: {
    title: "Traces",
    eyebrow: "Execution evidence",
    description: "Follow an agent call from prompt rendering through tools, retrieval and scores.",
  },
};

const recentRuns = [
  { id: "run_8f31", agent: "Order support v2", dataset: "orders-regression", score: "94.2%", status: "Completed", tone: "success", time: "8 min ago" },
  { id: "run_8f2a", agent: "Knowledge RAG v4", dataset: "help-center-qa", score: "88.7%", status: "Partial", tone: "warning", time: "41 min ago" },
  { id: "run_8e94", agent: "Support prompt v7", dataset: "support-smoke", score: "97.1%", status: "Completed", tone: "success", time: "Yesterday" },
];

const resourceRows: Record<Exclude<ViewKey, "overview">, Array<{ name: string; detail: string; status: string; tone: string; meta: string }>> = {
  agents: [
    { name: "Order support", detail: "Tool agent · 3 versions", status: "Active", tone: "success", meta: "Updated 12 min ago" },
    { name: "Knowledge RAG", detail: "RAG agent · 4 versions", status: "Active", tone: "success", meta: "Updated 1 hr ago" },
    { name: "Support prompt", detail: "Prompt agent · 7 versions", status: "Draft", tone: "neutral", meta: "Updated yesterday" },
  ],
  datasets: [
    { name: "orders-regression", detail: "Tool · 48 cases · v12", status: "Ready", tone: "success", meta: "Last edited today" },
    { name: "help-center-qa", detail: "RAG · 120 cases · v4", status: "Ready", tone: "success", meta: "Last edited yesterday" },
    { name: "support-smoke", detail: "Prompt · 16 cases · v3", status: "Ready", tone: "success", meta: "Last edited Aug 30" },
  ],
  evaluators: [
    { name: "Task success", detail: "Deterministic · higher is better", status: "Enabled", tone: "success", meta: "v1.0.0" },
    { name: "Policy compliance", detail: "Deterministic · hard gate", status: "Enabled", tone: "success", meta: "v1.2.0" },
    { name: "Answer quality", detail: "LLM judge · 0 to 1", status: "Enabled", tone: "success", meta: "v2.1.0" },
  ],
  runs: recentRuns.map((run) => ({ name: run.id, detail: `${run.agent} · ${run.dataset}`, status: run.status, tone: run.tone, meta: run.time })),
  reports: [
    { name: "orders-regression / v12", detail: "3 metrics · 48 samples", status: "94.2% pass", tone: "success", meta: "Generated 8 min ago" },
    { name: "help-center-qa / v4", detail: "5 metrics · 120 samples", status: "88.7% pass", tone: "warning", meta: "Generated 41 min ago" },
  ],
  traces: [
    { name: "trace_01HZX9Q", detail: "Order support · tool call chain", status: "Completed", tone: "success", meta: "8 min ago" },
    { name: "trace_01HZX7M", detail: "Knowledge RAG · retrieval miss", status: "Error", tone: "danger", meta: "41 min ago" },
    { name: "trace_01HZWQ2", detail: "Support prompt · LLM call", status: "Completed", tone: "success", meta: "Yesterday" },
  ],
};

function StatusMark({ tone, label }: { tone: string; label: string }) {
  const Icon = tone === "danger" ? XCircle : tone === "warning" ? CircleDashed : CircleCheck;
  return <span className={`status status-${tone}`}><Icon size={14} />{label}</span>;
}

function Overview({ onNavigate }: { onNavigate: (view: ViewKey) => void }) {
  return (
    <>
      <section className="welcome-band">
        <div>
          <p className="eyebrow"><Sparkles size={14} /> Evaluation control room</p>
          <h1>See what changed.<br /><span>Know why it changed.</span></h1>
          <p className="lede">A trace-first workspace for testing prompt, RAG and tool agents before quality regressions reach production.</p>
        </div>
        <div className="welcome-mark" aria-hidden="true"><GitCompareArrows size={48} strokeWidth={1.2} /><span>v1 → v2</span></div>
      </section>
      <section className="metric-grid" aria-label="Workspace summary">
        <article className="metric-tile"><span className="metric-label">Runs this week</span><strong>28</strong><span className="metric-change positive"><ArrowUpRight size={14} /> 18.4%</span></article>
        <article className="metric-tile accent-teal"><span className="metric-label">Average pass rate</span><strong>92.6%</strong><span className="metric-change positive"><ArrowUpRight size={14} /> 3.8 pts</span></article>
        <article className="metric-tile accent-coral"><span className="metric-label">Open failures</span><strong>17</strong><span className="metric-change negative"><ArrowUpRight size={14} /> 4 new</span></article>
        <article className="metric-tile accent-gold"><span className="metric-label">Tokens evaluated</span><strong>1.84M</strong><span className="metric-change muted">$12.48 estimated</span></article>
      </section>
      <section className="content-grid">
        <article className="panel runs-panel">
          <div className="panel-heading"><div><p className="eyebrow">Latest experiments</p><h2>Recent runs</h2></div><button className="text-button" onClick={() => onNavigate("runs")}>View all <ArrowUpRight size={15} /></button></div>
          <div className="run-list">{recentRuns.map((run) => <div className="run-row" key={run.id}><div className="run-icon"><TerminalSquare size={17} /></div><div className="run-main"><strong>{run.agent}</strong><span>{run.id} · {run.dataset}</span></div><div className="run-score"><strong>{run.score}</strong><span>{run.time}</span></div><StatusMark tone={run.tone} label={run.status} /></div>)}</div>
        </article>
        <article className="panel signal-panel">
          <div className="panel-heading"><div><p className="eyebrow">Signal watch</p><h2>Quality by agent</h2></div><button className="icon-button" title="Open reports" aria-label="Open reports" onClick={() => onNavigate("reports")}><ArrowUpRight size={17} /></button></div>
          <div className="signal-list"><div className="signal-row"><div><strong>Order support</strong><span>Tool correctness</span></div><b>96%</b><div className="bar"><i style={{ width: "96%" }} /></div></div><div className="signal-row"><div><strong>Knowledge RAG</strong><span>Faithfulness</span></div><b>89%</b><div className="bar"><i style={{ width: "89%" }} /></div></div><div className="signal-row"><div><strong>Support prompt</strong><span>Answer relevance</span></div><b>97%</b><div className="bar"><i style={{ width: "97%" }} /></div></div></div>
          <div className="signal-foot"><ShieldCheck size={16} /> All policy gates passed in the last 24 hours</div>
        </article>
      </section>
      <section className="quick-start"><div><p className="eyebrow">Build your first experiment</p><h2>Start with an agent, a dataset and a score.</h2><p>Everything stays versioned, so comparisons remain explainable.</p></div><div className="quick-actions"><button onClick={() => onNavigate("agents")}><Bot size={17} /> Add agent</button><button onClick={() => onNavigate("datasets")}><Database size={17} /> Add dataset</button><button className="primary" onClick={() => onNavigate("runs")}><Play size={16} /> New evaluation</button></div></section>
    </>
  );
}

function ResourceView({ view, onAction }: { view: Exclude<ViewKey, "overview">; onAction: () => void }) {
  const meta = viewMeta[view];
  const rows = resourceRows[view];
  return <section className="resource-view"><div className="resource-heading"><div><p className="eyebrow">{meta.eyebrow}</p><h1>{meta.title}</h1><p>{meta.description}</p></div><button className="primary" onClick={onAction}><Plus size={17} /> Create {view === "runs" ? "run" : view === "traces" ? "trace" : view.slice(0, -1)}</button></div><div className="toolbar"><div className="search-field"><Search size={16} /><input aria-label={`Search ${meta.title}`} placeholder={`Search ${meta.title.toLowerCase()}...`} /></div><button className="filter-button">All status <ChevronDown size={15} /></button></div><div className="resource-list">{rows.map((row) => <div className="resource-row" key={row.name}><div className="resource-symbol"><Boxes size={18} /></div><div className="resource-main"><strong>{row.name}</strong><span>{row.detail}</span></div><span className="resource-meta">{row.meta}</span><StatusMark tone={row.tone} label={row.status} /><button className="icon-button" title={`Open ${row.name}`} aria-label={`Open ${row.name}`}><ArrowUpRight size={17} /></button></div>)}</div>{rows.length === 0 && <div className="empty-state"><Braces size={26} /><h2>No {meta.title.toLowerCase()} yet</h2><p>Create the first one to make this workspace useful.</p><button className="primary" onClick={onAction}><Plus size={17} /> Create one</button></div>}</section>;
}

export default function Home() {
  const [activeView, setActiveView] = useState<ViewKey>("overview");
  const activeLabel = navItems.find((item) => item.key === activeView)?.label ?? "Overview";
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">AE</div><div><strong>Agent Eval</strong><span>Workbench</span></div></div><div className="workspace-switcher"><span>Workspace</span><strong>Local project</strong><ChevronDown size={15} /></div><nav aria-label="Main navigation">{navItems.map(({ key, label, icon: Icon }) => <button className={activeView === key ? "nav-item active" : "nav-item"} key={key} onClick={() => setActiveView(key)}><Icon size={18} /><span>{label}</span>{key === "runs" && <i className="nav-count">3</i>}</button>)}</nav><div className="sidebar-bottom"><div className="system-status"><span className="pulse" /> API connected<span>v0.1.0</span></div><div className="profile"><div className="avatar">D</div><div><strong>Developer</strong><span>Single workspace</span></div><MoreDots /></div></div></aside><main className="main-content"><header className="topbar"><div className="breadcrumb"><span>Workbench</span><b>/</b><strong>{activeLabel}</strong></div><div className="topbar-actions"><button className="icon-button" title="Search workspace" aria-label="Search workspace"><Search size={18} /></button><button className="outline-button" onClick={() => setActiveView("traces")}><Activity size={16} /> Live traces</button><button className="primary" onClick={() => setActiveView("runs")}><Play size={16} /> New run</button></div></header><div className="page-content">{activeView === "overview" ? <Overview onNavigate={setActiveView} /> : activeView === "agents" ? <AgentsView /> : activeView === "datasets" ? <DatasetsView /> : activeView === "runs" ? <RunsView /> : activeView === "reports" ? <ReportsView /> : <ResourceView view={activeView} onAction={() => setActiveView(activeView)} />}</div></main></div>;
}

function MoreDots() {
  return <span className="more-dots" aria-hidden="true"><i /><i /><i /></span>;
}
