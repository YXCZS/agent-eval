"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  CircleDashed,
  Clock3,
  LoaderCircle,
  Play,
  RefreshCw,
  Square,
  Target,
  XCircle,
} from "lucide-react";

type AgentType = "prompt" | "rag" | "tool" | "custom";
type RunStatus = "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";
type ExecutionStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

type Agent = { id: string; name: string; agent_type: AgentType; active: boolean };
type AgentVersion = { id: string; version: number; label: string; agent_type: AgentType; enabled: boolean };
type Dataset = { id: string; name: string; current_version_id: string | null };
type DatasetVersion = { id: string; version: number; cases: Array<{ id: string }> };
type Evaluator = { id: string; name: string; version: string; evaluator_type: string; supported_agent_types: AgentType[]; enabled: boolean; requires: string[] };
type CaseExecution = { id: string; case_id: string; status: ExecutionStatus; error_type?: string | null; error_message?: string | null };
type Run = { id: string; status: RunStatus; total_cases: number; completed_cases: number; failed_cases: number; agent_version_id: string; dataset_version_id: string; evaluator_version_ids: string[]; created_at: string; case_executions?: CaseExecution[] };
type AgentOption = AgentVersion & { agentName: string; active: boolean };
type DatasetOption = DatasetVersion & { datasetName: string };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PROJECT_ID = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1";
const SESSION = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";

function requestHeaders(): HeadersInit {
  return { "Content-Type": "application/json", "X-Workspace-Session": SESSION };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { ...requestHeaders(), ...init?.headers } });
  const body = await response.json().catch(() => null) as T | { detail?: unknown } | null;
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)).join("；"));
    }
    throw new Error(typeof detail === "string" ? detail : typeof detail === "object" && detail !== null ? JSON.stringify(detail) : `请求失败（${response.status}）`);
  }
  return body as T;
}

function displayStatus(status: RunStatus | ExecutionStatus): string {
  return ({ queued: "排队中", running: "运行中", completed: "已完成", partial: "部分完成", failed: "失败", cancelled: "已取消" })[status];
}

function statusTone(status: RunStatus | ExecutionStatus): "success" | "danger" | "warning" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled" || status === "partial") return "warning";
  return "neutral";
}

function StatusIcon({ status }: { status: RunStatus | ExecutionStatus }) {
  if (status === "completed") return <Check size={14} />;
  if (status === "failed") return <XCircle size={14} />;
  if (status === "cancelled") return <Square size={13} />;
  return <CircleDashed size={14} />;
}

