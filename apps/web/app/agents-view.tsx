"use client";

import { useMemo, useState } from "react";
import { Bot, Check, CircleAlert, Clock3, CopyPlus, ExternalLink, Globe2, Play, Plus, Save, Server, SlidersHorizontal, Sparkles, TestTube2, XCircle } from "lucide-react";

type AgentType = "prompt" | "rag" | "tool" | "custom";
type ConnectionState = { tone: "success" | "danger"; message: string; detail?: string; latency?: number } | null;
type PromptConfig = { provider: string; model: string; endpoint: string; system_prompt: string; user_template: string; variable_names: string[]; temperature: number; top_p: number; max_tokens: number | null; response_format: Record<string, unknown> | null; timeout_seconds: number; concurrency_limit: number; max_retries: number };
type EndpointConfig = { url: string; method: "POST"; auth_ref: string; protocol_version: string; timeout_seconds: number; max_response_bytes: number; max_tool_calls: number; concurrency_limit: number; max_retries: number };
type AgentVersion = { version: number; label: string; enabled: boolean; prompt_config?: PromptConfig; endpoint_config?: EndpointConfig };
type Agent = { id: string; name: string; type: AgentType; description: string; active: boolean; versions: AgentVersion[] };

const promptConfig: PromptConfig = { provider: "OpenAI-compatible", model: "gpt-4o-mini", endpoint: "https://api.openai.com/v1/chat/completions", system_prompt: "You are a precise support assistant.", user_template: "Answer the customer question:\n\n{{question}}", variable_names: ["question"], temperature: 0.2, top_p: 1, max_tokens: 600, response_format: null, timeout_seconds: 60, concurrency_limit: 4, max_retries: 2 };
const endpointConfig: EndpointConfig = { url: "http://localhost:8080/run", method: "POST", auth_ref: "", protocol_version: "v1", timeout_seconds: 30, max_response_bytes: 1048576, max_tool_calls: 32, concurrency_limit: 4, max_retries: 2 };
const initialAgents: Agent[] = [
  { id: "agent-order", name: "Order support", type: "tool", description: "Checks order status and handles cancellation policy.", active: true, versions: [{ version: 3, label: "Order support v3", enabled: true, endpoint_config: { ...endpointConfig, url: "https://order-agent.example.com/run" } }, { version: 2, label: "Order support v2", enabled: false, endpoint_config: { ...endpointConfig, url: "https://order-agent.example.com/run" } }] },
  { id: "agent-rag", name: "Knowledge RAG", type: "rag", description: "Answers help-center questions with retrieved context.", active: true, versions: [{ version: 4, label: "Knowledge RAG v4", enabled: true, endpoint_config: { ...endpointConfig, url: "https://knowledge-agent.example.com/run" } }] },
  { id: "agent-prompt", name: "Support prompt", type: "prompt", description: "A direct prompt runner for support answer quality.", active: true, versions: [{ version: 7, label: "Support prompt v7", enabled: true, prompt_config: { ...promptConfig } }] },
];
const typeLabels: Record<AgentType, string> = { prompt: "Prompt", rag: "RAG", tool: "Tool", custom: "Custom" };

function freshVersion(type: AgentType, version = 1): AgentVersion {
  return type === "prompt" ? { version, label: `New prompt v${version}`, enabled: true, prompt_config: { ...promptConfig } } : { version, label: `New ${type} v${version}`, enabled: true, endpoint_config: { ...endpointConfig } };
}
function renderTemplate(template: string, variables: Record<string, unknown>) {
  return template.replace(/\{\{?([A-Za-z_][A-Za-z0-9_]*)\}?\}/g, (_, name: string) => { const value = variables[name]; return value === undefined ? `{{${name}}}` : typeof value === "string" ? value : JSON.stringify(value); });
}
function parseVariables(source: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(source);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Variables must be a JSON object");
  return parsed as Record<string, unknown>;
}

