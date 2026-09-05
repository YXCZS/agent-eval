import { expect, test } from "@playwright/test";

const agent = { id: "agent-1", name: "Order agent", agent_type: "prompt", description: "demo", active: true };
const promptConfig = {
  provider: "OpenAI-compatible",
  model: "test-model",
  endpoint: "https://example.com/v1/chat/completions",
  system_prompt: "Be concise.",
  user_template: "Answer {{question}}",
  variable_names: ["question"],
  temperature: 0.2,
  top_p: 1,
  max_tokens: 100,
  response_format: null,
  timeout_seconds: 30,
  concurrency_limit: 2,
  max_retries: 1,
};
const agentVersion = { id: "agent-v1", agent_id: agent.id, version: 1, label: "Order agent v1", agent_type: "prompt", enabled: true, prompt_config: promptConfig, endpoint_config: null };
const dataset = { id: "dataset-1", name: "Smoke dataset", current_version_id: "dataset-v1" };
const datasetVersion = { id: "dataset-v1", dataset_id: dataset.id, version: 1, cases: [{ id: "case-1", input: "hello", variables: {}, expected_output: null, metadata: {} }] };
const evaluator = { id: "evaluator-v1", name: "task_success", version: "1.0.0", evaluator_type: "deterministic", supported_agent_types: ["prompt"], enabled: true, requires: [] };
const run = { id: "run-1", status: "completed", total_cases: 1, completed_cases: 1, failed_cases: 0, agent_version_id: agentVersion.id, dataset_version_id: datasetVersion.id, evaluator_version_ids: [evaluator.id], created_at: "2026-01-01T00:00:00Z", case_executions: [{ id: "execution-1", case_id: "case-1", status: "completed", trace_id: "trace-1" }] };
const summary = { run_id: run.id, status: "completed", agent_version_id: agentVersion.id, dataset_version_id: datasetVersion.id, total_cases: 1, completed_cases: 1, failed_cases: 0, created_at: "2026-01-01T00:00:00Z", finished_at: "2026-01-01T00:01:00Z", metrics: [{ metric_name: "task_success", evaluator_version_id: evaluator.id, valid_count: 1, missing_count: 0, error_count: 0, passed_count: 1, average: 1, pass_rate: 1, aggregation: "pass_rate", threshold: 0.9, direction: "higher_is_better" }] };

test("all primary workbench controls trigger a workflow", async ({ page }) => {
  let agentsCreated = false;
  let datasetCreated = false;
  await page.route("**/projects/project-1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body: unknown, status = 200, contentType = "application/json") => route.fulfill({ status, contentType, body: contentType === "application/json" ? JSON.stringify(body) : String(body) });
    if (method === "GET" && path === "/projects/project-1/agents") return json(agentsCreated ? [agent] : []);
    if (method === "GET" && path === "/projects/project-1/agents/agent-1/versions") return json([agentVersion]);
    if (method === "POST" && path === "/projects/project-1/agents") { agentsCreated = true; return json(agent, 201); }
    if (method === "POST" && path === "/projects/project-1/agents/agent-1/versions") return json({ ...agentVersion, id: "agent-v2", version: 2, label: "Order agent v2" }, 201);
    if (method === "GET" && path === "/projects/project-1/datasets") return json(datasetCreated ? [dataset] : []);
    if (method === "GET" && path === "/projects/project-1/datasets/dataset-1/versions") return json([datasetVersion]);
    if (method === "POST" && path === "/projects/project-1/datasets") { datasetCreated = true; return json(dataset, 201); }
    if (method === "GET" && path === "/projects/project-1/evaluators") return json([evaluator]);
    if (method === "GET" && path === "/projects/project-1/runs") return json([]);
    if (method === "POST" && path === "/projects/project-1/runs") return json(run, 201);
    if (method === "GET" && path === "/projects/project-1/runs/run-1") return json(run);
    if (method === "POST" && path === "/projects/project-1/runs/run-1/cancel") return json({ ...run, status: "cancelled" });
    if (method === "GET" && path === "/projects/project-1/reports") return json([summary]);
    if (method === "GET" && path === "/projects/project-1/reports/run-1") return json({ ...summary, matched_cases: 1, generated_at: "2026-01-01T00:01:00Z", filters: {}, cases: [{ case_id: "case-1", metadata: {}, execution_status: "completed", error_type: null, error_message: null, output: "ok", trace_id: "trace-1", scores: [] }] });
    if (method === "GET" && path === "/projects/project-1/traces/trace-1/timeline") return json({ trace_id: "trace-1", started_at: "2026-01-01T00:00:00Z", ended_at: "2026-01-01T00:00:01Z", spans: [] });
    if (method === "POST" && path === "/projects/project-1/comparisons") return json({ dataset_version_id: datasetVersion.id, baseline_run_id: run.id, metric_comparisons: [], new_failures: [], recovered_cases: [] });
    if (method === "POST" && path === "/projects/project-1/runs/run-1/regression-gate") return json({ run_id: run.id, run_status: "completed", status: "passed", generated_at: "2026-01-01T00:01:00Z", rules: [{ rule: { metric_name: "task_success", evaluator_version_id: evaluator.id, aggregation: "pass_rate", minimum: 0.9, require_all_passed: false }, status: "passed", actual_value: 1, valid_count: 1, missing_count: 0, error_count: 0, failed_case_ids: [], reason: null }] });
    if (method === "GET" && path.endsWith("/export")) return json("report", 200, "text/csv");
    return json({ detail: `Unhandled ${method} ${path}` }, 404);
  });

  await page.goto("/");
  await page.getByRole("button", { name: "搜索工作区" }).click();
  await page.getByRole("textbox", { name: "搜索导航" }).fill("Agent");
  await page.getByRole("textbox", { name: "搜索导航" }).press("Enter");
  await expect(page.getByRole("heading", { name: "Agent 管理" })).toBeVisible();
  await page.getByRole("button", { name: "新建 Agent", exact: true }).click();
  await page.getByLabel("Agent 名称").fill("Browser agent");
  await page.getByRole("button", { name: "创建 Agent", exact: true }).click();
  await expect(page.getByText("Agent 已创建并保存到当前工作区。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建版本" }).click();
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.getByText("已保存为新的 Agent 版本。", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "数据集", exact: true }).click();
  await page.getByLabel("数据集名称").fill("Browser dataset");
  await page.locator("textarea").first().fill("hello");
  await page.getByRole("button", { name: "添加行" }).click();
  await expect(page.getByText("2 个用例", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "移除用例" }).last().click();
  await page.getByRole("button", { name: "创建数据集", exact: true }).click();
  await expect(page.getByText("数据集已创建，包含 1 个用例。", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "评测运行", exact: true }).click();
  await expect(page.getByText("Order agent v1", { exact: true })).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "开始评测", exact: true }).click();
  await expect(page.getByText("已排队", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "评测报告", exact: true }).click();
  await expect(page.locator(".metric-tile").getByText("task_success", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "case-1" }).click();
  await expect(page.getByText("实际输出", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "比较与门禁" }).click();
  await page.getByLabel("指标").selectOption(`task_success::${evaluator.id}`);
  await page.getByRole("button", { name: "评估门禁" }).click();
  await expect(page.getByText("100%", { exact: true })).toBeVisible();
});
