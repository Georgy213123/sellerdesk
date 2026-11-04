import { expect, test } from "./fixtures";
import { login, noHorizontalScroll } from "./helpers";

test("агент: запустить разбор → готово → одобрить шаблон → шаблон виден во вкладке «Шаблоны»", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "Агент" }).click();

  const [started] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/agent/runs") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Запустить разбор" }).click(),
  ]);
  const { id } = (await started.json()) as { id: number };
  await expect(page.getByTestId("agent-run").filter({ hasText: `№${id}:` })).toContainText(
    "готово",
  );

  const proposal = page.locator('[data-testid="proposal"][data-kind="reply_template"]').first();
  await expect(proposal).toContainText("Случаев:");
  const title = await proposal.getByRole("heading").innerText();
  await noHorizontalScroll(page);
  await proposal.getByRole("button", { name: "Одобрить" }).click();
  await expect(page.getByRole("heading", { name: title })).toHaveCount(0);

  await page.getByRole("button", { name: "Шаблоны" }).click();
  await expect(page.getByRole("heading", { name: title, level: 3 })).toBeVisible();
  await noHorizontalScroll(page);
});
