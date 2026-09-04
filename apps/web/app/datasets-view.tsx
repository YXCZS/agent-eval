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
    if (!fileText) { setNotice({ tone: "danger", text: "Choose a CSV, JSON, or JSONL file first." }); return; }
    if (!name.trim()) { setNotice({ tone: "danger", text: "Dataset name is required before previewing an import." }); return; }
    setBusy(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ name: name.trim(), description, cases: [] }) });
      const created = await response.json() as { id?: string; detail?: string };
      if (!response.ok || !created.id) throw new Error(created.detail ?? `Could not create dataset (${response.status})`);
      setDatasetId(created.id);
      const previewResponse = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets/${created.id}/imports/preview`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ format, content_base64: encodeBase64(fileText), field_mapping: mappedFields }) });
      const result = await previewResponse.json() as Preview & { detail?: string };
      if (!previewResponse.ok) throw new Error(typeof result.detail === "string" ? result.detail : `Preview failed (${previewResponse.status})`);
      setPreview(result); setNotice({ tone: result.issues.length ? "neutral" : "success", text: `${result.cases.length} valid cases are ready for review.` });
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Import preview failed." }); }
    finally { setBusy(false); }
  }

  async function commitImport() {
    if (!datasetId || !preview) return;
    setBusy(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets/${datasetId}/imports/commit`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ format, content_base64: encodeBase64(fileText), field_mapping: mappedFields, allow_partial: preview.issues.length > 0 }) });
      const result = await response.json() as { dataset_version?: { version: number }; issues?: ImportIssue[]; detail?: unknown };
      if (!response.ok || !result.dataset_version) throw new Error(typeof result.detail === "string" ? result.detail : "Import could not be committed.");
      setNotice({ tone: "success", text: `Dataset imported as version ${result.dataset_version.version}.` });
      setPreview(null); setFile(null); setFileText("");
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Import commit failed." }); }
    finally { setBusy(false); }
  }

  async function createManual() {
    if (!name.trim()) { setNotice({ tone: "danger", text: "Dataset name is required." }); return; }
    const invalid = cases.some((row) => !row.input.trim());
    if (invalid) { setNotice({ tone: "danger", text: "Every case needs an input." }); return; }
    setBusy(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/projects/${PROJECT_ID}/datasets`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ name: name.trim(), description, cases: cases.map(caseFromManual) }) });
      const result = await response.json() as { id?: string; detail?: string };
      if (!response.ok) throw new Error(result.detail ?? `Dataset creation failed (${response.status})`);
      setNotice({ tone: "success", text: `Dataset created with ${cases.length} case${cases.length === 1 ? "" : "s"}.` });
      setCases([emptyCase()]);
    } catch (error) { setNotice({ tone: "danger", text: error instanceof Error ? error.message : "Dataset creation failed." }); }
    finally { setBusy(false); }
  }

  return <section className="datasets-workbench">
    <div className="resource-heading dataset-heading"><div><p className="eyebrow"><Database size={14} /> Evaluation inputs</p><h1>Datasets</h1><p>Build a versioned set of cases once, then reuse it across agents, evaluators and regression runs.</p></div><button className="primary" onClick={() => { setMode("manual"); setName(""); setDescription(""); setNotice(null); }}><Plus size={17} /> New dataset</button></div>
    <section className="dataset-builder panel">
      <div className="builder-top"><div><span className="section-kicker">New dataset</span><strong>{mode === "manual" ? "Add evaluation cases" : "Import evaluation cases"}</strong></div><span className="version-badge">Creates version 1</span></div>
      <div className="builder-body">
        <div className="field-grid two dataset-meta"><label className="field-label">Dataset name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. support-smoke" /></label><label className="field-label">Description<input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What this dataset checks" /></label></div>
        <div className="mode-tabs" role="tablist"><button className={mode === "manual" ? "active" : ""} onClick={() => { setMode("manual"); setNotice(null); }}><Table2 size={16} /> Manual table</button><button className={mode === "import" ? "active" : ""} onClick={() => { setMode("import"); setNotice(null); }}><FileUp size={16} /> Import file</button></div>
        {mode === "manual" ? <ManualEditor cases={cases} updateCase={updateCase} addCase={() => setCases((current) => [...current, emptyCase()])} removeCase={(index) => setCases((current) => current.length === 1 ? current : current.filter((_, rowIndex) => rowIndex !== index))} /> : <ImportEditor file={file} format={format} fields={fields} mapping={mapping} setFormat={setFormat} setMapping={setMapping} onFile={handleFile} preview={preview} onPreview={previewImport} onCommit={commitImport} onReset={resetImport} busy={busy} />}
        {notice && <div className={`dataset-notice ${notice.tone}`}><span>{notice.tone === "success" ? <Check size={16} /> : notice.tone === "danger" ? <AlertTriangle size={16} /> : <RefreshCw size={16} />}</span>{notice.text}</div>}
        {mode === "manual" && <div className="builder-actions"><span className="muted-helper">Cases are stored as a new immutable dataset version.</span><button className="primary" onClick={createManual} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Database size={16} />} Create dataset</button></div>}
      </div>
    </section>
  </section>;
}

function ManualEditor({ cases, updateCase, addCase, removeCase }: { cases: ManualCase[]; updateCase: (index: number, field: keyof ManualCase, value: string) => void; addCase: () => void; removeCase: (index: number) => void }) {
  return <div className="manual-editor"><div className="table-toolbar"><div><strong>{cases.length} case{cases.length === 1 ? "" : "s"}</strong><span>Input and optional expected output</span></div><button className="outline-button compact" onClick={addCase}><ListPlus size={15} /> Add row</button></div><div className="case-table-wrap"><table className="case-table"><thead><tr><th>ID</th><th>Input</th><th>Expected output <em>optional</em></th><th>Metadata <em>JSON</em></th><th aria-label="Actions" /></tr></thead><tbody>{cases.map((row, index) => <tr key={row.id}><td><input value={row.id} onChange={(event) => updateCase(index, "id", event.target.value)} /></td><td><textarea value={row.input} onChange={(event) => updateCase(index, "input", event.target.value)} placeholder="Question, message, or JSON input" rows={2} /></td><td><textarea value={row.expected_output} onChange={(event) => updateCase(index, "expected_output", event.target.value)} placeholder="Reference answer or object" rows={2} /></td><td><textarea value={row.metadata} onChange={(event) => updateCase(index, "metadata", event.target.value)} rows={2} /></td><td><button className="icon-button" title="Remove case" aria-label="Remove case" onClick={() => removeCase(index)}><Trash2 size={15} /></button></td></tr>)}</tbody></table></div></div>;
}

function ImportEditor({ file, format, fields, mapping, setFormat, setMapping, onFile, preview, onPreview, onCommit, onReset, busy }: { file: File | null; format: ImportFormat; fields: string[]; mapping: Record<CanonicalField, string>; setFormat: (value: ImportFormat) => void; setMapping: (value: Record<CanonicalField, string>) => void; onFile: (event: ChangeEvent<HTMLInputElement>) => void; preview: Preview | null; onPreview: () => void; onCommit: () => void; onReset: () => void; busy: boolean }) {
  const canonicalFields: Array<{ key: CanonicalField; label: string; required?: boolean }> = [{ key: "id", label: "Case ID", required: true }, { key: "input", label: "Input", required: true }, { key: "expected_output", label: "Expected output" }, { key: "variables", label: "Variables" }, { key: "criteria", label: "Criteria" }, { key: "metadata", label: "Metadata" }];
  return <div className="import-editor"><div className="drop-zone"><input id="dataset-file" type="file" accept=".csv,.json,.jsonl, text/csv, application/json" onChange={onFile} /><label htmlFor="dataset-file"><Upload size={22} /><strong>{file ? file.name : "Choose a dataset file"}</strong><span>CSV, JSON array, or JSONL up to 5 MB</span></label>{file && <button className="icon-button" title="Clear selected file" aria-label="Clear selected file" onClick={onReset}><X size={16} /></button>}</div><div className="import-controls"><label className="field-label">File format<select value={format} onChange={(event) => setFormat(event.target.value as ImportFormat)}><option value="csv">CSV</option><option value="jsonl">JSONL</option><option value="json">JSON array</option></select></label><div className="format-hint"><FileJson size={16} /><span>Map source columns to the canonical case fields before preview.</span></div></div>{fields.length > 0 && <div className="mapping-grid"><div className="mapping-heading"><div><span className="section-kicker">Field mapping</span><strong>Tell us what each column means</strong></div><span>{fields.length} source fields detected</span></div>{canonicalFields.map(({ key, label, required }) => <label className="mapping-row" key={key}><span>{label}{required && <b>*</b>}</span><select value={mapping[key]} onChange={(event) => setMapping({ ...mapping, [key]: event.target.value })}><option value="">Not mapped</option>{fields.map((field) => <option key={field} value={field}>{field}</option>)}</select></label>)}<button className="outline-button" onClick={onPreview} disabled={busy || !file}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} Preview import</button></div>}{preview && <ImportPreview preview={preview} onCommit={onCommit} busy={busy} />}</div>;
}

function ImportPreview({ preview, onCommit, busy }: { preview: Preview; onCommit: () => void; busy: boolean }) {
  return <div className="import-preview"><div className="preview-summary"><div><span className="section-kicker">Validation preview</span><strong>{preview.cases.length} valid cases</strong></div><span className={preview.issues.length ? "issue-count" : "valid-count"}>{preview.issues.length ? `${preview.issues.length} issue${preview.issues.length === 1 ? "" : "s"}` : "No issues"}</span></div>{preview.cases.length > 0 && <div className="preview-cases">{preview.cases.slice(0, 5).map((item) => <div className="preview-case" key={item.id}><span className="valid-mark"><Check size={13} /></span><div><strong>{item.id}</strong><span>{textValue(item.input).slice(0, 110)}</span></div></div>)}{preview.cases.length > 5 && <small>Showing first 5 cases</small>}</div>}{preview.issues.length > 0 && <div className="issue-list"><strong><AlertTriangle size={14} /> Rows needing attention</strong>{preview.issues.slice(0, 8).map((issue) => <div key={`${issue.line}-${issue.reason}`}><b>Line {issue.line}</b><span>{issue.reason}</span></div>)}</div>}<div className="preview-actions"><span>{preview.issues.length ? "Valid rows can be imported; invalid rows will be skipped." : "Nothing is created until you confirm."}</span><button className="primary" onClick={onCommit} disabled={busy || preview.cases.length === 0}>{busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Confirm import</button></div></div>;
}
