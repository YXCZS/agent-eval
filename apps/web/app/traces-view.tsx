"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Check, CircleAlert, Clock3, RefreshCw, Search, Workflow, XCircle } from "lucide-react";

type ExecutionStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
type TraceSummary = { trace_id: string; run_id: string | null; case_id: string | null; status: ExecutionStatus; source: string; span_count: number; started_at: string | null; ended_at: string | null; created_at: string };
type TraceSpan = { span_id: string; trace_id: string; parent_span_id: string | null; kind: string; name: string; status: ExecutionStatus; started_at: string; ended_at: string | null; input: unknown; output: unknown; error: Record<string, unknown> | null; attributes: Record<string, unknown>; extensions: Record<string, unknown> };
type Trace = { trace_id: string; run_id: string | null; case_id: string | null; status: ExecutionStatus; spans: TraceSpan[]; source: string; extensions: Record<string, unknown> };
type Timeline = { trace_id: string; started_at: string | null; ended_at: string | null; spans: Array<{ span_id: string; parent_span_id: string | null; kind: string; name: string; status: ExecutionStatus; started_at: string; ended_at: string | null; duration_ms: number | null; depth: number }> };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PROJECT_ID = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1";
const SESSION = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";
const statusLabels: Record<ExecutionStatus, string> = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消" };

