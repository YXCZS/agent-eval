"use client";

import { useEffect, useMemo, useState } from "react";
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
type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
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
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return body as T;
}

function displayStatus(status: RunStatus | ExecutionStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function statusTone(status: RunStatus | ExecutionStatus): "success" | "danger" | "warning" | "neutral" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "warning";
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
  const [notice, setNotice] = useState<{ tone: "success" | "danger" | "neutral"; text: string } | null>(null);

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
      const [rawAgents, rawDatasets, rawEvaluators, runs] = await Promise.all([
        requestJson<Agent[]>(`/projects/${PROJECT_ID}/agents`),
        requestJson<Dataset[]>(`/projects/${PROJECT_ID}/datasets`),
        requestJson<Evaluator[]>(`/projects/${PROJECT_ID}/evaluators`),
        requestJson<Run[]>(`/projects/${PROJECT_ID}/runs`),
      ]);
      const agentVersions = await Promise.all(rawAgents.map(async (agent) => {
        const versions = await requestJson<AgentVersion[]>(`/projects/${PROJECT_ID}/agents/${agent.id}/versions`);
        return versions.map((version) => ({ ...version, agentName: agent.name, active: agent.active }));
      }));
      const datasetVersions = await Promise.all(rawDatasets.map(async (dataset) => {
        const versions = await requestJson<DatasetVersion[]>(`/projects/${PROJECT_ID}/datasets/${dataset.id}/versions`);
        return versions.map((version) => ({ ...version, datasetName: dataset.name }));
      }));
      const nextAgents = agentVersions.flat().filter((item) => item.active && item.enabled);
      const nextDatasets = datasetVersions.flat();
      setAgents(nextAgents); setDatasets(nextDatasets); setEvaluators(rawEvaluators);
      setAgentVersionId((current) => current || nextAgents[0]?.id || "");
      setDatasetVersionId((current) => current || nextDatasets[0]?.id || "");
      const activeRun = runs.find((item) => item.status === "queued" || item.status === "running");
      if (activeRun) setRun(await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${activeRun.id}`));
    } catch (error) {
      setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Could not load run configuration." });
    } finally { setCatalogBusy(false); }
  }

  useEffect(() => { void loadCatalog(); }, []);

  useEffect(() => {
    if (!selectedAgent) return;
    setEvaluatorIds((current) => current.filter((id) => compatibleEvaluators.some((item) => item.id === id)));
  }, [selectedAgent, compatibleEvaluators]);

  useEffect(() => {
    if (!run || !isActive) return;
    const timer = window.setInterval(() => {
      void requestJson<Run>(`/projects/${PROJECT_ID}/runs/${run.id}`)
        .then((next) => { setRun(next); if (next.status !== "queued" && next.status !== "running") setNotice({ tone: next.status === "completed" ? "success" : "neutral", text: `Run ${next.id.slice(0, 8)} is ${next.status}.` }); })
        .catch((error: unknown) => setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Could not refresh run progress." }));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [isActive, run]);

  function toggleEvaluator(id: string) {
    setEvaluatorIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function createRun() {
    if (!agentVersionId || !datasetVersionId || evaluatorIds.length === 0) {
      setNotice({ tone: "danger", text: "Choose an agent version, dataset version, and at least one evaluator." });
      return;
    }
    setSubmitBusy(true); setNotice(null);
    try {
      const created = await requestJson<Run>(`/projects/${PROJECT_ID}/runs`, {
        method: "POST",
        body: JSON.stringify({ agent_version_id: agentVersionId, dataset_version_id: datasetVersionId, evaluator_version_ids: evaluatorIds }),
      });
      setRun(await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${created.id}`));
      setNotice({ tone: "success", text: `Run ${created.id.slice(0, 8)} queued with ${created.total_cases} cases.` });
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Could not create evaluation run." }); }
    finally { setSubmitBusy(false); }
  }

  async function cancelRun() {
    if (!run) return;
    setSubmitBusy(true); setNotice(null);
    try {
      setRun(await requestJson<Run>(`/projects/${PROJECT_ID}/runs/${run.id}/cancel`, { method: "POST" }));
      setNotice({ tone: "neutral", text: "Cancellation requested. Queued cases will not run." });
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Could not cancel this run." }); }
    finally { setSubmitBusy(false); }
  }

  return <section className="runs-workbench">
    <div className="resource-heading runs-heading"><div><p className="eyebrow"><Activity size={14} /> Experiments</p><h1>Evaluation runs</h1><p>Freeze an agent, dataset and evaluator set into one reproducible evaluation.</p></div><button className="outline-button" onClick={() => void loadCatalog()} disabled={catalogBusy}><RefreshCw className={catalogBusy ? "spin" : ""} size={16} /> Refresh catalog</button></div>
    <div className="runs-layout">
      <section className="run-config panel">
        <div className="run-panel-header"><div><span className="section-kicker">Configure run</span><strong>Choose versioned inputs</strong></div><span>{selectedDataset ? `${selectedDataset.cases.length} cases` : "No dataset selected"}</span></div>
        <div className="run-config-body">
          <label className="field-label">Agent version<select value={agentVersionId} onChange={(event) => setAgentVersionId(event.target.value)} disabled={catalogBusy || agents.length === 0}><option value="">Select an agent version</option>{agents.map((item) => <option value={item.id} key={item.id}>{item.agentName} / v{item.version} {item.label ? `(${item.label})` : ""}</option>)}</select></label>
          {selectedAgent && <div className="selection-summary"><Target size={16} /><div><strong>{selectedAgent.agentName} v{selectedAgent.version}</strong><span>{selectedAgent.agent_type} agent {selectedAgent.label ? `- ${selectedAgent.label}` : ""}</span></div></div>}
          <label className="field-label">Dataset version<select value={datasetVersionId} onChange={(event) => setDatasetVersionId(event.target.value)} disabled={catalogBusy || datasets.length === 0}><option value="">Select a dataset version</option>{datasets.map((item) => <option value={item.id} key={item.id}>{item.datasetName} / v{item.version} ({item.cases.length} cases)</option>)}</select></label>
          <div className="evaluator-picker"><div className="picker-heading"><div><span className="section-kicker">Evaluators</span><strong>Scoring definitions</strong></div><span>{evaluatorIds.length} selected</span></div>{compatibleEvaluators.length > 0 ? compatibleEvaluators.map((item) => <label className="evaluator-option" key={item.id}><input type="checkbox" checked={evaluatorIds.includes(item.id)} onChange={() => toggleEvaluator(item.id)} /><span className="checkbox-mark"><Check size={12} /></span><span className="evaluator-copy"><strong>{item.name}</strong><small>{item.evaluator_type} / v{item.version}{item.requires.length ? ` / needs ${item.requires.join(", ")}` : ""}</small></span></label>) : <div className="picker-empty">No enabled evaluators support this Agent type.</div>}</div>
          <div className="run-config-actions"><span>{catalogBusy ? "Loading available versions..." : "Version snapshots are frozen when the run starts."}</span><button className="primary" onClick={() => void createRun()} disabled={catalogBusy || submitBusy}><Play size={16} /> {submitBusy ? "Starting..." : "Start evaluation"}</button></div>
        </div>
      </section>
      <RunProgress run={run} progress={progress} queuedCount={queuedCount} runningCount={runningCount} busy={submitBusy} onCancel={cancelRun} />
    </div>
    {notice && <div className={`run-notice ${notice.tone}`}><span>{notice.tone === "success" ? <Check size={16} /> : notice.tone === "danger" ? <AlertTriangle size={16} /> : <Clock3 size={16} />}</span>{notice.text}</div>}
  </section>;
}

