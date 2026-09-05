"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, Check, CircleAlert, Clock3, CopyPlus, ExternalLink, Globe2, Play, Plus, Save, Server, SlidersHorizontal, Sparkles, TestTube2, XCircle } from "lucide-react";

type AgentType = "prompt" | "rag" | "tool" | "custom";
type ConnectionState = { tone: "success" | "danger"; message: string; detail?: string; latency?: number } | null;
type PromptConfig = { provider: string; model: string; endpoint: string; system_prompt: string; user_template: string; variable_names: string[]; temperature: number; top_p: number; max_tokens: number | null; response_format: Record<string, unknown> | null; timeout_seconds: number; concurrency_limit: number; max_retries: number };
type EndpointConfig = { url: string; method: "POST"; auth_ref: string | null; protocol_version: string; timeout_seconds: number; max_response_bytes: number; max_tool_calls: number; concurrency_limit: number; max_retries: number };
type AgentVersion = { id?: string; version: number; label: string; enabled: boolean; prompt_config?: PromptConfig; endpoint_config?: EndpointConfig };
type Agent = { id: string; name: string; type: AgentType; description: string; active: boolean; versions: AgentVersion[] };
type AgentApi = { id: string; name: string; agent_type: AgentType; description: string | null; active: boolean };
type AgentVersionApi = { id: string; agent_id: string; version: number; label: string; agent_type: AgentType; prompt_config: PromptConfig | null; endpoint_config: EndpointConfig | null; enabled: boolean };

const promptConfig: PromptConfig = { provider: "OpenAI-compatible", model: "gpt-4o-mini", endpoint: "https://api.openai.com/v1/chat/completions", system_prompt: "You are a precise support assistant.", user_template: "Answer the customer question:\n\n{{question}}", variable_names: ["question"], temperature: 0.2, top_p: 1, max_tokens: 600, response_format: null, timeout_seconds: 60, concurrency_limit: 4, max_retries: 2 };
const endpointConfig: EndpointConfig = { url: "http://localhost:8080/run", method: "POST", auth_ref: null, protocol_version: "v1", timeout_seconds: 30, max_response_bytes: 1048576, max_tool_calls: 32, concurrency_limit: 4, max_retries: 2 };
const typeLabels: Record<AgentType, string> = { prompt: "Prompt", rag: "RAG", tool: "Tool", custom: "Custom" };

function freshVersion(type: AgentType, version = 1): AgentVersion {
  return type === "prompt" ? { version, label: `新建 Prompt v${version}`, enabled: true, prompt_config: { ...promptConfig } } : { version, label: `新建 ${type} v${version}`, enabled: true, endpoint_config: { ...endpointConfig } };
}
function renderTemplate(template: string, variables: Record<string, unknown>) {
  return template.replace(/\{\{?([A-Za-z_][A-Za-z0-9_]*)\}?\}/g, (_, name: string) => { const value = variables[name]; return value === undefined ? `{{${name}}}` : typeof value === "string" ? value : JSON.stringify(value); });
}
function parseVariables(source: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(source);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("变量必须是 JSON 对象");
  return parsed as Record<string, unknown>;
}

function requestHeaders(): HeadersInit {
  return { "Content-Type": "application/json", "X-Workspace-Session": process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "" };
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}${path}`, {
    ...init,
    headers: { ...requestHeaders(), ...init?.headers },
  });
  const body = await response.json().catch(() => null) as T | { detail?: unknown } | null;
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)).join("；"));
    }
    throw new Error(typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`);
  }
  return body as T;
}

function toUiAgent(agent: AgentApi, versions: AgentVersionApi[]): Agent {
  return {
    id: agent.id,
    name: agent.name,
    type: agent.agent_type,
    description: agent.description ?? "",
    active: agent.active,
    versions: versions.map((version) => ({ ...version, prompt_config: version.prompt_config ?? undefined, endpoint_config: version.endpoint_config ?? undefined })),
  };
}

