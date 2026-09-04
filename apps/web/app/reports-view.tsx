"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Check,
  ChevronRight,
  CircleDashed,
  Clock3,
  Download,
  FileSearch,
  GitCompareArrows,
  LoaderCircle,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";

type RunStatus = "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";
type ExecutionStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
type ScoreStatus = "passed" | "failed" | "missing" | "error" | "not_run";
type Direction = "higher_is_better" | "lower_is_better";
type JsonValue = Record<string, unknown> | unknown[] | string | number | boolean | null;

type Metric = { metric_name: string; evaluator_version_id: string; valid_count: number; missing_count: number; error_count: number; passed_count: number; average: number | null; pass_rate: number | null; aggregation: string; threshold: number | null; direction: Direction };
type Score = { id: string; metric_name: string; evaluator_version_id: string; trace_id: string | null; status: ScoreStatus; value: number | null; label: string | null; passed: boolean | null; explanation: string | null; evidence: Array<Record<string, unknown>>; rubric: string | null; judge_model: string | null; threshold: number | null; direction: Direction; raw_result: JsonValue };
type ReportCase = { case_id: string; metadata: Record<string, unknown>; execution_status: ExecutionStatus; error_type: string | null; error_message: string | null; output: JsonValue; trace_id: string | null; scores: Score[] };
type Report = { run_id: string; status: RunStatus; total_cases: number; matched_cases: number; filters: Record<string, unknown>; metrics: Metric[]; cases: ReportCase[]; generated_at: string };
type ReportSummary = { run_id: string; status: RunStatus; agent_version_id: string; dataset_version_id: string; total_cases: number; completed_cases: number; failed_cases: number; metrics: Metric[]; created_at: string; finished_at: string | null };
type Timeline = { trace_id: string; started_at: string | null; ended_at: string | null; spans: Array<{ span_id: string; parent_span_id: string | null; kind: string; name: string; status: ExecutionStatus; started_at: string; ended_at: string | null; duration_ms: number | null; depth: number }> };
type ComparisonPoint = { run_id: string; average: number | null; pass_rate: number | null; valid_count: number; missing_count: number; error_count: number; passed_count: number; delta_average: number | null; delta_pass_rate: number | null };
type Comparison = { dataset_version_id: string; baseline_run_id: string; metric_comparisons: Array<{ metric_name: string; comparable: boolean; reason: string | null; points: ComparisonPoint[] }>; new_failures: Array<{ case_id: string; run_id: string; failed_metrics: string[] }>; recovered_cases: Array<{ case_id: string; run_id: string; failed_metrics: string[] }> };
type GateRule = { metric_name: string; evaluator_version_id?: string; aggregation: "average" | "pass_rate"; minimum?: number; maximum?: number; require_all_passed: boolean };
type GateResult = { run_id: string; run_status: RunStatus; status: "passed" | "failed" | "indeterminate" | "incomplete"; rules: Array<{ rule: GateRule; status: "passed" | "failed" | "indeterminate" | "incomplete"; actual_value: number | null; valid_count: number; missing_count: number; error_count: number; failed_case_ids: string[]; reason: string | null }> };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PROJECT_ID = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1";
const SESSION = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";

