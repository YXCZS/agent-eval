"use client";

import { useState } from "react";
import { AgentsView } from "./agents-view";
import { DatasetsView } from "./datasets-view";
import { EvaluatorsView } from "./evaluators-view";
import { ReportsView } from "./reports-view";
import { RunsView } from "./runs-view";
import { TracesView } from "./traces-view";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  ArrowUpRight,
  Bot,
  Boxes,
  Braces,
  Check,
  ChevronDown,
  CircleCheck,
  CircleDashed,
  Database,
  FileChartColumn,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  Layers3,
  Plus,
  Play,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Workflow,
  XCircle,
} from "lucide-react";

type ViewKey =
  | "overview"
  | "agents"
  | "datasets"
  | "evaluators"
  | "runs"
  | "reports"
  | "traces";

type NavItem = {
  key: ViewKey;
  label: string;
  icon: LucideIcon;
};

const navItems: NavItem[] = [
  { key: "overview", label: "总览", icon: Gauge },
  { key: "agents", label: "Agent 管理", icon: Bot },
  { key: "datasets", label: "数据集", icon: Database },
  { key: "evaluators", label: "评估器", icon: FlaskConical },
  { key: "runs", label: "评测运行", icon: Activity },
  { key: "reports", label: "评测报告", icon: FileChartColumn },
  { key: "traces", label: "Trace 追踪", icon: Workflow },
];

const viewMeta: Record<
  Exclude<ViewKey, "overview">,
  { title: string; eyebrow: string; description: string }
> = {
  agents: {
    title: "Agent 管理",
    eyebrow: "执行目标",
    description: "注册 Prompt Runner 和 HTTP Agent，并固定每次评测使用的版本。",
  },
  datasets: {
    title: "数据集",
    eyebrow: "评测输入",
    description: "管理用于 Prompt、RAG、Tool 和多轮 Agent 评测的版本化样本。",
  },
  evaluators: {
    title: "评估器",
    eyebrow: "评分定义",
    description: "组合确定性检查、LLM Judge 和适配器指标。",
  },
  runs: {
    title: "评测运行",
    eyebrow: "评测实验",
    description: "跟踪排队任务、样本失败情况和可复现的配置快照。",
  },
  reports: {
    title: "评测报告",
    eyebrow: "质量信号",
    description: "比较指标、定位失败样本，并导出机器可读的结果。",
  },
  traces: {
    title: "Trace 追踪",
    eyebrow: "执行证据",
    description:
      "从 Prompt 渲染开始，跟踪 Agent 的工具调用、检索过程和评分结果。",
  },
};

const recentRuns = [
  {
    id: "run_8f31",
    agent: "Order support v2",
    dataset: "orders-regression",
    score: "94.2%",
    status: "已完成",
    tone: "success",
    time: "8 分钟前",
  },
  {
    id: "run_8f2a",
    agent: "Knowledge RAG v4",
    dataset: "help-center-qa",
    score: "88.7%",
    status: "部分完成",
    tone: "warning",
    time: "41 分钟前",
  },
  {
    id: "run_8e94",
    agent: "Support prompt v7",
    dataset: "support-smoke",
    score: "97.1%",
    status: "已完成",
    tone: "success",
    time: "昨天",
  },
];

const resourceRows: Record<
  Exclude<ViewKey, "overview">,
  Array<{
    name: string;
    detail: string;
    status: string;
    tone: string;
    meta: string;
  }>