export function AgentsView() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<Agent>({ id: "", name: "", type: "prompt", description: "", active: true, versions: [freshVersion("prompt")] });
  const [selectedVersion, setSelectedVersion] = useState(1);
  const [isNew, setIsNew] = useState(false);
  const [variablesText, setVariablesText] = useState('{\n  "question": "Can I cancel an order after it ships?"\n}');
  const [schemaText, setSchemaText] = useState("");
  const [connection, setConnection] = useState<ConnectionState>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const currentVersion = draft.versions.find((version) => version.version === selectedVersion) ?? draft.versions[0];
  const currentPrompt = currentVersion?.prompt_config;
  const currentEndpoint = currentVersion?.endpoint_config;
  const preview = useMemo(() => { if (!currentPrompt) return "HTTP Agent 会通过 /run 协议接收以下示例输入。"; try { return renderTemplate(currentPrompt.user_template, parseVariables(variablesText)); } catch { return "请输入 JSON 对象以渲染 Prompt 预览。"; } }, [currentPrompt, variablesText]);

  async function loadAgents(selectId?: string) {
    setBusy(true);
    try {
      const rawAgents = await requestJson<AgentApi[]>(`/projects/${process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1"}/agents`);
      const loaded = await Promise.all(rawAgents.map(async (agent) => {
        const versions = await requestJson<AgentVersionApi[]>(`/projects/${process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1"}/agents/${agent.id}/versions`);
        return toUiAgent(agent, versions);
      }));
      setAgents(loaded);
      const next = loaded.find((agent) => agent.id === selectId) ?? loaded[0];
      if (next) selectAgent(next);
      else if (!selectId) startNew();
    } catch (error) {
      setNotice(error instanceof Error ? `加载 Agent 失败：${error.message}` : "加载 Agent 失败。");
    } finally { setBusy(false); }
  }

  useEffect(() => { void loadAgents(); }, []);

  function selectAgent(agent: Agent) {
    const version = agent.versions[agent.versions.length - 1] ?? freshVersion(agent.type);
    setSelectedId(agent.id); setDraft({ ...agent, versions: agent.versions.map((item) => ({ ...item, prompt_config: item.prompt_config ? { ...item.prompt_config } : undefined, endpoint_config: item.endpoint_config ? { ...item.endpoint_config } : undefined })) }); setSelectedVersion(version.version); setIsNew(false); setConnection(null); setNotice(null); setSchemaText(version.prompt_config?.response_format ? JSON.stringify(version.prompt_config.response_format, null, 2) : "");
  }
  function startNew() {
    const type: AgentType = "prompt"; setSelectedId(""); setDraft({ id: "", name: "", type, description: "", active: true, versions: [freshVersion(type)] }); setSelectedVersion(1); setIsNew(true); setConnection(null); setNotice(null); setSchemaText("");
  }
  function changeType(type: AgentType) { setDraft((current) => ({ ...current, type, versions: [freshVersion(type, currentVersion?.version ?? 1)] })); setSelectedVersion(currentVersion?.version ?? 1); setConnection(null); }
  function updatePrompt(field: keyof PromptConfig, value: string | number | null) { setDraft((current) => ({ ...current, versions: current.versions.map((version) => version.version === selectedVersion ? { ...version, prompt_config: { ...version.prompt_config!, [field]: value } } : version) })); }
  function updateEndpoint(field: keyof EndpointConfig, value: string | number | null) { setDraft((current) => ({ ...current, versions: current.versions.map((version) => version.version === selectedVersion ? { ...version, endpoint_config: { ...version.endpoint_config!, [field]: value } } : version) })); }
  function schemaValue(): Record<string, unknown> | null {
    if (!schemaText.trim()) return null;
    const parsed: unknown = JSON.parse(schemaText);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("响应 Schema 必须是 JSON 对象。");
    return parsed as Record<string, unknown>;
  }

  async function saveVersion() {
    if (!draft.name.trim()) { setNotice("必须填写 Agent 名称。"); return; }
    if (draft.type === "prompt" && !currentPrompt?.user_template.trim()) { setNotice("必须填写用户模板。"); return; }
    if (draft.type !== "prompt") { try { new URL(currentEndpoint?.url ?? ""); } catch { setNotice("请输入有效的 HTTP 端点 URL。"); return; } }
    let responseFormat: Record<string, unknown> | null = null;
    try { responseFormat = schemaValue(); } catch (error) { setNotice(error instanceof Error ? error.message : "响应 Schema 无效。"); return; }
    const projectId = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1";
    const config = draft.type === "prompt" && currentPrompt ? { ...currentPrompt, response_format: responseFormat } : undefined;
    const endpoint = draft.type !== "prompt" ? currentEndpoint : undefined;
    setBusy(true); setNotice(null);
    try {
      if (isNew) {
        const created = await requestJson<AgentApi>(`/projects/${projectId}/agents`, { method: "POST", body: JSON.stringify({ name: draft.name.trim(), agent_type: draft.type, description: draft.description.trim() || null, prompt_config: config, endpoint_config: endpoint }) });
        await loadAgents(created.id);
        setIsNew(false);
        setNotice("Agent 已创建并保存到当前工作区。");
      } else {
        await requestJson<AgentVersionApi>(`/projects/${projectId}/agents/${draft.id}/versions`, { method: "POST", body: JSON.stringify({ name: draft.name.trim(), label: `${draft.name.trim()} v${(currentVersion?.version ?? 0) + 1}`, agent_type: draft.type, description: draft.description.trim() || null, prompt_config: config, endpoint_config: endpoint }) });
        await loadAgents(draft.id);
        setNotice("已保存为新的 Agent 版本。");
      }
      setConnection(null);
    } catch (error) { setNotice(error instanceof Error ? `保存失败：${error instanceof Error ? error.message : "未知错误"}` : "保存失败。"); }
    finally { setBusy(false); }
  }
  function saveAsVersion() {
    const next = Math.max(...draft.versions.map((version) => version.version), 0) + 1;
    const copied = currentVersion ? { ...currentVersion, version: next, label: `${draft.name || "Agent"} v${next}`, prompt_config: currentPrompt ? { ...currentPrompt } : undefined, endpoint_config: currentEndpoint ? { ...currentEndpoint } : undefined } : freshVersion(draft.type, next);
    setDraft((current) => ({ ...current, versions: [copied, ...current.versions] })); setSelectedVersion(next); setNotice(`已创建草稿版本 ${next}，配置完成后请保存。`); setConnection(null);
  }
  async function testConnection() {
    setConnection(null); setNotice(null); let variables: Record<string, unknown> = {};
    try { variables = parseVariables(variablesText); } catch (error) { setConnection({ tone: "danger", message: "变量不是有效的 JSON。", detail: error instanceof Error ? error.message : "请先修正示例变量。" }); return; }
    let responseFormat: Record<string, unknown> | null = null;
    try { responseFormat = schemaValue(); } catch { setConnection({ tone: "danger", message: "响应架构不是有效的 JSON。", detail: "测试前请先修正架构。" }); return; }
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"; const projectId = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1"; const session = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";
    const body = draft.type === "prompt" ? { agent_type: draft.type, prompt_config: { ...currentPrompt, response_format: responseFormat }, input: variables, variables, messages: [] } : { agent_type: draft.type, endpoint_config: currentEndpoint, input: variables, variables, messages: [] };
    const started = performance.now();
    try {
      const response = await fetch(`${apiBase}/projects/${projectId}/agents/connection-test`, { method: "POST", headers: { "Content-Type": "application/json", "X-Workspace-Session": session }, body: JSON.stringify(body) });
      const result = await response.json() as { success?: boolean; message?: string; error_type?: string; latency_ms?: number; output?: unknown; rendered_prompt?: string; detail?: unknown };
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `API 返回了 HTTP ${response.status}`);
      if (!result.success) { setConnection({ tone: "danger", message: result.message ?? "连接测试失败。", detail: result.error_type, latency: result.latency_ms }); return; }
      setConnection({ tone: "success", message: result.message ?? "连接成功。", detail: result.output ? `输出：${JSON.stringify(result.output).slice(0, 180)}` : result.rendered_prompt ? "Prompt 已成功渲染。" : "端点已接受请求。", latency: result.latency_ms ?? performance.now() - started });
    } catch (error) { setConnection({ tone: "danger", message: "连接测试无法访问 API。", detail: error instanceof Error ? error.message : "请检查 NEXT_PUBLIC_API_URL 和 API 服务。" }); }
  }

  return <section className="agents-workbench">
    <div className="resource-heading agent-heading"><div><p className="eyebrow"><Bot size={14} /> 执行目标</p><h1>Agent 管理</h1><p>配置评测用例将调用的运行器。每个已保存的配置都会成为可选择的版本。</p></div><button className="primary" onClick={startNew}><Plus size={17} /> 新建 Agent</button></div>
    <div className="agents-layout">
      <aside className="agent-catalog panel"><div className="catalog-heading"><div><span className="section-kicker">工作区 Agent</span><strong>{agents.length} 个已注册</strong></div><SlidersHorizontal size={16} /></div><div className="agent-list">{agents.map((agent) => <button key={agent.id} className={`agent-list-item ${agent.id === selectedId ? "selected" : ""}`} onClick={() => selectAgent(agent)}><span className={`agent-list-icon type-${agent.type}`}>{agent.type === "prompt" ? <Sparkles size={16} /> : agent.type === "rag" ? <Server size={16} /> : <Bot size={16} />}</span><span className="agent-list-copy"><strong>{agent.name}</strong><span>{typeLabels[agent.type]} · v{Math.max(...agent.versions.map((version) => version.version))}</span></span><span className={`live-dot ${agent.active ? "on" : ""}`} /></button>)}</div><button className="catalog-add" onClick={startNew}><CopyPlus size={15} /> 注册另一个 Agent</button></aside>
      <div className="agent-editor panel"><div className="editor-header"><div><span className="section-kicker">{isNew ? "新建注册" : "配置编辑器"}</span><strong>{isNew ? "连接 Agent" : draft.name}</strong></div><span className={`state-chip ${draft.active ? "active" : ""}`}>{draft.active ? "运行中" : "已暂停"}</span></div><div className="editor-scroll"><label className="field-label">Agent 名称<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="例如：账单助手" /></label><label className="field-label">描述<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={2} placeholder="说明此 Agent 负责的工作" /></label><div className="field-label"><span>执行类型</span><div className="type-switch">{(Object.keys(typeLabels) as AgentType[]).map((type) => <button key={type} className={draft.type === type ? "chosen" : ""} disabled={!isNew || busy} onClick={() => changeType(type)}>{typeLabels[type]}</button>)}</div>{!isNew && <small>注册后 Agent 类型不可更改。</small>}</div><div className="version-line"><label className="field-label">版本<select value={selectedVersion} onChange={(event) => { const value = Number(event.target.value); setSelectedVersion(value); const version = draft.versions.find((item) => item.version === value); setSchemaText(version?.prompt_config?.response_format ? JSON.stringify(version.prompt_config.response_format, null, 2) : ""); setConnection(null); }} disabled={busy}>{draft.versions.map((version) => <option key={version.version} value={version.version}>{version.label}{version.enabled ? " · 已启用" : " · 已禁用"}</option>)}</select></label><button className="outline-button compact" onClick={saveAsVersion} disabled={busy || isNew}><CopyPlus size={15} /> 新建版本</button></div>{draft.type === "prompt" && currentPrompt ? <PromptFields config={currentPrompt} update={updatePrompt} /> : currentEndpoint ? <EndpointFields config={currentEndpoint} update={updateEndpoint} type={draft.type} /> : null}<div className="editor-actions"><button className="outline-button" onClick={() => void testConnection()} disabled={busy}><TestTube2 size={16} /> 测试连接</button><button className="primary" onClick={() => void saveVersion()} disabled={busy}><Save size={16} /> {isNew ? "创建 Agent" : "保存草稿"}</button></div>{notice && <div className="inline-notice"><CircleAlert size={16} />{notice}</div>}</div></div>
      <div className="agent-side-stack"><section className="preview-panel panel"><div className="panel-heading"><div><p className="eyebrow">实时预览</p><h2>{draft.type === "prompt" ? "渲染后的 Prompt" : "请求示例"}</h2></div><ExternalLink size={16} className="muted-icon" /></div>{draft.type === "prompt" ? <><pre className="prompt-preview">{preview}</pre><div className="sample-box"><span>示例变量</span><textarea value={variablesText} onChange={(event) => setVariablesText(event.target.value)} rows={5} /></div></> : <div className="http-preview"><div><Globe2 size={18} /><strong>POST {currentEndpoint?.url || "尚未设置端点"}</strong></div><pre>{JSON.stringify({ input: { question: "Can I cancel an order?" }, variables: { question: "Can I cancel an order?" }, metadata: { case_id: "connection-test" }, trace_id: "generated-at-run-time" }, null, 2)}</pre></div>}</section><section className="test-panel panel"><div className="panel-heading"><div><p className="eyebrow">连接检查</p><h2>单次示例请求</h2></div><Clock3 size={16} className="muted-icon" /></div>{connection ? <div className={`connection-result ${connection.tone}`}><div className="connection-title">{connection.tone === "success" ? <Check size={18} /> : <XCircle size={18} />}<strong>{connection.message}</strong></div>{connection.latency !== undefined && <span>{Math.round(connection.latency)} ms</span>}<small>{connection.detail}</small></div> : <div className="test-empty"><Play size={17} /><span>运行一次受限请求，验证当前配置。</span></div>}</section></div>
    </div>
    {draft.type === "prompt" && currentPrompt && <section className="advanced-panel panel"><div className="panel-heading"><div><p className="eyebrow">结构化输出</p><h2>响应架构</h2></div><span className="optional-label">可选 JSON Schema</span></div><textarea className="schema-editor" value={schemaText} onChange={(event) => setSchemaText(event.target.value)} placeholder={'{\n  "type": "object",\n  "properties": { "answer": { "type": "string" } }\n}'} rows={7} /></section>}
  </section>;
}