export function AgentsView() {
  const [agents, setAgents] = useState(initialAgents);
  const [selectedId, setSelectedId] = useState(initialAgents[2].id);
  const [draft, setDraft] = useState<Agent>({ ...initialAgents[2], versions: [{ ...initialAgents[2].versions[0], prompt_config: { ...promptConfig } }] });
  const [selectedVersion, setSelectedVersion] = useState(7);
  const [isNew, setIsNew] = useState(false);
  const [variablesText, setVariablesText] = useState('{\n  "question": "Can I cancel an order after it ships?"\n}');
  const [schemaText, setSchemaText] = useState("");
  const [connection, setConnection] = useState<ConnectionState>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const currentVersion = draft.versions.find((version) => version.version === selectedVersion) ?? draft.versions[0];
  const currentPrompt = currentVersion?.prompt_config;
  const currentEndpoint = currentVersion?.endpoint_config;
  const preview = useMemo(() => { if (!currentPrompt) return "HTTP agents receive the sample input below through the /run protocol."; try { return renderTemplate(currentPrompt.user_template, parseVariables(variablesText)); } catch { return "Enter a JSON object to render the prompt preview."; } }, [currentPrompt, variablesText]);

  function selectAgent(agent: Agent) {
    const version = agent.versions[0]; setSelectedId(agent.id); setDraft({ ...agent }); setSelectedVersion(version.version); setIsNew(false); setConnection(null); setNotice(null); setSchemaText(version.prompt_config?.response_format ? JSON.stringify(version.prompt_config.response_format, null, 2) : "");
  }
  function startNew() {
    const type: AgentType = "prompt"; setSelectedId(""); setDraft({ id: "", name: "", type, description: "", active: true, versions: [freshVersion(type)] }); setSelectedVersion(1); setIsNew(true); setConnection(null); setNotice(null); setSchemaText("");
  }
  function changeType(type: AgentType) { setDraft((current) => ({ ...current, type, versions: [freshVersion(type, currentVersion?.version ?? 1)] })); setSelectedVersion(currentVersion?.version ?? 1); setConnection(null); }
  function updatePrompt(field: keyof PromptConfig, value: string | number | null) { setDraft((current) => ({ ...current, versions: current.versions.map((version) => version.version === selectedVersion ? { ...version, prompt_config: { ...version.prompt_config!, [field]: value } } : version) })); }
  function updateEndpoint(field: keyof EndpointConfig, value: string | number) { setDraft((current) => ({ ...current, versions: current.versions.map((version) => version.version === selectedVersion ? { ...version, endpoint_config: { ...version.endpoint_config!, [field]: value } } : version) })); }
  function saveVersion() {
    if (!draft.name.trim()) { setNotice("Agent name is required."); return; }
    if (draft.type === "prompt" && !currentPrompt?.user_template.trim()) { setNotice("User template is required."); return; }
    if (draft.type !== "prompt") { try { new URL(currentEndpoint?.url ?? ""); } catch { setNotice("Enter a valid HTTP endpoint URL."); return; } }
    if (isNew) { const newAgent = { ...draft, id: `agent-local-${Date.now()}`, name: draft.name.trim(), versions: draft.versions }; setAgents((current) => [newAgent, ...current]); setSelectedId(newAgent.id); setDraft(newAgent); setIsNew(false); setNotice("Agent created in this workspace."); }
    else { setAgents((current) => current.map((agent) => agent.id === draft.id ? draft : agent)); setNotice(`Draft ${currentVersion?.label ?? "version"} saved locally. New versions remain immutable after API persistence.`); }
    setConnection(null);
  }
  function saveAsVersion() {
    const next = Math.max(...draft.versions.map((version) => version.version), 0) + 1;
    const copied = currentVersion ? { ...currentVersion, version: next, label: `${draft.name || "Agent"} v${next}`, prompt_config: currentPrompt ? { ...currentPrompt } : undefined, endpoint_config: currentEndpoint ? { ...currentEndpoint } : undefined } : freshVersion(draft.type, next);
    setDraft((current) => ({ ...current, versions: [copied, ...current.versions] })); setSelectedVersion(next); setNotice(`Created draft version ${next}. Save it when the configuration is ready.`); setConnection(null);
  }
  async function testConnection() {
    setConnection(null); setNotice(null); let variables: Record<string, unknown> = {};
    try { variables = parseVariables(variablesText); } catch (error) { setConnection({ tone: "danger", message: "Variables are not valid JSON.", detail: error instanceof Error ? error.message : "Fix the sample variables first." }); return; }
    let responseFormat: Record<string, unknown> | null = null;
    try { responseFormat = schemaText.trim() ? JSON.parse(schemaText) as Record<string, unknown> : null; } catch { setConnection({ tone: "danger", message: "Response schema is not valid JSON.", detail: "Fix the schema before testing." }); return; }
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"; const projectId = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1"; const session = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";
    const body = draft.type === "prompt" ? { agent_type: draft.type, prompt_config: { ...currentPrompt, response_format: responseFormat }, input: variables, variables, messages: [] } : { agent_type: draft.type, endpoint_config: currentEndpoint, input: variables, variables, messages: [] };
    const started = performance.now();
    try {
      const response = await fetch(`${apiBase}/projects/${projectId}/agents/connection-test`, { method: "POST", headers: { "Content-Type": "application/json", "X-Workspace-Session": session }, body: JSON.stringify(body) });
      const result = await response.json() as { success?: boolean; message?: string; error_type?: string; latency_ms?: number; output?: unknown; rendered_prompt?: string; detail?: unknown };
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `API returned HTTP ${response.status}`);
      if (!result.success) { setConnection({ tone: "danger", message: result.message ?? "Connection test failed.", detail: result.error_type, latency: result.latency_ms }); return; }
      setConnection({ tone: "success", message: result.message ?? "Connection succeeded.", detail: result.output ? `Output: ${JSON.stringify(result.output).slice(0, 180)}` : result.rendered_prompt ? "Prompt rendered successfully." : "The endpoint accepted the request.", latency: result.latency_ms ?? performance.now() - started });
    } catch (error) { setConnection({ tone: "danger", message: "Connection test could not reach the API.", detail: error instanceof Error ? error.message : "Check NEXT_PUBLIC_API_URL and the API service." }); }
  }

  return <section className="agents-workbench">
    <div className="resource-heading agent-heading"><div><p className="eyebrow"><Bot size={14} /> Execution targets</p><h1>Agents</h1><p>Configure the runner that evaluation cases will call. Every saved configuration becomes a selectable version.</p></div><button className="primary" onClick={startNew}><Plus size={17} /> New agent</button></div>
    <div className="agents-layout">
      <aside className="agent-catalog panel"><div className="catalog-heading"><div><span className="section-kicker">Workspace agents</span><strong>{agents.length} registered</strong></div><SlidersHorizontal size={16} /></div><div className="agent-list">{agents.map((agent) => <button key={agent.id} className={`agent-list-item ${agent.id === selectedId ? "selected" : ""}`} onClick={() => selectAgent(agent)}><span className={`agent-list-icon type-${agent.type}`}>{agent.type === "prompt" ? <Sparkles size={16} /> : agent.type === "rag" ? <Server size={16} /> : <Bot size={16} />}</span><span className="agent-list-copy"><strong>{agent.name}</strong><span>{typeLabels[agent.type]} · v{Math.max(...agent.versions.map((version) => version.version))}</span></span><span className={`live-dot ${agent.active ? "on" : ""}`} /></button>)}</div><button className="catalog-add" onClick={startNew}><CopyPlus size={15} /> Register another agent</button></aside>
      <div className="agent-editor panel"><div className="editor-header"><div><span className="section-kicker">{isNew ? "New registration" : "Configuration editor"}</span><strong>{isNew ? "Connect an agent" : draft.name}</strong></div><span className={`state-chip ${draft.active ? "active" : ""}`}>{draft.active ? "Active" : "Paused"}</span></div><div className="editor-scroll"><label className="field-label">Agent name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="e.g. Billing assistant" /></label><label className="field-label">Description<textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={2} placeholder="What this agent is responsible for" /></label><div className="field-label"><span>Execution type</span><div className="type-switch">{(Object.keys(typeLabels) as AgentType[]).map((type) => <button key={type} className={draft.type === type ? "chosen" : ""} disabled={!isNew} onClick={() => changeType(type)}>{typeLabels[type]}</button>)}</div>{!isNew && <small>Agent type is fixed after registration.</small>}</div><div className="version-line"><label className="field-label">Version<select value={selectedVersion} onChange={(event) => { const value = Number(event.target.value); setSelectedVersion(value); const version = draft.versions.find((item) => item.version === value); setSchemaText(version?.prompt_config?.response_format ? JSON.stringify(version.prompt_config.response_format, null, 2) : ""); setConnection(null); }}>{draft.versions.map((version) => <option key={version.version} value={version.version}>{version.label}{version.enabled ? " · enabled" : " · disabled"}</option>)}</select></label><button className="outline-button compact" onClick={saveAsVersion}><CopyPlus size={15} /> New version</button></div>{draft.type === "prompt" && currentPrompt ? <PromptFields config={currentPrompt} update={updatePrompt} /> : currentEndpoint ? <EndpointFields config={currentEndpoint} update={updateEndpoint} type={draft.type} /> : null}<div className="editor-actions"><button className="outline-button" onClick={testConnection}><TestTube2 size={16} /> Test connection</button><button className="primary" onClick={saveVersion}><Save size={16} /> {isNew ? "Create agent" : "Save draft"}</button></div>{notice && <div className="inline-notice"><CircleAlert size={16} />{notice}</div>}</div></div>
      <div className="agent-side-stack"><section className="preview-panel panel"><div className="panel-heading"><div><p className="eyebrow">Live preview</p><h2>{draft.type === "prompt" ? "Rendered prompt" : "Request sample"}</h2></div><ExternalLink size={16} className="muted-icon" /></div>{draft.type === "prompt" ? <><pre className="prompt-preview">{preview}</pre><div className="sample-box"><span>Sample variables</span><textarea value={variablesText} onChange={(event) => setVariablesText(event.target.value)} rows={5} /></div></> : <div className="http-preview"><div><Globe2 size={18} /><strong>POST {currentEndpoint?.url || "endpoint not set"}</strong></div><pre>{JSON.stringify({ input: { question: "Can I cancel an order?" }, variables: { question: "Can I cancel an order?" }, metadata: { case_id: "connection-test" }, trace_id: "generated-at-run-time" }, null, 2)}</pre></div>}</section><section className="test-panel panel"><div className="panel-heading"><div><p className="eyebrow">Connection check</p><h2>One sample request</h2></div><Clock3 size={16} className="muted-icon" /></div>{connection ? <div className={`connection-result ${connection.tone}`}><div className="connection-title">{connection.tone === "success" ? <Check size={18} /> : <XCircle size={18} />}<strong>{connection.message}</strong></div>{connection.latency !== undefined && <span>{Math.round(connection.latency)} ms</span>}<small>{connection.detail}</small></div> : <div className="test-empty"><Play size={17} /><span>Run a bounded request to verify the current configuration.</span></div>}</section></div>
    </div>
    {draft.type === "prompt" && currentPrompt && <section className="advanced-panel panel"><div className="panel-heading"><div><p className="eyebrow">Structured output</p><h2>Response schema</h2></div><span className="optional-label">Optional JSON Schema</span></div><textarea className="schema-editor" value={schemaText} onChange={(event) => setSchemaText(event.target.value)} placeholder={'{\n  "type": "object",\n  "properties": { "answer": { "type": "string" } }\n}'} rows={7} /></section>}
  </section>;
}