> = {
  agents: [
    {
      name: "Order support",
      detail: "Tool Agent · 3 个版本",
      status: "运行中",
      tone: "success",
      meta: "12 分钟前更新",
    },
    {
      name: "Knowledge RAG",
      detail: "RAG Agent · 4 个版本",
      status: "运行中",
      tone: "success",
      meta: "1 小时前更新",
    },
    {
      name: "Support prompt",
      detail: "Prompt Agent · 7 个版本",
      status: "草稿",
      tone: "neutral",
      meta: "昨天更新",
    },
  ],
  datasets: [
    {
      name: "orders-regression",
      detail: "Tool · 48 个样本 · v12",
      status: "就绪",
      tone: "success",
      meta: "今天编辑",
    },
    {
      name: "help-center-qa",
      detail: "RAG · 120 个样本 · v4",
      status: "就绪",
      tone: "success",
      meta: "昨天编辑",
    },
    {
      name: "support-smoke",
      detail: "Prompt · 16 个样本 · v3",
      status: "就绪",
      tone: "success",
      meta: "8 月 30 日编辑",
    },
  ],
  evaluators: [
    {
      name: "Task success",
      detail: "Deterministic · higher is better",
      status: "Enabled",
      tone: "success",
      meta: "v1.0.0",
    },
    {
      name: "Policy compliance",
      detail: "Deterministic · hard gate",
      status: "Enabled",
      tone: "success",
      meta: "v1.2.0",
    },
    {
      name: "Answer quality",
      detail: "LLM judge · 0 to 1",
      status: "Enabled",
      tone: "success",
      meta: "v2.1.0",
    },
  ],
  runs: recentRuns.map((run) => ({
    name: run.id,
    detail: `${run.agent} · ${run.dataset}`,
    status: run.status,
    tone: run.tone,
    meta: run.time,
  })),
  reports: [
    {
      name: "orders-regression / v12",
      detail: "3 metrics · 48 samples",
      status: "94.2% pass",
      tone: "success",
      meta: "Generated 8 min ago",
    },
    {
      name: "help-center-qa / v4",
      detail: "5 metrics · 120 samples",
      status: "88.7% pass",
      tone: "warning",
      meta: "Generated 41 min ago",
    },
  ],
  traces: [
    {
      name: "trace_01HZX9Q",
      detail: "Order support · Tool 调用链",
      status: "已完成",
      tone: "success",
      meta: "8 分钟前",
    },
    {
      name: "trace_01HZX7M",
      detail: "Knowledge RAG · 检索未命中",
      status: "错误",
      tone: "danger",
      meta: "41 分钟前",
    },
    {
      name: "trace_01HZWQ2",
      detail: "Support prompt · LLM 调用",
      status: "已完成",
      tone: "success",
      meta: "昨天",
    },
  ],
};

function StatusMark({ tone, label }: { tone: string; label: string }) {
  const Icon =
    tone === "danger"
      ? XCircle
      : tone === "warning"
        ? CircleDashed
        : CircleCheck;
  return (
    <span className={`status status-${tone}`}>
      <Icon size={14} />
      {label}
    </span>
  );
}

function Overview({ onNavigate }: { onNavigate: (view: ViewKey) => void }) {
  return (
    <>
      <section className="welcome-band">
        <div>
          <p className="eyebrow">
            <Sparkles size={14} /> 评测控制台
          </p>
          <h1>
            看见质量变化。
            <br />
            <span>知道问题原因。</span>
          </h1>
          <p className="lede">
            以 Trace 为核心，在质量问题进入生产前测试 Prompt、RAG 和 Tool
            Agent。
          </p>
        </div>
        <div className="welcome-mark" aria-hidden="true">
          <GitCompareArrows size={48} strokeWidth={1.2} />
          <span>v1 → v2</span>
        </div>
      </section>
      <section className="metric-grid" aria-label="Workspace summary">
        <article className="metric-tile">
          <span className="metric-label">本周运行次数</span>
          <strong>28</strong>
          <span className="metric-change positive">
            <ArrowUpRight size={14} /> 18.4%
          </span>
        </article>
        <article className="metric-tile accent-teal">
          <span className="metric-label">平均通过率</span>
          <strong>92.6%</strong>
          <span className="metric-change positive">
            <ArrowUpRight size={14} /> 3.8 个百分点
          </span>
        </article>
        <article className="metric-tile accent-coral">
          <span className="metric-label">待处理失败</span>
          <strong>17</strong>
          <span className="metric-change negative">
            <ArrowUpRight size={14} /> 新增 4 个
          </span>
        </article>
        <article className="metric-tile accent-gold">
          <span className="metric-label">已评测 Tokens</span>
          <strong>1.84M</strong>
          <span className="metric-change muted">预计 $12.48</span>
        </article>
      </section>
      <section className="content-grid">
        <article className="panel runs-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">最新实验</p>
              <h2>最近运行</h2>
            </div>
            <button className="text-button" onClick={() => onNavigate("runs")}>
              查看全部 <ArrowUpRight size={15} />
            </button>
          </div>
          <div className="run-list">
            {recentRuns.map((run) => (
              <div className="run-row" key={run.id}>
                <div className="run-icon">
                  <TerminalSquare size={17} />
                </div>
                <div className="run-main">
                  <strong>{run.agent}</strong>
                  <span>
                    {run.id} · {run.dataset}
                  </span>
                </div>
                <div className="run-score">
                  <strong>{run.score}</strong>
                  <span>{run.time}</span>
                </div>
                <StatusMark tone={run.tone} label={run.status} />
              </div>
            ))}
          </div>
        </article>
        <article className="panel signal-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">质量信号</p>
              <h2>Agent 质量概览</h2>
            </div>
            <button
              className="icon-button"
              title="打开报告"
              aria-label="打开报告"
              onClick={() => onNavigate("reports")}
            >
              <ArrowUpRight size={17} />
            </button>
          </div>
          <div className="signal-list">
            <div className="signal-row">
              <div>
                <strong>Order support</strong>
                <span>Tool correctness</span>
              </div>
              <b>96%</b>
              <div className="bar">
                <i style={{ width: "96%" }} />
              </div>
            </div>
            <div className="signal-row">
              <div>
                <strong>Knowledge RAG</strong>
                <span>Faithfulness</span>
              </div>
              <b>89%</b>
              <div className="bar">
                <i style={{ width: "89%" }} />
              </div>
            </div>
            <div className="signal-row">
              <div>
                <strong>Support prompt</strong>
                <span>Answer relevance</span>
              </div>
              <b>97%</b>
              <div className="bar">
                <i style={{ width: "97%" }} />
              </div>
            </div>
          </div>
          <div className="signal-foot">
            <ShieldCheck size={16} /> 过去 24 小时所有策略门禁均已通过
          </div>
        </article>
      </section>
      <section className="quick-start">
        <div>
          <p className="eyebrow">开始第一次实验</p>
          <h2>从一个 Agent、一个数据集和一个评分开始。</h2>
          <p>所有配置都会保留版本，方便解释每次比较结果。</p>
        </div>
        <div className="quick-actions">
          <button onClick={() => onNavigate("agents")}>
            <Bot size={17} /> 添加 Agent
          </button>
          <button onClick={() => onNavigate("datasets")}>
            <Database size={17} /> 添加数据集
          </button>
          <button className="primary" onClick={() => onNavigate("runs")}>
            <Play size={16} /> 新建评测
          </button>
        </div>
      </section>
    </>
  );
}