function RunProgress({ run, progress, queuedCount, runningCount, busy, onCancel }: { run: Run | null; progress: number; queuedCount: number; runningCount: number; busy: boolean; onCancel: () => Promise<void> }) {
  if (!run) return <section className="run-progress panel"><div className="run-panel-header"><div><span className="section-kicker">Run status</span><strong>Waiting to start</strong></div></div><div className="run-empty"><Activity size={22} /><p>Start an evaluation to see sample progress, failures and runtime state here.</p></div></section>;
  const active = run.status === "queued" || run.status === "running";
  const errors = run.case_executions?.filter((item) => item.status === "failed").slice(0, 3) ?? [];
  return <section className="run-progress panel"><div className="run-panel-header"><div><span className="section-kicker">Run status</span><strong>{run.id}</strong></div><span className={`run-status ${statusTone(run.status)}`}><StatusIcon status={run.status} /> {displayStatus(run.status)}</span></div><div className="run-progress-body"><div className="progress-number"><strong>{progress}%</strong><span>{run.completed_cases + run.failed_cases} of {run.total_cases} cases settled</span></div><div className="progress-track"><i style={{ width: `${progress}%` }} /></div><div className="run-counts"><div><span>Completed</span><b>{run.completed_cases}</b></div><div><span>Failed</span><b className={run.failed_cases ? "danger-text" : ""}>{run.failed_cases}</b></div><div><span>Running</span><b>{runningCount}</b></div><div><span>Queued</span><b>{queuedCount}</b></div></div>{errors.length > 0 && <div className="run-errors"><strong><AlertTriangle size={14} /> Recent sample failures</strong>{errors.map((item) => <div key={item.id}><b>{item.case_id}</b><span>{item.error_type ?? "execution_error"}{item.error_message ? `: ${item.error_message}` : ""}</span></div>)}</div>}{active && <button className="outline-button cancel-run" onClick={() => void onCancel()} disabled={busy}><Square size={14} /> Cancel run</button>}</div></section>;
}