function PromptFields({ config, update }: { config: PromptConfig; update: (field: keyof PromptConfig, value: string | number | null) => void }) {
  return <div className="config-section"><div className="config-section-title"><Sparkles size={15} /><strong>Prompt runner</strong><span>OpenAI-compatible</span></div><div className="field-grid two"><label className="field-label">Provider<input value={config.provider} onChange={(event) => update("provider", event.target.value)} /></label><label className="field-label">Model<input value={config.model} onChange={(event) => update("model", event.target.value)} /></label></div><label className="field-label">Endpoint<input value={config.endpoint} onChange={(event) => update("endpoint", event.target.value)} /></label><label className="field-label">System prompt<textarea value={config.system_prompt} onChange={(event) => update("system_prompt", event.target.value)} rows={3} /></label><label className="field-label">User template<textarea value={config.user_template} onChange={(event) => update("user_template", event.target.value)} rows={4} /><small>Use named variables such as {"{{question}}"}.</small></label><div className="field-grid three"><label className="field-label">Temperature<input type="number" min="0" max="2" step="0.1" value={config.temperature} onChange={(event) => update("temperature", Number(event.target.value))} /></label><label className="field-label">Top p<input type="number" min="0.01" max="1" step="0.05" value={config.top_p} onChange={(event) => update("top_p", Number(event.target.value))} /></label><label className="field-label">Max tokens<input type="number" min="1" value={config.max_tokens ?? ""} onChange={(event) => update("max_tokens", event.target.value ? Number(event.target.value) : null)} /></label></div></div>;
}