function ResourceView({
  view,
  onAction,
}: {
  view: Exclude<ViewKey, "overview">;
  onAction: () => void;
}) {
  const meta = viewMeta[view];
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [resourceNotice, setResourceNotice] = useState("");
  const [draftRows, setDraftRows] = useState<(typeof resourceRows)["agents"]>(
    [],
  );
  const rows = [...resourceRows[view], ...draftRows];
  const visibleRows = rows.filter((row) => {
    const matchesQuery =
      !query.trim() ||
      `${row.name} ${row.detail} ${row.meta}`
        .toLowerCase()
        .includes(query.trim().toLowerCase());
    return (
      matchesQuery && (statusFilter === "all" || row.tone === statusFilter)
    );
  });
  const createLabel =
    view === "runs"
      ? "运行"
      : view === "traces"
        ? "Trace"
        : view === "agents"
          ? "Agent"
          : view === "datasets"
            ? "数据集"
            : "评估器";
  function createResource() {
    if (view === "agents" || view === "datasets" || view === "runs") {
      onAction();
      return;
    }
    const name = view === "evaluators" ? `新评估器草稿 ${draftRows.length + 1}` : `新 Trace 草稿 ${draftRows.length + 1}`;
    setDraftRows((current) => [
      {
        name,
        detail: "本地草稿，等待配置",
        status: "草稿",
        tone: "neutral",
        meta: "刚刚创建",
      },
      ...current,
    ]);
    setSelectedName(name);
    setResourceNotice(`${createLabel}草稿已创建，仅保存在当前页面；真实${createLabel}接口尚未接入。`);
  }
  return (
    <section className="resource-view">
      <div className="resource-heading">
        <div>
          <p className="eyebrow">{meta.eyebrow}</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <button className="primary" onClick={createResource}>
          <Plus size={17} /> 新建{createLabel}
        </button>
      </div>
      <div className="toolbar">
        <div className="search-field">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={`搜索${meta.title}`}
            placeholder={`搜索${meta.title}...`}
          />
        </div>
        <select
          className="filter-button"
          aria-label="状态筛选"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="all">全部状态</option>
          <option value="success">正常</option>
          <option value="warning">需关注</option>
          <option value="danger">错误</option>
          <option value="neutral">草稿</option>
        </select>
      </div>
      <div className="resource-list">
        {visibleRows.map((row, index) => (
          <div className="resource-row" key={`${row.name}-${index}`}>
            <div className="resource-symbol">
              <Boxes size={18} />
            </div>
            <div className="resource-main">
              <strong>{row.name}</strong>
              <span>{row.detail}</span>
            </div>
            <span className="resource-meta">{row.meta}</span>
            <StatusMark tone={row.tone} label={row.status} />
            <button
              className="icon-button"
              title={`打开 ${row.name}`}
              aria-label={`打开 ${row.name}`}
              onClick={() => {
                setSelectedName(row.name);
                setResourceNotice(`${row.name}为演示资源，详情接口尚未接入。`);
              }}
            >
              <ArrowUpRight size={17} />
            </button>
          </div>
        ))}
      </div>
      {visibleRows.length === 0 && (
        <div className="empty-state">
          <Braces size={26} />
          <h2>暂无匹配资源</h2>
          <p>调整搜索词或状态筛选条件。</p>
          <button className="primary" onClick={createResource}>
            <Plus size={17} /> 创建资源
          </button>
        </div>
      )}
      {selectedName && (
        <div className="inline-notice">
          <Check size={16} /> {resourceNotice || `已打开资源：${selectedName}`}
        </div>
      )}
    </section>
  );
}