export function RunsView() {
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [agentVersionId, setAgentVersionId] = useState("");
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [evaluatorIds, setEvaluatorIds] = useState<string[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [catalogBusy, setCatalogBusy] = useState(true);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [catalogIssues, setCatalogIssues] = useState<string[]>([]);
  const [notice, setNotice] = useState<{ tone: "success" | "danger" | "neutral"; text: string } | null>(null);
  const pollControllerRef = useRef<AbortController | null>(null);

  const selectedAgent = agents.find((item) => item.id === agentVersionId) ?? null;
  const compatibleEvaluators = useMemo(
    () => evaluators.filter((item) => item.enabled && (!selectedAgent || item.supported_agent_types.includes(selectedAgent.agent_type))),
    [evaluators, selectedAgent],
  );
  const selectedDataset = datasets.find((item) => item.id === datasetVersionId) ?? null;
  const isActive = run?.status === "queued" || run?.status === "running";
  const progress = run && run.total_cases > 0 ? Math.round(((run.completed_cases + run.failed_cases) / run.total_cases) * 100) : 0;
  const queuedCount = run?.case_executions?.filter((item) => item.status === "queued").length ?? Math.max((run?.total_cases ?? 0) - (run?.completed_cases ?? 0) - (run?.failed_cases ?? 0), 0);
  const runningCount = run?.case_executions?.filter((item) => item.status === "running").length ?? 0;

  async function loadCatalog() {
    setCatalogBusy(true);
    try {
      const [agentsResult, datasetsResult, evaluatorsResult, runsResult] = await Promise.allSettled([
        requestJson<Agent[]>(`/projects/${PROJECT_ID}/agents`),
        requestJson<Dataset[]>(`/projects/${PROJECT_ID}/datasets`),
        requestJson<Evaluator[]>(`/projects/${PROJECT_ID}/evaluators`),
        requestJson<Run[]>(`/projects/${PROJECT_ID}/runs`),
      ]);
      const rawAgents = agentsResult.status === "fulfilled" ? agentsResult.value : [];
      const rawDatasets = datasetsResult.status === "fulfilled" ? datasetsResult.value : [];
      const rawEvaluators = evaluatorsResult.status === "fulfilled" ? evaluatorsResult.value : [];
      const runs = runsResult.status === "fulfilled" ? runsResult.value : [];
      const versionIssues: string[] = [];
      const agentVersions = await Promise.all(rawAgents.map(async (agent) => {
        try {
          const versions = await requestJson<AgentVersion[]>(`/projects/${PROJECT_ID}/agents/${agent.id}/versions`);
          return versions.map((version) => ({ ...version, agentName: agent.name, active: agent.active }));
        } catch (error) {
          versionIssues.push(`Agent「${agent.name}」版本：${error instanceof Error ? error.message : "加载失败"}`);
          return [];
        }
      }));
      const datasetVersions = await Promise.all(rawDatasets.map(async (dataset) => {
        try {
          const versions = await requestJson<DatasetVersion[]>(`/projects/${PROJECT_ID}/datasets/${dataset.id}/versions`);
          return versions.map((version) => ({ ...version, datasetName: dataset.name }));
        } catch (error) {
          versionIssues.push(`数据集「${dataset.name}」版本：${error instanceof Error ? error.message : "加载失败"}`);
          return [];
        }
      }));
      const nextAgents = agentVersions.flat().filter((item) => item.active && item.enabled);
      const nextDatasets = datasetVersions.flat();
      setAgents(nextAgents); setDatasets(nextDatasets); setEvaluators(rawEvaluators);
      setCatalogIssues(versionIssues);
      setAgentVersionId((current) => nextAgents.some((item) => item.id === current) ? current : nextAgents[0]?.id || "");
      setDatasetVersionId((current) => nextDatasets.some((item) => item.id === current) ? current : nextDatasets[0]?.id || "");
      const activeRun = runs.find((item) => item.status === "queued" || item.status === "running") ?? runs[0];
      if (activeRun) setRun(await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${activeRun.id}`));
      else setRun(null);
      const failures = [agentsResult, datasetsResult, evaluatorsResult, runsResult].filter((result) => result.status === "rejected").length;
      if (failures || versionIssues.length) {
        const details = [...versionIssues, failures ? `${failures} 个目录接口失败` : ""].filter(Boolean).join("；");
        setNotice({ tone: "danger", text: `部分运行配置加载失败：${details}。请检查 API 后点击刷新目录。` });
      }
    } catch (error) {
      setNotice({ tone: "danger", text: error instanceof Error ? error.message : "无法加载运行配置。" });
    } finally { setCatalogBusy(false); }
  }

  useEffect(() => { void loadCatalog(); }, []);

  useEffect(() => {
    if (!selectedAgent) return;
    setEvaluatorIds((current) => current.filter((id) => compatibleEvaluators.some((item) => item.id === id)));
  }, [selectedAgent, compatibleEvaluators]);

  useEffect(() => {
    const runId = run?.id;
    if (!runId || !isActive) return;
    const controller = new AbortController();
    pollControllerRef.current = controller;
    let timer: number | undefined;
    let stopped = false;
    const poll = async () => {
      try {
        const next = await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${runId}`, { signal: controller.signal });
        if (stopped) return;
        setRun(next);
        if (next.status !== "queued" && next.status !== "running") {
          setNotice({ tone: next.status === "completed" ? "success" : "neutral", text: `运行 ${next.id.slice(0, 8)} 当前状态为${displayStatus(next.status)}。` });
        } else {
          timer = window.setTimeout(() => void poll(), 2000);
        }
      } catch (error: unknown) {
        if (!controller.signal.aborted) {
          setNotice({ tone: "danger", text: error instanceof Error ? `运行进度刷新失败：${error.message}` : "运行进度刷新失败，请稍后重试。" });
          timer = window.setTimeout(() => void poll(), 4000);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 2000);
    return () => { stopped = true; if (timer !== undefined) window.clearTimeout(timer); controller.abort(); if (pollControllerRef.current === controller) pollControllerRef.current = null; };
  }, [isActive, run?.id]);

  function toggleEvaluator(id: string) {
    setEvaluatorIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function createRun() {
    if (!agentVersionId || !datasetVersionId || evaluatorIds.length === 0) {
      setNotice({ tone: "danger", text: "请选择 Agent 版本、数据集版本以及至少一个评估器。" });
      return;
    }
    setSubmitBusy(true); setNotice(null);
    try {
      const created = await requestJson<Run>(`/projects/${PROJECT_ID}/runs`, {
        method: "POST",
        body: JSON.stringify({ agent_version_id: agentVersionId, dataset_version_id: datasetVersionId, evaluator_version_ids: evaluatorIds }),
      });
      setRun(await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${created.id}`));
      setNotice({ tone: "success", text: `运行 ${created.id.slice(0, 8)} 已排队，包含 ${created.total_cases} 个用例。` });
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "无法创建评测运行。" }); }
    finally { setSubmitBusy(false); }
  }

  async function cancelRun() {
    if (!run) return;
    pollControllerRef.current?.abort();
    pollControllerRef.current = null;
    setSubmitBusy(true); setNotice(null);
    try {
      setRun(await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${run.id}/cancel`, { method: "POST" }));
      setNotice({ tone: "neutral", text: "已请求取消，排队中的用例将不会运行。" });
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "无法取消此运行。" }); }
    finally { setSubmitBusy(false); }
  }

  return <section className="runs-workbench">
    <div className="resource-heading runs-heading"><div><p className="eyebrow"><Activity size={14} /> 评测实验</p><h1>评测运行</h1><p>将 Agent、数据集和评估器集合固定为一次可复现的评测。</p></div><button className="outline-button" onClick={() => void loadCatalog()} disabled={catalogBusy}><RefreshCw className={catalogBusy ? "spin" : ""} size={16} /> 刷新目录</button></div>
    <div className="runs-layout">
      <section className="run-config panel">
        <div className="run-panel-header"><div><span className="section-kicker">配置运行</span><strong>选择带版本的输入</strong></div><span>{selectedDataset ? `${selectedDataset.cases.length} 个用例` : "未选择数据集"}</span></div>
        <div className="run-config-body">
          <label className="field-label">Agent 版本<select value={agentVersionId} onChange={(event) => setAgentVersionId(event.target.value)} disabled={catalogBusy || agents.length === 0}><option value="">选择 Agent 版本</option>{agents.map((item) => <option value={item.id} key={item.id}>{item.agentName} / v{item.version} {item.label ? `(${item.label})` : ""}</option>)}</select></label>
          {selectedAgent && <div className="selection-summary"><Target size={16} /><div><strong>{selectedAgent.agentName} v{selectedAgent.version}</strong><span>{selectedAgent.agent_type} Agent {selectedAgent.label ? `- ${selectedAgent.label}` : ""}</span></div></div>}
          <label className="field-label">数据集版本<select value={datasetVersionId} onChange={(event) => setDatasetVersionId(event.target.value)} disabled={catalogBusy || datasets.length === 0}><option value="">选择数据集版本</option>{datasets.map((item) => <option value={item.id} key={item.id}>{item.datasetName} / v{item.version}（{item.cases.length} 个用例）</option>)}</select></label>
          <div className="evaluator-picker"><div className="picker-heading"><div><span className="section-kicker">评估器</span><strong>评分定义</strong></div><span>已选择 {evaluatorIds.length} 个</span></div>{compatibleEvaluators.length > 0 ? compatibleEvaluators.map((item) => <label className="evaluator-option" key={item.id}><input type="checkbox" checked={evaluatorIds.includes(item.id)} onChange={() => toggleEvaluator(item.id)} /><span className="checkbox-mark"><Check size={12} /></span><span className="evaluator-copy"><strong>{item.name}</strong><small>{item.evaluator_type} / v{item.version}{item.requires.length ? ` / 需要 ${item.requires.join(", ")}` : ""}</small></span></label>) : <div className="picker-empty">没有启用的评估器支持此 Agent 类型。</div>}</div>
          <div className="run-config-actions"><span>{catalogBusy ? "正在加载可用版本……" : "运行开始时将固定版本快照。"}</span><button className="primary" onClick={() => void createRun()} disabled={catalogBusy || submitBusy}><Play size={16} /> {submitBusy ? "正在启动……" : "开始评测"}</button></div>
        </div>
      </section>
      <RunProgress run={run} progress={progress} queuedCount={queuedCount} runningCount={runningCount} busy={submitBusy} onCancel={cancelRun} />
    </div>
    {catalogIssues.length > 0 && !notice && <div className="run-notice danger"><span><AlertTriangle size={16} /></span>{catalogIssues.join("；")}</div>}
    {notice && <div className={`run-notice ${notice.tone}`}><span>{notice.tone === "success" ? <Check size={16} /> : notice.tone === "danger" ? <AlertTriangle size={16} /> : <Clock3 size={16} />}</span>{notice.text}</div>}
  </section>;
}

