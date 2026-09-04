import { expect, test } from "@playwright/test";

const agent = { id: "agent-1", name: "Order agent", agent_type: "tool", active: true };
const agentVersion = { id: "agent-v1", version: 1, label: "baseline", agent_type: "tool", enabled: true };
const dataset = { id: "dataset-1", name: "Order regression", current_version_id: "dataset-v2" };
const datasetVersion = { id: "dataset-v2", version: 2, cases: [{ id: "cancel-42" }] };
const evaluator = { id: "evaluator-v1", name: "task_success", version: "1.0.0", evaluator_type: "deterministic", supported_agent_types: ["tool"], enabled: true, requires: ["expected_state"] };
const run = { id: "run-1", status: "completed", total_cases: 1, completed_cases: 1, failed_cases: 0, agent_version_id: agentVersion.id, dataset_version_id: datasetVersion.id, evaluator_version_ids: [evaluator.id], created_at: "2026-01-01T00:00:00Z", case_executions: [{ id: "execution-1", case_id: "cancel-42", status: "completed" }] };
const reportSummary = { run_id: run.id, dataset_version_id: datasetVersion.id, status: "completed", total_cases: 1, metrics: [{ metric_name: "task_success", evaluator_version_id: evaluator.id, valid_count: 1, missing_count: 0, error_count: 0, passed_count: 1, pass_rate: 1, average: 1, threshold: 1, direction: "higher_is_better" }] };

test("imports a dataset, starts an evaluation, and evaluates its regression gate", async ({ page }) => {
  let datasetCreated = false;
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (method === "POST" && path === "/projects/project-1/datasets") {
      datasetCreated = true;
      return json({ ...dataset, current_version_id: "dataset-v1" }, 201);
    }
    if (method === "POST" && path.endsWith("/imports/preview")) return json({ cases: [{ id: "cancel-42", input: "Cancel order 42", expected_output: null }], issues: [] });
    if (method === "POST" && path.endsWith("/imports/commit")) return json({ dataset_version: datasetVersion, issues: [] }, 201);
    if (method === "GET" && path === "/projects/project-1/agents") return json([agent]);
    if (method === "GET" && path === "/projects/project-1/agents/agent-1/versions") return json([agentVersion]);
    if (method === "GET" && path === "/projects/project-1/datasets") return json(datasetCreated ? [dataset] : []);
    if (method === "GET" && path === "/projects/project-1/datasets/dataset-1/versions") return json([datasetVersion]);
    if (method === "GET" && path === "/projects/project-1/evaluators") return json([evaluator]);
    if (method === "GET" && path === "/projects/project-1/runs") return json([]);
    if (method === "POST" && path === "/projects/project-1/runs") return json(run, 201);
    if (method === "GET" && path === "/projects/project-1/runs/run-1") return json(run);
    if (method === "GET" && path === "/projects/project-1/reports") return json([reportSummary]);
    if (method === "GET" && path === "/projects/project-1/reports/run-1") return json({ ...reportSummary, generated_at: "2026-01-01T00:00:00Z", matched_cases: 1, cases: [] });
    if (method === "POST" && path === "/projects/project-1/runs/run-1/regression-gate") return json({ run_id: run.id, run_status: "completed", status: "passed", generated_at: "2026-01-01T00:00:00Z", rules: [{ rule: { metric_name: "task_success", aggregation: "pass_rate", minimum: 0.9, require_all_passed: false }, status: "passed", actual_value: 1, valid_count: 1, missing_count: 0, error_count: 0, failed_case_ids: [] }] });
    return json({ detail: `Unhandled ${method} ${path}` }, 404);
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Datasets" }).click();
  await page.getByRole("button", { name: "Import file" }).click();
  await page.getByLabel("Dataset name").fill("Order regression");
  await page.locator("#dataset-file").setInputFiles({ name: "orders.csv", mimeType: "text/csv", buffer: Buffer.from("case_key,prompt\ncancel-42,Cancel order 42\n") });
  await page.getByRole("button", { name: "Preview import" }).click();
  await expect(page.getByText("1 valid cases", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Confirm import" }).click();
  await expect(page.getByText("Dataset imported as version 2.")).toBeVisible();

  await page.getByRole("button", { name: "Evaluation runs" }).click();
  await expect(page.getByText("Order agent v1")).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Start evaluation" }).click();
  await expect(page.getByText("queued with 1 cases")).toBeVisible();

  await page.getByRole("button", { name: "Reports" }).click();
  await page.getByRole("tab", { name: "Compare & gate" }).click();
  await page.getByLabel("Metric").selectOption("task_success");
  await page.getByRole("button", { name: "Evaluate gate" }).click();
  await expect(page.getByText("100%")).toBeVisible();
});
