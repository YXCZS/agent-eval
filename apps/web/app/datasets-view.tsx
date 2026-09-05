"use client";

import { ChangeEvent, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Database,
  FileJson,
  FileUp,
  ListPlus,
  LoaderCircle,
  Plus,
  RefreshCw,
  Table2,
  Trash2,
  Upload,
  X,
} from "lucide-react";

type JsonValue = unknown;
type Mode = "manual" | "import";
type ImportFormat = "csv" | "json" | "jsonl";
type CanonicalField = "id" | "input" | "expected_output" | "variables" | "criteria" | "metadata";
type ManualCase = { id: string; input: string; expected_output: string; metadata: string };
type PreviewCase = { id: string; input: JsonValue; expected_output?: JsonValue; metadata?: Record<string, unknown> };
type ImportIssue = { line: number; reason: string };
type Preview = { cases: PreviewCase[]; issues: ImportIssue[] };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PROJECT_ID = process.env.NEXT_PUBLIC_PROJECT_ID ?? "project-1";
const SESSION = process.env.NEXT_PUBLIC_WORKSPACE_SESSION ?? "";

const emptyCase = (): ManualCase => ({ id: `case-${Date.now()}`, input: "", expected_output: "", metadata: "{}" });

function authHeaders(json = true): HeadersInit {
  return { ...(json ? { "Content-Type": "application/json" } : {}), "X-Workspace-Session": SESSION };
}

function parseJsonField(value: string, fallback: JsonValue = undefined): JsonValue {
  if (!value.trim()) return fallback;
  try { return JSON.parse(value); } catch { return value; }
}

function textValue(value: JsonValue): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return "";
  return JSON.stringify(value);
}

function encodeBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary);
}

function guessFormat(fileName: string): ImportFormat {
  const extension = fileName.toLowerCase().split(".").pop();
  return extension === "csv" ? "csv" : extension === "json" ? "json" : "jsonl";
}

function sourceFields(text: string, format: ImportFormat): string[] {
  try {
    if (format === "csv") return (text.split(/\r?\n/, 1)[0] ?? "").split(",").map((field) => field.trim()).filter(Boolean);
    const first = format === "json" ? JSON.parse(text)[0] : JSON.parse(text.split(/\r?\n/).find(Boolean) ?? "{}");
    return first && typeof first === "object" && !Array.isArray(first) ? Object.keys(first) : [];
  } catch { return []; }
}

function caseFromManual(row: ManualCase, index: number): Record<string, JsonValue> {
  return {
    id: row.id.trim() || `case-${index + 1}`,
    input: parseJsonField(row.input, ""),
    expected_output: parseJsonField(row.expected_output),
    metadata: parseJsonField(row.metadata, {}),
  };
}