function requestHeaders(): HeadersInit { return { "Content-Type": "application/json", "X-Workspace-Session": SESSION }; }
async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { headers: requestHeaders() });
  const body = (await response.json().catch(() => null)) as T | { detail?: unknown } | null;
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new Error(typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`);
  }
  return body as T;
}
function formatDate(value: string | null): string { return value ? new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "未记录"; }
function formatJson(value: unknown): string { return value === null || value === undefined ? "未记录" : typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function tone(status: string): "success" | "danger" | "warning" | "neutral" { return status === "completed" ? "success" : status === "failed" ? "danger" : status === "cancelled" ? "warning" : "neutral"; }
function StatusMark({ status }: { status: ExecutionStatus }) { const currentTone = tone(status); const Icon = currentTone === "success" ? Check : currentTone === "danger" ? XCircle : currentTone === "warning" ? AlertTriangle : Clock3; return <span className={`status status-${currentTone}`}><Icon size={14} />{statusLabels[status]}</span>; }

export function TracesView() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Trace | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ExecutionStatus>("all");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState("");
  const visibleTraces = useMemo(() => traces.filter((trace) => { const text = `${trace.trace_id} ${trace.run_id ?? ""} ${trace.case_id ?? ""} ${trace.source}`.toLowerCase(); return (!query.trim() || text.includes(query.trim().toLowerCase())) && (statusFilter === "all" || trace.status === statusFilter); }), [query, statusFilter, traces]);
  const selectedSpan = detail?.spans.find((span) => span.span_id === selectedSpanId) ?? null;

  async function loadTrace(traceId: string) {
    setSelectedId(traceId);
    setDetailLoading(true);
    setNotice(null);
    try {
      const [trace, traceTimeline] = await Promise.all([
        requestJson<Trace>(`/projects/${PROJECT_ID}/traces/${encodeURIComponent(traceId)}`),
        requestJson<Timeline>(`/projects/${PROJECT_ID}/traces/${encodeURIComponent(traceId)}/timeline`),
      ]);
      setDetail(trace);
      setTimeline(traceTimeline);
      setSelectedSpanId(trace.spans[0]?.span_id ?? "");
    } catch (error) {
      setDetail(null);
      setTimeline(null);
      setNotice(`加载 Trace 详情失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setDetailLoading(false);
    }
  }

  async function loadTraces(preferredId?: string) {
    setLoading(true);
    try {
      const loaded = await requestJson<TraceSummary[]>(`/projects/${PROJECT_ID}/traces?limit=200`);
      setTraces(loaded);
      const next = loaded.find((trace) => trace.trace_id === preferredId) ?? loaded[0];
      if (next) await loadTrace(next.trace_id);
      else { setSelectedId(""); setDetail(null); setTimeline(null); }
      setNotice(null);
    } catch (error) {
      setNotice(`加载 Trace 失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadTraces(); }, []);

  return (
    <section className="resource-view traces-workbench">
      <div className="resource-heading">
        <div><p className="eyebrow"><Workflow size={14} /> 执行证据</p><h1>Trace 追踪</h1><p>查看 Agent 运行产生的真实 Trace、Span 和输入输出。Trace 由运行任务自动写入，也可以通过 API ingest。</p></div>
        <button className="outline-button" onClick={() => void loadTraces(selectedId)} disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""} /> 刷新 Trace</button>
      </div>
      {notice && <div className="inline-notice" role="status"><CircleAlert size={16} /> {notice}</div>}
      <div className="toolbar"><div className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="搜索 Trace" placeholder="搜索 Trace、Run 或 Case..." /></div><select className="filter-button" aria-label="Trace 状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | ExecutionStatus)}><option value="all">全部状态</option><option value="completed">已完成</option><option value="failed">失败</option><option value="running">运行中</option><option value="queued">排队中</option><option value="cancelled">已取消</option></select></div>
      <div className="traces-layout">
        <section className="panel trace-list-panel"><div className="panel-heading"><div><p className="eyebrow">最近执行</p><h2>{visibleTraces.length} 条 Trace</h2></div><Activity size={16} className="muted-icon" /></div>{loading ? <p className="panel-placeholder">正在加载 Trace...</p> : visibleTraces.length === 0 ? <div className="panel-placeholder"><Workflow size={24} /><p>{traces.length ? "没有符合筛选条件的 Trace。" : "还没有 Trace。先运行一次评测，或使用 Trace ingest API 写入。"}</p></div> : <div className="trace-list">{visibleTraces.map((trace) => <button key={trace.trace_id} className={`trace-list-item ${trace.trace_id === selectedId ? "selected" : ""}`} onClick={() => void loadTrace(trace.trace_id)}><span className={`trace-dot ${tone(trace.status)}`} /><span className="trace-list-copy"><strong>{trace.trace_id}</strong><small>{trace.run_id ?? "无 Run"} · {trace.case_id ?? "无 Case"}</small></span><span className="trace-list-meta"><b>{trace.span_count} spans</b><small>{formatDate(trace.created_at)}</small></span><StatusMark status={trace.status} /></button>)}</div>}</section>
        <section className="panel trace-detail-panel">{detailLoading ? <div className="panel-placeholder"><RefreshCw size={22} className="spin" /><p>正在加载 Trace 详情...</p></div> : detail && timeline ? <><div className="panel-heading"><div><p className="eyebrow">Trace 详情</p><h2>{detail.trace_id}</h2></div><StatusMark status={detail.status} /></div><div className="trace-detail-body"><div className="trace-meta-grid"><div><span>来源</span><strong>{detail.source}</strong></div><div><span>Run</span><strong>{detail.run_id ?? "无"}</strong></div><div><span>Case</span><strong>{detail.case_id ?? "无"}</strong></div><div><span>Span 数量</span><strong>{detail.spans.length}</strong></div></div><div className="trace-section"><div className="trace-section-heading"><h3>执行时间线</h3><span>{formatDate(timeline.started_at)} - {formatDate(timeline.ended_at)}</span></div><div className="timeline-list">{timeline.spans.map((span) => <button key={span.span_id} className={`timeline-row timeline-button ${span.span_id === selectedSpanId ? "selected" : ""}`} style={{ paddingLeft: `${12 + span.depth * 18}px` }} onClick={() => setSelectedSpanId(span.span_id)}><i className={tone(span.status)} /><div><strong>{span.name}</strong><span>{span.kind} · {span.duration_ms === null ? "未结束" : `${Math.round(span.duration_ms)} ms`} · {span.span_id}</span></div><StatusMark status={span.status} /></button>)}</div></div>{selectedSpan && <div className="trace-section span-detail"><div className="trace-section-heading"><h3>Span 数据</h3><span>{selectedSpan.kind} · {selectedSpan.span_id}</span></div><div className="span-json-grid"><div className="detail-block"><h3>输入</h3><pre>{formatJson(selectedSpan.input)}</pre></div><div className="detail-block"><h3>输出</h3><pre>{formatJson(selectedSpan.output)}</pre></div>{selectedSpan.error && <div className="detail-block"><h3>错误</h3><pre>{formatJson(selectedSpan.error)}</pre></div>}<div className="detail-block"><h3>Attributes</h3><pre>{formatJson(selectedSpan.attributes)}</pre></div><div className="detail-block"><h3>Extensions</h3><pre>{formatJson(selectedSpan.extensions)}</pre></div></div></div>}<div className="trace-section"><div className="trace-section-heading"><h3>Trace 扩展字段</h3></div><pre className="trace-json">{formatJson(detail.extensions)}</pre></div></div></> : <div className="panel-placeholder"><Workflow size={24} /><p>从左侧选择一条 Trace 查看执行详情。</p></div>}</section>
      </div>
    </section>
  );
}
