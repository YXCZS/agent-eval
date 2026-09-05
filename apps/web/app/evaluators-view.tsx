"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleAlert,
  CircleCheck,
  CircleOff,
  FlaskConical,
  Plus,
  Save,
} from "lucide-react";

type EvaluatorType = "deterministic" | "llm_judge" | "adapter" | "human";
type AgentType = "prompt" | "rag" | "tool" | "custom";
type Direction = "higher_is_better" | "lower_is_better";
type Evaluator = {
  id: string;
  name: string;
  version: string;
  evaluator_type: EvaluatorType;
  requires: string[];
  supported_agent_types: AgentType[];
  score_min: number | null;
  score_max: number | null;
  direction: Direction;
  default_threshold: number | null;
  rubric: string | null;
  judge_model: string | null;
  config: Record<string, unknown>;
  enabled: boolean;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PROJECT_ID = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1";
const SESSION = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";
const evaluatorTypeLabels: Record<EvaluatorType, string> = {
  deterministic: "确定性规则",
  llm_judge: "LLM Judge",
  adapter: "第三方适配器",
  human: "人工评审",
};
const agentTypeLabels: Record<AgentType, string> = {
  prompt: "Prompt",
  rag: "RAG",
  tool: "Tool",
  custom: "Custom",
};

function headers(): HeadersInit {
  return { "Content-Type": "application/json", "X-Workspace-Session": SESSION };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...headers(), ...init?.headers },
  });
  const body = (await response.json().catch(() => null)) as
    | T
    | { detail?: unknown }
    | null;
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)).join("; "));
    }
    throw new Error(typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`);
  }
  return body as T;
}

function nextVersion(version: string): string {
  const match = version.match(/^(.*?)(\d+)$/);
  return match ? `${match[1]}${Number(match[2]) + 1}` : `${version}-next`;
}

function formatConfig(config: Record<string, unknown>): string {
  return JSON.stringify(config, null, 2);
}

function parseOptionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function EvaluatorsView() {
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [evaluatorType, setEvaluatorType] = useState<EvaluatorType>("deterministic");
  const [supportedTypes, setSupportedTypes] = useState<AgentType[]>(["prompt"]);
  const [requires, setRequires] = useState("");
  const [scoreMin, setScoreMin] = useState("0");
  const [scoreMax, setScoreMax] = useState("1");
  const [threshold, setThreshold] = useState("1");
  const [direction, setDirection] = useState<Direction>("higher_is_better");
  const [rubric, setRubric] = useState("");
  const [judgeModel, setJudgeModel] = useState("");
  const [configText, setConfigText] = useState("{}");
  const selected = evaluators.find((item) => item.id === selectedId) ?? null;

  const grouped = useMemo(() => {
    return evaluators.reduce<Record<string, Evaluator[]>>((groups, evaluator) => {
      (groups[evaluator.name] ??= []).push(evaluator);
      return groups;
    }, {});
  }, [evaluators]);

  async function loadEvaluators(selectId?: string) {
    setLoading(true);
    try {
      const loaded = await requestJson<Evaluator[]>(`/projects/${PROJECT_ID}/evaluators`);
      setEvaluators(loaded);
      const next = loaded.find((item) => item.id === selectId) ?? loaded[0];
      setSelectedId(next?.id ?? "");
      setNotice(null);
    } catch (error) {
      setNotice(`加载评估器失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadEvaluators();
  }, []);

  function resetForm(item?: Evaluator) {
    setFormOpen(true);
    setName(item?.name ?? "");
    setVersion(item ? nextVersion(item.version) : "1.0.0");
    setEvaluatorType(item?.evaluator_type ?? "deterministic");
    setSupportedTypes(item?.supported_agent_types ?? ["prompt"]);
    setRequires(item?.requires.join(", ") ?? "");
    setScoreMin(item?.score_min === null || item?.score_min === undefined ? "" : String(item.score_min));
    setScoreMax(item?.score_max === null || item?.score_max === undefined ? "" : String(item.score_max));
    setThreshold(item?.default_threshold === null || item?.default_threshold === undefined ? "" : String(item.default_threshold));
    setDirection(item?.direction ?? "higher_is_better");
    setRubric(item?.rubric ?? "");
    setJudgeModel(item?.judge_model ?? "");
    setConfigText(item ? formatConfig(item.config) : "{}");
    setNotice(null);
  }

  function toggleAgentType(type: AgentType) {
    setSupportedTypes((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type]);
  }

  async function createEvaluator() {
    if (!name.trim()) {
      setNotice("请填写评估器名称。");
      return;
    }
    if (supportedTypes.length === 0) {
      setNotice("至少选择一种支持的 Agent 类型。");
      return;
    }
    let config: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(configText);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("配置必须是 JSON 对象");
      config = parsed as Record<string, unknown>;
    } catch (error) {
      setNotice(`配置 JSON 无效：${error instanceof Error ? error.message : "无法解析"}`);
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const created = await requestJson<Evaluator>(`/projects/${PROJECT_ID}/evaluators`, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          version: version.trim(),
          evaluator_type: evaluatorType,
          requires: requires.split(",").map((item) => item.trim()).filter(Boolean),
          supported_agent_types: supportedTypes,
          score_min: parseOptionalNumber(scoreMin),
          score_max: parseOptionalNumber(scoreMax),
          direction,
          default_threshold: parseOptionalNumber(threshold),
          rubric: rubric.trim() || null,
          judge_model: judgeModel.trim() || null,
          config,
        }),
      });
      await loadEvaluators(created.id);
      setFormOpen(false);
      setNotice(`评估器 ${created.name} ${created.version} 已创建。`);
    } catch (error) {
      setNotice(`创建失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled(item: Evaluator) {
    setBusy(true);
    setNotice(null);
    try {
      const updated = await requestJson<Evaluator>(`/projects/${PROJECT_ID}/evaluators/${item.id}/enabled?enabled=${!item.enabled}`, { method: "PATCH" });
      setEvaluators((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate));
      setNotice(`${updated.name} ${updated.version} 已${updated.enabled ? "启用" : "停用"}。`);
    } catch (error) {
      setNotice(`状态更新失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="resource-view evaluator-workbench">
      <div className="resource-heading">
        <div>
          <p className="eyebrow"><FlaskConical size={14} /> 评分定义</p>
          <h1>评估器</h1>
          <p>每个评估器都是一个可复用的评分规则。版本创建后不可修改，只能创建新版本，保证历史报告可复现。</p>
        </div>
        <button className="primary" onClick={() => resetForm()}><Plus size={17} /> 新建评估器</button>
      </div>
      {notice && <div className="inline-notice" role="status"><CircleAlert size={16} /> {notice}</div>}
      <div className="evaluator-layout">
        <aside className="panel evaluator-catalog">
          <div className="panel-heading"><div><p className="eyebrow">已注册规则</p><h2>{evaluators.length} 个版本</h2></div><FlaskConical size={16} className="muted-icon" /></div>
          {loading ? <p className="panel-placeholder">正在加载评估器...</p> : Object.keys(grouped).length === 0 ? <div className="panel-placeholder">还没有评估器，请先创建一个。</div> : <div className="evaluator-list">{Object.entries(grouped).map(([groupName, versions]) => <div key={groupName} className="evaluator-group"><strong>{groupName}</strong>{versions.map((item) => <button key={item.id} className={`evaluator-list-item ${item.id === selectedId ? "selected" : ""}`} onClick={() => { setSelectedId(item.id); setFormOpen(false); setNotice(null); }}><span><b>{item.version}</b><small>{evaluatorTypeLabels[item.evaluator_type]}</small></span><i className={item.enabled ? "enabled" : "disabled"}>{item.enabled ? "启用" : "停用"}</i></button>)}</div>)}</div>}
        </aside>
        <div className="panel evaluator-detail">
          {formOpen ? <>
            <div className="panel-heading"><div><p className="eyebrow">新版本</p><h2>{name || "新建评估器"}</h2></div><Save size={16} className="muted-icon" /></div>
            <div className="evaluator-form">
              <div className="field-grid two"><label className="field-label">名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 task_success" /></label><label className="field-label">版本<input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="例如 1.0.0" /></label></div>
              <div className="field-grid two"><label className="field-label">评估器类型<select value={evaluatorType} onChange={(event) => setEvaluatorType(event.target.value as EvaluatorType)}>{Object.entries(evaluatorTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field-label">方向<select value={direction} onChange={(event) => setDirection(event.target.value as Direction)}><option value="higher_is_better">分数越高越好</option><option value="lower_is_better">分数越低越好</option></select></label></div>
              <fieldset className="check-field"><legend>支持的 Agent 类型</legend><div className="check-grid">{(Object.keys(agentTypeLabels) as AgentType[]).map((type) => <label key={type}><input type="checkbox" checked={supportedTypes.includes(type)} onChange={() => toggleAgentType(type)} /><span>{supportedTypes.includes(type) ? <Check size={13} /> : null}</span>{agentTypeLabels[type]}</label>)}</div></fieldset>
              <label className="field-label">依赖字段<input value={requires} onChange={(event) => setRequires(event.target.value)} placeholder="用逗号分隔，例如 expected_output, expected_state" /><small>运行前会检查测试用例是否提供这些字段。</small></label>
              <div className="field-grid three"><label className="field-label">最低分<input type="number" value={scoreMin} onChange={(event) => setScoreMin(event.target.value)} /></label><label className="field-label">最高分<input type="number" value={scoreMax} onChange={(event) => setScoreMax(event.target.value)} /></label><label className="field-label">默认阈值<input type="number" value={threshold} onChange={(event) => setThreshold(event.target.value)} /></label></div>
              <label className="field-label">评分标准（可选）<textarea value={rubric} onChange={(event) => setRubric(event.target.value)} rows={3} placeholder="描述 LLM Judge 或人工评审的评分规则" /></label>
              <div className="field-grid two"><label className="field-label">Judge 模型（可选）<input value={judgeModel} onChange={(event) => setJudgeModel(event.target.value)} placeholder="例如 gpt-4o-mini" /></label><label className="field-label">配置 JSON<textarea value={configText} onChange={(event) => setConfigText(event.target.value)} rows={3} /></label></div>
              <div className="editor-actions"><button className="outline-button" onClick={() => setFormOpen(false)}>取消</button><button className="primary" onClick={() => void createEvaluator()} disabled={busy}><Save size={16} /> 创建版本</button></div>
            </div>
          </> : selected ? <>
            <div className="panel-heading"><div><p className="eyebrow">评估器详情</p><h2>{selected.name} <span className="version-badge">{selected.version}</span></h2></div><button className="outline-button compact" onClick={() => resetForm(selected)}><Plus size={15} /> 新建版本</button></div>
            <div className="evaluator-detail-body"><div className="detail-stat-grid"><div><span>类型</span><strong>{evaluatorTypeLabels[selected.evaluator_type]}</strong></div><div><span>评分方向</span><strong>{selected.direction === "higher_is_better" ? "越高越好" : "越低越好"}</strong></div><div><span>默认阈值</span><strong>{selected.default_threshold ?? "未设置"}</strong></div><div><span>状态</span><strong className={selected.enabled ? "text-success" : "text-muted"}>{selected.enabled ? "已启用" : "已停用"}</strong></div></div><div className="detail-block"><h3>支持的 Agent</h3><div className="tag-list">{selected.supported_agent_types.map((type) => <span key={type}>{agentTypeLabels[type]}</span>)}</div></div><div className="detail-block"><h3>运行依赖</h3><p className="detail-muted">{selected.requires.length ? selected.requires.join("、") : "无需额外字段"}</p></div>{(selected.rubric || selected.judge_model) && <div className="detail-block"><h3>评审配置</h3>{selected.judge_model && <p className="detail-muted">Judge 模型：{selected.judge_model}</p>}{selected.rubric && <p className="rubric-text">{selected.rubric}</p>}</div>}<div className="detail-block"><h3>原始配置</h3><pre>{formatConfig(selected.config)}</pre></div><button className="outline-button" onClick={() => void toggleEnabled(selected)} disabled={busy}>{selected.enabled ? <><CircleOff size={16} /> 停用此版本</> : <><CircleCheck size={16} /> 启用此版本</>}</button></div>
          </> : <div className="panel-placeholder"><FlaskConical size={24} /><p>选择一个评估器查看详情，或创建第一个评估器。</p></div>}
        </div>
      </div>
    </section>
  );
}