export function DatasetsView() {
  const [mode, setMode] = useState<Mode>("manual");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cases, setCases] = useState<ManualCase[]>([emptyCase()]);
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<ImportFormat>("jsonl");
  const [fileText, setFileText] = useState("");
  const [fields, setFields] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<CanonicalField, string>>({ id: "", input: "", expected_output: "", variables: "", criteria: "", metadata: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "danger" | "neutral"; text: string } | null>(null);

  const mappedFields = useMemo(() => Object.fromEntries(Object.entries(mapping).filter(([, value]) => value)), [mapping]);

  function resetImport() {
    setFile(null); setFileText(""); setFields([]); setPreview(null); setDatasetId(null);
    setMapping({ id: "", input: "", expected_output: "", variables: "", criteria: "", metadata: "" });
  }

  function updateCase(index: number, field: keyof ManualCase, value: string) {
    setCases((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row));
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    if (!selected) return;
    const nextFormat = guessFormat(selected.name);
    setFile(selected); setFormat(nextFormat); setPreview(null); setNotice(null);
    const text = await selected.text();
    setFileText(text);
    const nextFields = sourceFields(text, nextFormat);
    setFields(nextFields);
    setMapping((current) => ({ ...current, id: nextFields.find((field) => ["id", "case_id", "case_key"].includes(field)) ?? "", input: nextFields.find((field) => ["input", "question", "prompt"].includes(field)) ?? "", expected_output: nextFields.find((field) => ["expected_output", "expected", "answer"].includes(field)) ?? "" }));
  }

  async function previewImport() {
    if (!fileText) { setNotice({ tone: "danger", text: "请先选择 CSV、JSON 或 JSONL 文件。" }); return; }
    if (!name.trim()) { setNotice({ tone: "danger", text: "预览导入前必须填写数据集名称。" }); return; }
    setBusy(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ name: name.trim(), description, cases: [] }) });
      const created = await response.json() as { id?: string; detail?: string };
      if (!response.ok || !created.id) throw new Error(created.detail ?? `无法创建数据集（${response.status}）`);
      setDatasetId(created.id);
      const previewResponse = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets/${created.id}/imports/preview`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ format, content_base64: encodeBase64(fileText), field_mapping: mappedFields }) });
      const result = await previewResponse.json() as Preview & { detail?: string };
      if (!previewResponse.ok) throw new Error(typeof result.detail === "string" ? result.detail : `预览失败（${previewResponse.status}）`);
      setPreview(result); setNotice({ tone: result.issues.length ? "neutral" : "success", text: `已有 ${result.cases.length} 个有效用例可供检查。` });
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "导入预览失败。" }); }
    finally { setBusy(false); }
  }

  async function commitImport() {
    if (!datasetId || !preview) return;
    setBusy(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets/${datasetId}/imports/commit`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ format, content_base64: encodeBase64(fileText), field_mapping: mappedFields, allow_partial: preview.issues.length > 0 }) });
      const result = await response.json() as { dataset_version?: { version: number }; issues?: ImportIssue[]; detail?: unknown };
      if (!response.ok || !result.dataset_version) throw new Error(typeof result.detail === "string" ? result.detail : "无法提交导入。");
      setNotice({ tone: "success", text: `数据集已导入为版本 ${result.dataset_version.version}。` });
      setPreview(null); setFile(null); setFileText("");
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "导入提交失败。" }); }
    finally { setBusy(false); }
  }

  async function createManual() {
    if (!name.trim()) { setNotice({ tone: "danger", text: "必须填写数据集名称。" }); return; }
    const invalid = cases.some((row) => !row.input.trim());
    if (invalid) { setNotice({ tone: "danger", text: "每个用例都必须填写输入。" }); return; }
    setBusy(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ name: name.trim(), description, cases: cases.map(caseFromManual) }) });
      const result = await response.json() as { id?: string; detail?: string };
      if (!response.ok) throw new Error(result.detail ?? `数据集创建失败（${response.status}）`);
      setNotice({ tone: "success", text: `数据集已创建，包含 ${cases.length} 个用例。` });
      setCases([emptyCase()]);
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "数据集创建失败。" }); }
    finally { setBusy(false); }
  }

  return <section className="datasets-workbench">
    <div className="resource-heading dataset-heading"><div><p className="eyebrow"><Database size={14} /> 评测输入</p><h1>数据集</h1><p>一次构建带版本的数据集，即可在 Agent、评估器和回归运行中重复使用。</p></div><button className="primary" onClick={() => { setMode("manual"); setName(""); setDescription(""); setNotice(null); }}><Plus size={17} /> 新建数据集</button></div>
    <section className="dataset-builder panel">
      <div className="builder-top"><div><span className="section-kicker">新建数据集</span><strong>{mode === "manual" ? "添加评估用例" : "导入评估用例"}</strong></div><span className="version-badge">创建版本 1</span></div>
      <div className="builder-body">
        <div className="field-grid two dataset-meta"><label className="field-label">数据集名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：support-smoke" /></label><label className="field-label">描述<input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="说明此数据集检查的内容" /></label></div>
        <div className="mode-tabs" role="tablist"><button className={mode === "manual" ? "active" : ""} onClick={() => { setMode("manual"); setNotice(null); }}><Table2 size={16} /> 手动填写</button><button className={mode === "import" ? "active" : ""} onClick={() => { setMode("import"); setNotice(null); }}><FileUp size={16} /> 导入文件</button></div>
        {mode === "manual" ? <ManualEditor cases={cases} updateCase={updateCase} addCase={() => setCases((current) => [...current, emptyCase()])} removeCase={(index) => setCases((current) => current.length === 1 ? current : current.filter((_, rowIndex) => rowIndex !== index))} /> : <ImportEditor file={file} format={format} fields={fields} mapping={mapping} setFormat={setFormat} setMapping={setMapping} onFile={handleFile} preview={preview} onPreview={previewImport} onCommit={commitImport} onReset={resetImport} busy={busy} />}
        {notice && <div className={`dataset-notice ${notice.tone}`}><span>{notice.tone === "success" ? <Check size={16} /> : notice.tone === "danger" ? <AlertTriangle size={16} /> : <RefreshCw size={16} />}</span>{notice.text}</div>}
        {mode === "manual" && <div className="builder-actions"><span className="muted-helper">用例将作为新的不可变数据集版本保存。</span><button className="primary" onClick={createManual} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Database size={16} />} 创建数据集</button></div>}
      </div>
    </section>
  </section>;
}