function EndpointFields({ config, update, type }: { config: EndpointConfig; update: (field: keyof EndpointConfig, value: string | number) => void; type: AgentType }) {
  return <div className="config-section"><div className="config-section-title"><Globe2 size={15} /><strong>HTTP adapter</strong><span>{typeLabels[type]} /run protocol</span></div><label className="field-label">Agent endpoint<input value={config.url} onChange={(event) => update("url", event.target.value)} placeholder="https://your-agent.example.com/run" /></label><div className="field-grid two"><label className="field-label">Auth reference<input value={config.auth_ref} onChange={(event) => update("auth_ref", event.target.value)} placeholder="project-agent-key" /></label><label className="field-label">Protocol version<input value={config.protocol_version} onChange={(event) => update("protocol_version", event.target.value)} /></label></div><div className="field-grid three"><label className="field-label">Timeout (s)<input type="number" min="1" value={config.timeout_seconds} onChange={(event) => update("timeout_seconds", Number(event.target.value))} /></label><label className="field-label">Max tool calls<input type="number" min="0" value={config.max_tool_calls} onChange={(event) => update("max_tool_calls", Number(event.target.value))} /></label><label className="field-label">Retries<input type="number" min="0" max="5" value={config.max_retries} onChange={(event) => update("max_retries", Number(event.target.value))} /></label></div></div>;
}