function requestHeaders(): HeadersInit { return { "Content-Type": "application/json", "X-Workspace-Session": SESSION }; }
async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { ...requestHeaders(), ...init?.headers } });
  const body = await response.json().catch(() => null) as T | { detail?: unknown } | null;
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return body as T;
}
function label(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase()); }
function displayValue(value: JsonValue): string { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function formatMetric(metric: Metric): string {
  const value = metric.pass_rate ?? metric.average;
  return value === null ? "No score" : metric.pass_rate !== null ? `${Math.round(value * 100)}% pass` : value.toFixed(3);
}
function formatDate(value: string): string { return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
function statusTone(status: string): "success" | "danger" | "warning" | "neutral" { if (status === "completed" || status === "passed") return "success"; if (status === "failed" || status === "error") return "danger"; if (status === "partial" || status === "cancelled" || status === "missing" || status === "not_run") return "warning"; return "neutral"; }

function StatusMark({ status }: { status: string }) {
  const tone = statusTone(status);
  const Icon = tone === "success" ? Check : tone === "danger" ? XCircle : tone === "warning" ? AlertTriangle : CircleDashed;
  return <span className={`report-status ${tone}`}><Icon size={13} />{label(status)}</span>;
}

export function ReportsView() {
  const [mode, setMode] = useState<"report" | "compare">("report");
  const [summaries, setSummaries] = useState<ReportSummary[]>([]);
  const [runId, setRunId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [metric, setMetric] = useState("");
  const [executionStatus, setExecutionStatus] = useState("");
  const [search, setSearch] = useState("");
  const [selectedCase, setSelectedCase] = useState<ReportCase | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [busy, setBusy] = useState(true);
  const [detailBusy, setDetailBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [compareBusy, setCompareBusy] = useState(false);
  const [gateMetric, setGateMetric] = useState("");
  const [gateMinimum, setGateMinimum] = useState("0.9");
  const [gateHard, setGateHard] = useState(false);
  const [gateResult, setGateResult] = useState<GateResult | null>(null);

  async function loadSummaries() {
    setBusy(true); setNotice(null);
    try {
      const next = await requestJson<ReportSummary[]>(`/projects/${PROJECT_ID}/reports`);
      setSummaries(next);
      setRunId((current) => current || next[0]?.run_id || "");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not load reports."); }
    finally { setBusy(false); }
  }

  useEffect(() => { void loadSummaries(); }, []);
  useEffect(() => {
    if (!runId) { setReport(null); return; }
    const params = new URLSearchParams();
    if (metric) params.set("metric", metric);
    if (executionStatus) params.set("execution_status", executionStatus);
    setBusy(true); setNotice(null); setSelectedCase(null); setTimeline(null);
    void requestJson<Report>(`/projects/${PROJECT_ID}/reports/${runId}?${params.toString()}`)
      .then(setReport)
      .catch((error: unknown) => setNotice(error instanceof Error ? error.message : "Could not load this report."))
      .finally(() => setBusy(false));
  }, [runId, metric, executionStatus]);

  const metricNames = useMemo(() => Array.from(new Set((summaries.find((item) => item.run_id === runId)?.metrics ?? report?.metrics ?? []).map((item) => item.metric_name))).sort(), [summaries, runId, report]);
  const visibleCases = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized || !report) return report?.cases ?? [];
    return report.cases.filter((item) => item.case_id.toLowerCase().includes(normalized) || JSON.stringify(item.metadata).toLowerCase().includes(normalized));
  }, [report, search]);
  const failures = report?.cases.filter((item) => item.execution_status === "failed" || item.scores.some((score) => score.status === "failed" || score.status === "error")).length ?? 0;

  function toggleComparison(runId: string) {
    setComparisonIds((current) => current.includes(runId) ? current.filter((item) => item !== runId) : [...current, runId].slice(-2));
    setComparison(null);
  }
  async function createComparison() {
    if (comparisonIds.length !== 2) { setNotice("Choose exactly two runs. The first is the baseline."); return; }
    setCompareBusy(true); setNotice(null);
    try { setComparison(await requestJson<Comparison>(`/projects/${PROJECT_ID}/comparisons`, { method: "POST", body: JSON.stringify({ run_ids: comparisonIds }) })); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not compare these runs."); }
    finally { setCompareBusy(false); }
  }
  async function evaluateGate() {
    if (!runId || !gateMetric) { setNotice("Choose a report run and metric before evaluating a gate."); return; }
    const minimum = Number(gateMinimum);
    if (!gateHard && (!Number.isFinite(minimum) || gateMinimum.trim() === "")) { setNotice("Enter a numeric minimum or require every sample to pass."); return; }
    setCompareBusy(true); setNotice(null);
    const rule: GateRule = { metric_name: gateMetric, aggregation: "pass_rate", require_all_passed: gateHard };
    if (Number.isFinite(minimum) && gateMinimum.trim() !== "") rule.minimum = minimum;
    try { setGateResult(await requestJson<GateResult>(`/projects/${PROJECT_ID}/runs/${runId}/regression-gate`, { method: "POST", body: JSON.stringify({ rules: [rule] }) })); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not evaluate this regression gate."); }
    finally { setCompareBusy(false); }
  }
  async function downloadReport(format: "json" | "csv") {
    if (!runId) return;
    const params = new URLSearchParams({ format });
    if (metric) params.set("metric", metric);
    if (executionStatus) params.set("execution_status", executionStatus);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/reports/${runId}/export?${params.toString()}`, { headers: requestHeaders() });
      if (!response.ok) throw new Error(`Export failed (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `evaluation-report-${runId}.${format}`; anchor.click(); URL.revokeObjectURL(url);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not export this report."); }
  }

  async function selectCase(item: ReportCase) {
    setSelectedCase(item); setTimeline(null);
    if (!item.trace_id) return;
    setDetailBusy(true);
    try { setTimeline(await requestJson<Timeline>(`/projects/${PROJECT_ID}/traces/${item.trace_id}/timeline`)); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not load this trace timeline."); }
    finally { setDetailBusy(false); }
  }

  return <section className="reports-workbench">
    <div className="resource-heading reports-heading"><div><p className="eyebrow"><BarChart3 size={14} /> Quality signals</p><h1>Evaluation reports</h1><p>Inspect metric health, isolate failures and trace every score back to the execution that produced it.</p></div><button className="outline-button" onClick={() => void loadSummaries()} disabled={busy}><LoaderCircle className={busy ? "spin" : ""} size={16} /> Refresh reports</button></div>
    {notice && <div className="report-notice"><AlertTriangle size={16} />{notice}</div>}
    <div className="report-tabs" role="tablist"><button className={mode === "report" ? "active" : ""} onClick={() => setMode("report")} role="tab" aria-selected={mode === "report"}><FileSearch size={15} /> Report detail</button><button className={mode === "compare" ? "active" : ""} onClick={() => setMode("compare")} role="tab" aria-selected={mode === "compare"}><GitCompareArrows size={15} /> Compare & gate</button></div>
    {mode === "compare" ? <ComparisonGatePanel summaries={summaries} selectedRunId={runId} comparisonIds={comparisonIds} comparison={comparison} gateMetric={gateMetric} minimum={gateMinimum} hard={gateHard} gateResult={gateResult} busy={compareBusy} onToggle={toggleComparison} onCompare={() => void createComparison()} onMetric={setGateMetric} onMinimum={setGateMinimum} onHard={setGateHard} onGate={() => void evaluateGate()} /> : <>
    <div className="report-controls panel">
      <label className="field-label">Evaluation run<select value={runId} onChange={(event) => { setRunId(event.target.value); setMetric(""); setExecutionStatus(""); setGateResult(null); }} disabled={busy && summaries.length === 0}><option value="">Select a run</option>{summaries.map((item) => <option key={item.run_id} value={item.run_id}>{item.run_id.slice(0, 12)} / {item.total_cases} cases / {label(item.status)}</option>)}</select></label>
      <label className="field-label">Metric<select value={metric} onChange={(event) => setMetric(event.target.value)} disabled={!runId}><option value="">All metrics</option>{metricNames.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label className="field-label">Execution<select value={executionStatus} onChange={(event) => setExecutionStatus(event.target.value)} disabled={!runId}><option value="">All states</option>{["completed", "failed", "queued", "running", "cancelled"].map((item) => <option key={item} value={item}>{label(item)}</option>)}</select></label>
      <label className="report-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find case or metadata" aria-label="Find a report case" /></label>
    </div>
    {runId && <div className="report-downloads"><span>Includes configuration snapshot, metric definition and applied filters.</span><button className="outline-button compact" onClick={() => void downloadReport("csv")}><Download size={14} /> CSV</button><button className="outline-button compact" onClick={() => void downloadReport("json")}><Download size={14} /> JSON</button></div>}
    {!busy && !report && !notice && <div className="report-empty panel"><FileSearch size={24} /><strong>No evaluation report yet</strong><span>Start an evaluation run to generate score and trace evidence.</span></div>}
    {report && <>
      <div className="report-summary"><div><span>Run</span><strong>{report.run_id}</strong><StatusMark status={report.status} /></div><div><span>Cases shown</span><strong>{report.matched_cases} / {report.total_cases}</strong></div><div><span>Failures</span><strong className={failures ? "danger-text" : ""}>{failures}</strong></div><div><span>Generated</span><strong>{formatDate(report.generated_at)}</strong></div></div>
      <div className="metric-grid report-metrics">{report.metrics.length ? report.metrics.map((item) => <article className="metric-tile accent-teal" key={`${item.metric_name}-${item.evaluator_version_id}`}><span className="metric-label">{item.metric_name}</span><strong>{formatMetric(item)}</strong><span className="metric-change muted">{item.passed_count}/{item.valid_count} passed{item.threshold !== null ? ` / threshold ${item.threshold}` : ""}</span></article>) : <div className="report-metric-empty">No score records match these filters.</div>}</div>
      <div className="reports-layout">
        <section className="report-cases panel"><div className="report-panel-header"><div><span className="section-kicker">Samples</span><strong>{visibleCases.length} matching cases</strong></div><span>Output and score state</span></div><div className="case-list">{visibleCases.map((item) => <button className={selectedCase?.case_id === item.case_id ? "report-case selected" : "report-case"} onClick={() => void selectCase(item)} key={item.case_id}><span className="case-status"><StatusMark status={item.execution_status} /></span><span className="case-copy"><strong>{item.case_id}</strong><small>{item.error_type ?? (Object.entries(item.metadata).slice(0, 2).map(([key, value]) => `${key}: ${String(value)}`).join(" / ") || "No metadata")}</small></span><span className="case-score-summary">{item.scores.slice(0, 2).map((score) => <i className={statusTone(score.status)} title={`${score.metric_name}: ${label(score.status)}`} key={score.id}>{score.value ?? (score.passed === true ? "1" : score.passed === false ? "0" : "-")}</i>)}</span><ChevronRight size={16} /></button>)}{visibleCases.length === 0 && <div className="case-list-empty">No cases match the selected report filters.</div>}</div></section>
        <CaseDetail item={selectedCase} timeline={timeline} busy={detailBusy} />
      </div>
    </>}
    </>}
  </section>;
}

function ComparisonGatePanel({ summaries, selectedRunId, comparisonIds, comparison, gateMetric, minimum, hard, gateResult, busy, onToggle, onCompare, onMetric, onMinimum, onHard, onGate }: { summaries: ReportSummary[]; selectedRunId: string; comparisonIds: string[]; comparison: Comparison | null; gateMetric: string; minimum: string; hard: boolean; gateResult: GateResult | null; busy: boolean; onToggle: (runId: string) => void; onCompare: () => void; onMetric: (value: string) => void; onMinimum: (value: string) => void; onHard: (value: boolean) => void; onGate: () => void }) {
  const current = summaries.find((item) => item.run_id === selectedRunId);
  const metrics = current?.metrics ?? [];
  return <div className="compare-workbench">
    <section className="compare-config panel"><div className="report-panel-header"><div><span className="section-kicker">Version comparison</span><strong>Choose baseline and candidate</strong></div><span>{comparisonIds.length}/2 selected</span></div><div className="compare-config-body"><div className="comparison-runs">{summaries.map((item) => <label key={item.run_id}><input type="checkbox" checked={comparisonIds.includes(item.run_id)} onChange={() => onToggle(item.run_id)} /><span><strong>{item.run_id}</strong><small>{item.dataset_version_id.slice(0, 10)} / {item.total_cases} cases / {label(item.status)}</small></span></label>)}</div><button className="primary" onClick={onCompare} disabled={busy || comparisonIds.length !== 2}><GitCompareArrows size={16} /> {busy ? "Comparing..." : "Compare runs"}</button></div></section>
    {comparison && <section className="comparison-result panel"><div className="report-panel-header"><div><span className="section-kicker">Comparison result</span><strong>{comparison.baseline_run_id.slice(0, 12)} baseline</strong></div><span>{comparison.dataset_version_id.slice(0, 12)}</span></div><div className="comparison-metrics">{comparison.metric_comparisons.map((item) => <div key={item.metric_name}><strong>{item.metric_name}</strong>{!item.comparable ? <span className="comparison-reason">{item.reason}</span> : item.points.map((point) => <span className="comparison-point" key={point.run_id}>{point.run_id.slice(0, 8)}: {point.pass_rate === null ? "no score" : `${Math.round(point.pass_rate * 100)}%`}{point.delta_pass_rate !== null && <b className={point.delta_pass_rate < 0 ? "danger-text" : "positive"}>{point.delta_pass_rate >= 0 ? "+" : ""}{(point.delta_pass_rate * 100).toFixed(1)} pts</b>}</span>)}</div>)}</div><div className="change-columns"><div><span className="section-kicker">New failures</span>{comparison.new_failures.length ? comparison.new_failures.map((item) => <p key={`${item.case_id}-${item.run_id}`}><b>{item.case_id}</b>{item.failed_metrics.join(", ") || "execution"}</p>) : <p>No newly failing cases.</p>}</div><div><span className="section-kicker">Recovered cases</span>{comparison.recovered_cases.length ? comparison.recovered_cases.map((item) => <p key={`${item.case_id}-${item.run_id}`}><b>{item.case_id}</b>{item.failed_metrics.join(", ") || "execution"}</p>) : <p>No recovered cases.</p>}</div></div></section>}
    <section className="gate-config panel"><div className="report-panel-header"><div><span className="section-kicker">Regression gate</span><strong>Machine-readable quality check</strong></div><ShieldCheck size={17} /></div><div className="gate-config-body"><label className="field-label">Metric<select value={gateMetric} onChange={(event) => onMetric(event.target.value)}><option value="">Select a metric</option>{metrics.map((item) => <option key={`${item.metric_name}-${item.evaluator_version_id}`} value={item.metric_name}>{item.metric_name}</option>)}</select></label><label className="field-label">Minimum pass rate<input type="number" min="0" max="1" step="0.01" value={minimum} onChange={(event) => onMinimum(event.target.value)} /></label><label className="gate-hard"><input type="checkbox" checked={hard} onChange={(event) => onHard(event.target.checked)} /><span className="checkbox-mark"><Check size={12} /></span> Require every sample to pass</label><button className="primary" onClick={onGate} disabled={busy || !selectedRunId}><ShieldCheck size={16} /> {busy ? "Checking..." : "Evaluate gate"}</button>{gateResult && <div className={`gate-result ${statusTone(gateResult.status)}`}><StatusMark status={gateResult.status} />{gateResult.rules.map((item) => <p key={item.rule.metric_name}><b>{item.actual_value === null ? "No result" : item.rule.aggregation === "pass_rate" ? `${Math.round(item.actual_value * 100)}%` : item.actual_value.toFixed(3)}</b>{item.reason ?? `${item.valid_count} valid scores`}</p>)}</div>}</div></section>
  </div>;
}

function CaseDetail({ item, timeline, busy }: { item: ReportCase | null; timeline: Timeline | null; busy: boolean }) {
  if (!item) return <section className="report-detail panel"><div className="report-panel-header"><div><span className="section-kicker">Sample detail</span><strong>Choose a sample</strong></div></div><div className="detail-empty"><Sparkles size={22} /><span>Select a case to inspect its output, score evidence and trace timeline.</span></div></section>;
  return <section className="report-detail panel"><div className="report-panel-header"><div><span className="section-kicker">Sample detail</span><strong>{item.case_id}</strong></div><StatusMark status={item.execution_status} /></div><div className="detail-scroll">
    {(item.error_type || item.error_message) && <div className="sample-error"><ShieldAlert size={15} /><div><strong>{item.error_type ?? "Execution error"}</strong><span>{item.error_message ?? "This sample did not complete successfully."}</span></div></div>}
    <DetailBlock title="Actual output"><pre>{displayValue(item.output)}</pre></DetailBlock>
    <div className="score-evidence"><span className="section-kicker">Scores and evidence</span>{item.scores.length ? item.scores.map((score) => <article className="score-record" key={score.id}><div><strong>{score.metric_name}</strong><StatusMark status={score.status} /></div><b>{score.value ?? score.label ?? "No value"}</b>{score.explanation && <p>{score.explanation}</p>}{score.evidence.length > 0 && <pre>{displayValue(score.evidence)}</pre>}{score.rubric && <small>Rubric: {score.rubric}</small>}</article>) : <p className="detail-muted">No score records were written for this sample.</p>}</div>
    <div className="trace-evidence"><span className="section-kicker">Trace timeline</span>{busy && <div className="timeline-loading"><LoaderCircle className="spin" size={15} /> Loading execution evidence</div>}{!busy && !item.trace_id && <p className="detail-muted">This sample has no stored trace.</p>}{!busy && timeline && <div className="timeline-list">{timeline.spans.map((span) => <div className="timeline-row" style={{ paddingLeft: `${span.depth * 13}px` }} key={span.span_id}><i className={statusTone(span.status)} /><div><strong>{span.name}</strong><span>{span.kind} / {span.duration_ms === null ? "in progress" : `${Math.round(span.duration_ms)} ms`}</span></div><StatusMark status={span.status} /></div>)}</div>}</div>
  </div></section>;
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) { return <div className="detail-block"><span className="section-kicker">{title}</span>{children}</div>; }