function PromptFields({ config, update }: { config: PromptConfig; update: (field: keyof PromptConfig, value: string | number | null) => void }) {
  return <div className="config-section"><div className="config-section-title"><Sparkles size={15} /><strong>Prompt 运行器</strong><span>兼容 OpenAI</span></div><div className="field-grid two"><label className="field-label">提供商<input value={config.provider} onChange={(event) => update("provider", event.target.value)} /></label><label className="field-label">模型<input value={config.model} onChange={(event) => update("model", event.target.value)} /></label></div><label className="field-label">端点<input value={config.endpoint} onChange={(event) => update("endpoint", event.target.value)} /></label><label className="field-label">系统 Prompt<textarea value={config.system_prompt} onChange={(event) => update("system_prompt", event.target.value)} rows={3} /></label><label className="field-label">用户模板<textarea value={config.user_template} onChange={(event) => update("user_template", event.target.value)} rows={4} /><small>使用命名变量，例如 {"{{question}}"}。</small></label><div className="field-grid three"><label className="field-label">Temperature<input type="number" min="0" max="2" step="0.1" value={config.temperature} onChange={(event) => update("temperature", Number(event.target.value))} /></label><label className="field-label">Top p<input type="number" min="0.01" max="1" step="0.05" value={config.top_p} onChange={(event) => update("top_p", Number(event.target.value))} /></label><label className="field-label">最大 Token 数<input type="number" min="1" value={config.max_tokens ?? ""} onChange={(event) => update("max_tokens", event.target.value ? Number(event.target.value) : null)} /></label></div></div>;
}

