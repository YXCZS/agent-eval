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
function label(value: string): string { return ({ queued: "排队中", running: "运行中", completed: "已完成", partial: "部分完成", failed: "失败", cancelled: "已取消", passed: "通过", missing: "缺失", error: "错误", not_run: "未运行" })[value] ?? value.replaceAll("_", " "); }
function displayValue(value: JsonValue): string { return typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function formatMetric(metric: Metric): string {
  const value = metric.pass_rate ?? metric.average;
  return value === null ? "无评分" : metric.pass_rate !== null ? `通过率 ${Math.round(value * 100)}%` : value.toFixed(3);
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
    } catch (error) { setNotice(error instanceof Error ? error.message : "无法加载报告。"); }
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
      .catch((error: unknown) => setNotice(error instanceof Error ? error.message : "无法加载此报告。"))
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
    if (comparisonIds.length !== 2) { setNotice("请选择恰好两个运行；第一个将作为基线。"); return; }
    setCompareBusy(true); setNotice(null);
    try { setComparison(await requestJson<Comparison>(`/projects/${PROJECT_ID}/comparisons`, { method: "POST", body: JSON.stringify({ run_ids: comparisonIds }) })); }
    catch (error) { setNotice(error instanceof Error ? error.message : "无法比较这些运行。"); }
    finally { setCompareBusy(false); }
  }
  async function evaluateGate() {
    if (!runId || !gateMetric) { setNotice("评估门禁前，请选择报告运行和指标。"); return; }
    const minimum = Number(gateMinimum);
    if (!gateHard && (!Number.isFinite(minimum) || gateMinimum.trim() === "")) { setNotice("请输入数值型最低阈值，或要求所有用例通过。"); return; }
    setCompareBusy(true); setNotice(null);
    const rule: GateRule = { metric_name: gateMetric, aggregation: "pass_rate", require_all_passed: gateHard };
    if (Number.isFinite(minimum) && gateMinimum.trim() !== "") rule.minimum = minimum;
    try { setGateResult(await requestJson<GateResult>(`/projects/${PROJECT_ID}/runs/${runId}/regression-gate`, { method: "POST", body: JSON.stringify({ rules: [rule] }) })); }
    catch (error) { setNotice(error instanceof Error ? error.message : "无法评估此回归门禁。"); }
    finally { setCompareBusy(false); }
  }
  async function downloadReport(format: "json" | "csv") {
    if (!runId) return;
    const params = new URLSearchParams({ format });
    if (metric) params.set("metric", metric);
    if (executionStatus) params.set("execution_status", executionStatus);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/reports/${runId}/export?${params.toString()}`, { headers: requestHeaders() });
      if (!response.ok) throw new Error(`导出失败（${response.status}）`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `evaluation-report-${runId}.${format}`; anchor.click(); URL.revokeObjectURL(url);
    } catch (error) { setNotice(error instanceof Error ? error.message : "无法导出此报告。"); }
  }

  async function selectCase(item: ReportCase) {
    setSelectedCase(item); setTimeline(null);
    if (!item.trace_id) return;
    setDetailBusy(true);
    try { setTimeline(await requestJson<Timeline>(`/projects/${PROJECT_ID}/traces/${item.trace_id}/timeline`)); }
    catch (error) { setNotice(error instanceof Error ? error.message : "无法加载此 Trace 时间线。"); }
    finally { setDetailBusy(false); }
  }

  return <section className="reports-workbench">
    <div className="resource-heading reports-heading"><div><p className="eyebrow"><BarChart3 size={14} /> 质量信号</p><h1>评测报告</h1><p>检查指标状态、定位失败，并将每项评分追溯到生成它的执行过程。</p></div><button className="outline-button" onClick={() => void loadSummaries()} disabled={busy}><LoaderCircle className={busy ? "spin" : ""} size={16} /> 刷新报告</button></div>
    {notice && <div className="report-notice"><AlertTriangle size={16} />{notice}</div>}
    <div className="report-tabs" role="tablist"><button className={mode === "report" ? "active" : ""} onClick={() => setMode("report")} role="tab" aria-selected={mode === "report"}><FileSearch size={15} /> 报告详情</button><button className={mode === "compare" ? "active" : ""} onClick={() => setMode("compare")} role="tab" aria-selected={mode === "compare"}><GitCompareArrows size={15} /> 比较与门禁</button></div>
    {mode === "compare" ? <ComparisonGatePanel summaries={summaries} selectedRunId={runId} comparisonIds={comparisonIds} comparison={comparison} gateMetric={gateMetric} minimum={gateMinimum} hard={gateHard} gateResult={gateResult} busy={compareBusy} onToggle={toggleComparison} onCompare={() => void createComparison()} onMetric={setGateMetric} onMinimum={setGateMinimum} onHard={setGateHard} onGate={() => void evaluateGate()} /> : <>
    <div className="report-controls panel">
      <label className="field-label">评测运行<select value={runId} onChange={(event) => { setRunId(event.target.value); setMetric(""); setExecutionStatus(""); setGateResult(null); }} disabled={busy && summaries.length === 0}><option value="">选择运行</option>{summaries.map((item) => <option key={item.run_id} value={item.run_id}>{item.run_id.slice(0, 12)} / {item.total_cases} 个用例 / {label(item.status)}</option>)}</select></label>
      <label className="field-label">指标<select value={metric} onChange={(event) => setMetric(event.target.value)} disabled={!runId}><option value="">所有指标</option>{metricNames.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label className="field-label">执行状态<select value={executionStatus} onChange={(event) => setExecutionStatus(event.target.value)} disabled={!runId}><option value="">所有状态</option>{["completed", "failed", "queued", "running", "cancelled"].map((item) => <option key={item} value={item}>{label(item)}</option>)}</select></label>
      <label className="report-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="查找用例或元数据" aria-label="查找报告用例" /></label>
    </div>
    {runId && <div className="report-downloads"><span>包含配置快照、指标定义和已应用的筛选条件。</span><button className="outline-button compact" onClick={() => void downloadReport("csv")}><Download size={14} /> CSV</button><button className="outline-button compact" onClick={() => void downloadReport("json")}><Download size={14} /> JSON</button></div>}
    {!busy && !report && !notice && <div className="report-empty panel"><FileSearch size={24} /><strong>暂无评测报告</strong><span>开始一次评测运行以生成评分和 Trace 证据。</span></div>}
    {report && <>
      <div className="report-summary"><div><span>运行</span><strong>{report.run_id}</strong><StatusMark status={report.status} /></div><div><span>显示的用例</span><strong>{report.matched_cases} / {report.total_cases}</strong></div><div><span>失败数</span><strong className={failures ? "danger-text" : ""}>{failures}</strong></div><div><span>生成时间</span><strong>{formatDate(report.generated_at)}</strong></div></div>
      <div className="metric-grid report-metrics">{report.metrics.length ? report.metrics.map((item) => <article className="metric-tile accent-teal" key={`${item.metric_name}-${item.evaluator_version_id}`}><span className="metric-label">{item.metric_name}</span><strong>{formatMetric(item)}</strong><span className="metric-change muted">{item.passed_count}/{item.valid_count} 个通过{item.threshold !== null ? ` / 阈值 ${item.threshold}` : ""}</span></article>) : <div className="report-metric-empty">没有评分记录符合这些筛选条件。</div>}</div>
      <div className="reports-layout">
        <section className="report-cases panel"><div className="report-panel-header"><div><span className="section-kicker">用例</span><strong>{visibleCases.length} 个匹配用例</strong></div><span>输出和评分状态</span></div><div className="case-list">{visibleCases.map((item) => <button className={selectedCase?.case_id === item.case_id ? "report-case selected" : "report-case"} onClick={() => void selectCase(item)} key={item.case_id}><span className="case-status"><StatusMark status={item.execution_status} /></span><span className="case-copy"><strong>{item.case_id}</strong><small>{item.error_type ?? (Object.entries(item.metadata).slice(0, 2).map(([key, value]) => `${key}: ${String(value)}`).join(" / ") || "无元数据")}</small></span><span className="case-score-summary">{item.scores.slice(0, 2).map((score) => <i className={statusTone(score.status)} title={`${score.metric_name}: ${label(score.status)}`} key={score.id}>{score.value ?? (score.passed === true ? "1" : score.passed === false ? "0" : "-")}</i>)}</span><ChevronRight size={16} /></button>)}{visibleCases.length === 0 && <div className="case-list-empty">没有用例符合当前报告筛选条件。</div>}</div></section>
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
    <section className="compare-config panel"><div className="report-panel-header"><div><span className="section-kicker">版本比较</span><strong>选择基线和候选版本</strong></div><span>已选择 {comparisonIds.length}/2</span></div><div className="compare-config-body"><div className="comparison-runs">{summaries.map((item) => <label key={item.run_id}><input type="checkbox" checked={comparisonIds.includes(item.run_id)} onChange={() => onToggle(item.run_id)} /><span><strong>{item.run_id}</strong><small>{item.dataset_version_id.slice(0, 10)} / {item.total_cases} 个用例 / {label(item.status)}</small></span></label>)}</div><button className="primary" onClick={onCompare} disabled={busy || comparisonIds.length !== 2}><GitCompareArrows size={16} /> {busy ? "正在比较……" : "比较运行"}</button></div></section>
    {comparison && <section className="comparison-result panel"><div className="report-panel-header"><div><span className="section-kicker">比较结果</span><strong>{comparison.baseline_run_id.slice(0, 12)} 基线</strong></div><span>{comparison.dataset_version_id.slice(0, 12)}</span></div><div className="comparison-metrics">{comparison.metric_comparisons.map((item) => <div key={item.metric_name}><strong>{item.metric_name}</strong>{!item.comparable ? <span className="comparison-reason">{item.reason}</span> : item.points.map((point) => <span className="comparison-point" key={point.run_id}>{point.run_id.slice(0, 8)}：{point.pass_rate === null ? "无评分" : `${Math.round(point.pass_rate * 100)}%`}{point.delta_pass_rate !== null && <b className={point.delta_pass_rate < 0 ? "danger-text" : "positive"}>{point.delta_pass_rate >= 0 ? "+" : ""}{(point.delta_pass_rate * 100).toFixed(1)} 个百分点</b>}</span>)}</div>)}</div><div className="change-columns"><div><span className="section-kicker">新增失败</span>{comparison.new_failures.length ? comparison.new_failures.map((item) => <p key={`${item.case_id}-${item.run_id}`}><b>{item.case_id}</b>{item.failed_metrics.join(", ") || "执行"}</p>) : <p>没有新出现的失败用例。</p>}</div><div><span className="section-kicker">恢复用例</span>{comparison.recovered_cases.length ? comparison.recovered_cases.map((item) => <p key={`${item.case_id}-${item.run_id}`}><b>{item.case_id}</b>{item.failed_metrics.join(", ") || "执行"}</p>) : <p>没有恢复的用例。</p>}</div></div></section>}
    <section className="gate-config panel"><div className="report-panel-header"><div><span className="section-kicker">回归门禁</span><strong>机器可读的质量检查</strong></div><ShieldCheck size={17} /></div><div className="gate-config-body"><label className="field-label">指标<select value={gateMetric} onChange={(event) => onMetric(event.target.value)}><option value="">选择指标</option>{metrics.map((item) => <option key={`${item.metric_name}-${item.evaluator_version_id}`} value={item.metric_name}>{item.metric_name}</option>)}</select></label><label className="field-label">最低通过率<input type="number" min="0" max="1" step="0.01" value={minimum} onChange={(event) => onMinimum(event.target.value)} /></label><label className="gate-hard"><input type="checkbox" checked={hard} onChange={(event) => onHard(event.target.checked)} /><span className="checkbox-mark"><Check size={12} /></span> 要求所有用例通过</label><button className="primary" onClick={onGate} disabled={busy || !selectedRunId}><ShieldCheck size={16} /> {busy ? "正在检查……" : "评估门禁"}</button>{gateResult && <div className={`gate-result ${statusTone(gateResult.status)}`}><StatusMark status={gateResult.status} />{gateResult.rules.map((item) => <p key={item.rule.metric_name}><b>{item.actual_value === null ? "无结果" : item.rule.aggregation === "pass_rate" ? `${Math.round(item.actual_value * 100)}%` : item.actual_value.toFixed(3)}</b>{item.reason ?? `${item.valid_count} 个有效评分`}</p>)}</div>}</div></section>
  </div>;
}

function CaseDetail({ item, timeline, busy }: { item: ReportCase | null; timeline: Timeline | null; busy: boolean }) {
  if (!item) return <section className="report-detail panel"><div className="report-panel-header"><div><span className="section-kicker">用例详情</span><strong>选择用例</strong></div></div><div className="detail-empty"><Sparkles size={22} /><span>选择一个用例，以查看其输出、评分证据和 Trace 时间线。</span></div></section>;
  return <section className="report-detail panel"><div className="report-panel-header"><div><span className="section-kicker">用例详情</span><strong>{item.case_id}</strong></div><StatusMark status={item.execution_status} /></div><div className="detail-scroll">
    {(item.error_type || item.error_message) && <div className="sample-error"><ShieldAlert size={15} /><div><strong>{item.error_type ?? "执行错误"}</strong><span>{item.error_message ?? "此用例未能成功完成。"}</span></div></div>}
    <DetailBlock title="实际输出"><pre>{displayValue(item.output)}</pre></DetailBlock>
    <div className="score-evidence"><span className="section-kicker">评分和证据</span>{item.scores.length ? item.scores.map((score) => <article className="score-record" key={score.id}><div><strong>{score.metric_name}</strong><StatusMark status={score.status} /></div><b>{score.value ?? score.label ?? "无值"}</b>{score.explanation && <p>{score.explanation}</p>}{score.evidence.length > 0 && <pre>{displayValue(score.evidence)}</pre>}{score.rubric && <small>评分标准：{score.rubric}</small>}</article>) : <p className="detail-muted">此用例没有写入评分记录。</p>}</div>
    <div className="trace-evidence"><span className="section-kicker">Trace 时间线</span>{busy && <div className="timeline-loading"><LoaderCircle className="spin" size={15} /> 正在加载执行证据</div>}{!busy && !item.trace_id && <p className="detail-muted">此用例没有存储的 Trace 记录。</p>}{!busy && timeline && <div className="timeline-list">{timeline.spans.map((span) => <div className="timeline-row" style={{ paddingLeft: `${span.depth * 13}px` }} key={span.span_id}><i className={statusTone(span.status)} /><div><strong>{span.name}</strong><span>{span.kind} / {span.duration_ms === null ? "进行中" : `${Math.round(span.duration_ms)} ms`}</span></div><StatusMark status={span.status} /></div>)}</div>}</div>
  </div></section>;
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) { return <div className="detail-block"><span className="section-kicker">{title}</span>{children}</div>; }