function RunProgress({ run, progress, queuedCount, runningCount, busy, onCancel }: { run: Run | null; progress: number; queuedCount: number; runningCount: number; busy: boolean; onCancel: () => Promise<void> }) {
  if (!run) return <section className="run-progress panel"><div className="run-panel-header"><div><span className="section-kicker">运行状态</span><strong>等待开始</strong></div></div><div className="run-empty"><Activity size={22} /><p>开始评测后，可在此查看用例进度、失败情况和运行时状态。</p></div></section>;
  const active = run.status === "queued" || run.status === "running";
  const errors = run.case_executions?.filter((item) => item.status === "failed").slice(0, 3) ?? [];
  return <section className="run-progress panel"><div className="run-panel-header"><div><span className="section-kicker">运行状态</span><strong>{run.id}</strong></div><span className={`run-status ${statusTone(run.status)}`}><StatusIcon status={run.status} /> {displayStatus(run.status)}</span></div><div className="run-progress-body"><div className="progress-number"><strong>{progress}%</strong><span>{run.total_cases} 个用例中已有 {run.completed_cases + run.failed_cases} 个处理完成</span></div><div className="progress-track"><i style={{ width: `${progress}%` }} /></div><div className="run-counts"><div><span>已完成</span><b>{run.completed_cases}</b></div><div><span>失败</span><b className={run.failed_cases ? "danger-text" : ""}>{run.failed_cases}</b></div><div><span>运行中</span><b>{runningCount}</b></div><div><span>排队中</span><b>{queuedCount}</b></div></div>{errors.length > 0 && <div className="run-errors"><strong><AlertTriangle size={14} /> 最近的用例失败</strong>{errors.map((item) => <div key={item.id}><b>{item.case_id}</b><span>{item.error_type ?? "执行错误"}{item.error_message ? `：${item.error_message}` : ""}</span></div>)}</div>}{active && <button className="outline-button cancel-run" onClick={() => void onCancel()} disabled={busy}><Square size={14} /> 取消运行</button>}</div></section>;
}