export default function Home() {
  const [activeView, setActiveView] = useState<ViewKey>("overview");
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false);
  const [globalQuery, setGlobalQuery] = useState("");
  const [globalNotice, setGlobalNotice] = useState("");
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const activeLabel =
    navItems.find((item) => item.key === activeView)?.label ?? "总览";

  function submitGlobalSearch() {
    const normalized = globalQuery.trim().toLowerCase();
    if (!normalized) {
      setGlobalNotice("请输入要搜索的导航名称。");
      return;
    }
    const match = navItems.find((item) => item.label.toLowerCase().includes(normalized));
    if (match) {
      setActiveView(match.key);
      setGlobalSearchOpen(false);
      setGlobalQuery("");
      setGlobalNotice("");
    } else {
      setGlobalNotice(`没有找到“${globalQuery.trim()}”对应的导航。`);
    }
  }
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AE</div>
          <div>
            <strong>Agent Eval</strong>
            <span>评测工作台</span>
          </div>
        </div>
        <button className="workspace-switcher" onClick={() => setWorkspaceOpen((current) => !current)} aria-expanded={workspaceOpen}>
          <span>工作区</span>
          <strong>本地项目</strong>
          <ChevronDown size={15} />
        </button>
        {workspaceOpen && <div className="workspace-menu"><strong>本地项目</strong><span>当前为本地开发工作区</span></div>}
        <nav aria-label="主导航">
          {navItems.map(({ key, label, icon: Icon }) => (
            <button
              className={activeView === key ? "nav-item active" : "nav-item"}
              key={key}
              aria-label={label}
              onClick={() => setActiveView(key)}
            >
              <Icon size={18} />
              <span>{label}</span>
              {key === "runs" && <i className="nav-count">3</i>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="system-status">
            <span className="pulse" /> API 已连接<span>v0.1.0</span>
          </div>
          <div className="profile">
            <div className="avatar">D</div>
            <div>
              <strong>开发者</strong>
              <span>单人工作区</span>
            </div>
            <button className="more-dots-button" aria-label="打开个人菜单" aria-expanded={profileOpen} onClick={() => setProfileOpen((current) => !current)}><MoreDots /></button>
            {profileOpen && <div className="profile-menu"><strong>开发者</strong><span>本地单人工作区</span></div>}
          </div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            <span>评测工作台</span>
            <b>/</b>
            <strong>{activeLabel}</strong>
          </div>
          <div className="topbar-actions">
            {globalSearchOpen && (
              <label className="topbar-search">
                <Search size={15} />
                <input
                  autoFocus
                  value={globalQuery}
                  onChange={(event) => setGlobalQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") submitGlobalSearch();
                    if (event.key === "Escape") {
                      setGlobalSearchOpen(false);
                      setGlobalQuery("");
                    }
                  }}
                  placeholder="搜索导航"
                  aria-label="搜索导航"
                />
              </label>
            )}
            <button
              className="icon-button"
              title="搜索工作区"
              aria-label="搜索工作区"
              onClick={() => setGlobalSearchOpen((current) => !current)}
            >
              <Search size={18} />
            </button>
            <button
              className="outline-button"
              onClick={() => setActiveView("traces")}
            >
              <Activity size={16} /> 实时 Trace
            </button>
            <button className="primary" onClick={() => setActiveView("runs")}>
              <Play size={16} /> 新建运行
            </button>
          </div>
          {globalNotice && <div className="global-search-notice" role="status">{globalNotice}</div>}
        </header>
        <div className="page-content">
          {activeView === "overview" ? (
            <Overview onNavigate={setActiveView} />
          ) : activeView === "agents" ? (
            <AgentsView />
          ) : activeView === "datasets" ? (
            <DatasetsView />
          ) : activeView === "runs" ? (
            <RunsView />
          ) : activeView === "reports" ? (
            <ReportsView />
          ) : activeView === "evaluators" ? (
            <EvaluatorsView />
          ) : activeView === "traces" ? (
            <TracesView />
          ) : (
            <ResourceView
              view={activeView}
              onAction={() => setActiveView(activeView)}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function MoreDots() {
  return (
    <span className="more-dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}