function ManualEditor({ cases, updateCase, addCase, removeCase }: { cases: ManualCase[]; updateCase: (index: number, field: keyof ManualCase, value: string) => void; addCase: () => void; removeCase: (index: number) => void }) {
  return <div className="manual-editor"><div className="table-toolbar"><div><strong>{cases.length} 个用例</strong><span>输入及可选的预期输出</span></div><button className="outline-button compact" onClick={addCase}><ListPlus size={15} /> 添加行</button></div><div className="case-table-wrap"><table className="case-table"><thead><tr><th>ID</th><th>输入</th><th>预期输出 <em>可选</em></th><th>元数据 <em>JSON</em></th><th aria-label="操作" /></tr></thead><tbody>{cases.map((row, index) => <tr key={row.id}><td><input value={row.id} onChange={(event) => updateCase(index, "id", event.target.value)} /></td><td><textarea value={row.input} onChange={(event) => updateCase(index, "input", event.target.value)} placeholder="问题、消息或 JSON 输入" rows={2} /></td><td><textarea value={row.expected_output} onChange={(event) => updateCase(index, "expected_output", event.target.value)} placeholder="参考答案或对象" rows={2} /></td><td><textarea value={row.metadata} onChange={(event) => updateCase(index, "metadata", event.target.value)} rows={2} /></td><td><button className="icon-button" title="移除用例" aria-label="移除用例" onClick={() => removeCase(index)}><Trash2 size={15} /></button></td></tr>)}</tbody></table></div></div>;
}

function ImportEditor({ file, format, fields, mapping, setFormat, setMapping, onFile, preview, onPreview, onCommit, onReset, busy }: { file: File | null; format: ImportFormat; fields: string[]; mapping: Record<CanonicalField, string>; setFormat: (value: ImportFormat) => void; setMapping: (value: Record<CanonicalField, string>) => void; onFile: (event: ChangeEvent<HTMLInputElement>) => void; preview: Preview | null; onPreview: () => void; onCommit: () => void; onReset: () => void; busy: boolean }) {
  const canonicalFields: Array<{ key: CanonicalField; label: string; required?: boolean }> = [{ key: "id", label: "用例 ID", required: true }, { key: "input", label: "输入", required: true }, { key: "expected_output", label: "预期输出" }, { key: "variables", label: "变量" }, { key: "criteria", label: "标准" }, { key: "metadata", label: "元数据" }];
  return <div className="import-editor"><div className="drop-zone"><input id="dataset-file" type="file" accept=".csv,.json,.jsonl, text/csv, application/json" onChange={onFile} /><label htmlFor="dataset-file"><Upload size={22} /><strong>{file ? file.name : "选择数据集文件"}</strong><span>CSV、JSON 数组或 JSONL，最大 5 MB</span></label>{file && <button className="icon-button" title="清除已选文件" aria-label="清除已选文件" onClick={onReset}><X size={16} /></button>}</div><div className="import-controls"><label className="field-label">文件格式<select value={format} onChange={(event) => setFormat(event.target.value as ImportFormat)}><option value="csv">CSV</option><option value="jsonl">JSONL</option><option value="json">JSON 数组</option></select></label><div className="format-hint"><FileJson size={16} /><span>预览前，请将源列映射到标准用例字段。</span></div></div>{fields.length > 0 && <div className="mapping-grid"><div className="mapping-heading"><div><span className="section-kicker">字段映射</span><strong>说明每一列的含义</strong></div><span>检测到 {fields.length} 个源字段</span></div>{canonicalFields.map(({ key, label, required }) => <label className="mapping-row" key={key}><span>{label}{required && <b>*</b>}</span><select value={mapping[key]} onChange={(event) => setMapping({ ...mapping, [key]: event.target.value })}><option value="">未映射</option>{fields.map((field) => <option key={field} value={field}>{field}</option>)}</select></label>)}<button className="outline-button" onClick={onPreview} disabled={busy || !file}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} 预览导入</button></div>}{preview && <ImportPreview preview={preview} onCommit={onCommit} busy={busy} />}</div>;
}

function ImportPreview({ preview, onCommit, busy }: { preview: Preview; onCommit: () => void; busy: boolean }) {
  return <div className="import-preview"><div className="preview-summary"><div><span className="section-kicker">校验预览</span><strong>{preview.cases.length} 个有效用例</strong></div><span className={preview.issues.length ? "issue-count" : "valid-count"}>{preview.issues.length ? `${preview.issues.length} 个问题` : "无问题"}</span></div>{preview.cases.length > 0 && <div className="preview-cases">{preview.cases.slice(0, 5).map((item) => <div className="preview-case" key={item.id}><span className="valid-mark"><Check size={13} /></span><div><strong>{item.id}</strong><span>{textValue(item.input).slice(0, 110)}</span></div></div>)}{preview.cases.length > 5 && <small>显示前 5 个用例</small>}</div>}{preview.issues.length > 0 && <div className="issue-list"><strong><AlertTriangle size={14} /> 需要处理的行</strong>{preview.issues.slice(0, 8).map((issue) => <div key={`${issue.line}-${issue.reason}`}><b>第 {issue.line} 行</b><span>{issue.reason}</span></div>)}</div>}<div className="preview-actions"><span>{preview.issues.length ? "有效行可以导入；无效行将被跳过。" : "确认前不会创建任何内容。"}</span><button className="primary" onClick={onCommit} disabled={busy || preview.cases.length === 0}>{busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} 确认导入</button></div></div>;
}