function EndpointFields({ config, update, type }: { config: EndpointConfig; update: (field: keyof EndpointConfig, value: string | number | null) => void; type: AgentType }) {
  return <div className="config-section"><div className="config-section-title"><Globe2 size={15} /><strong>HTTP 适配器</strong><span>{typeLabels[type]} /run 协议</span></div><label className="field-label">Agent 端点<input value={config.url} onChange={(event) => update("url", event.target.value)} placeholder="https://your-agent.example.com/run" /></label><div className="field-grid two"><label className="field-label">认证引用<input value={config.auth_ref ?? ""} onChange={(event) => update("auth_ref", event.target.value.trim() || null)} placeholder="可选，例如 project-agent-key" /></label><label className="field-label">协议版本<input value={config.protocol_version} onChange={(event) => update("protocol_version", event.target.value)} /></label></div><div className="field-grid three"><label className="field-label">超时时间（秒）<input type="number" min="1" value={config.timeout_seconds} onChange={(event) => update("timeout_seconds", Number(event.target.value))} /></label><label className="field-label">最大工具调用次数<input type="number" min="0" value={config.max_tool_calls} onChange={(event) => update("max_tool_calls", Number(event.target.value))} /></label><label className="field-label">重试次数<input type="number" min="0" max="5" value={config.max_retries} onChange={(event) => update("max_retries", Number(event.target.value))} /></label></div></div>;
}
