import { expect, type Page } from "@playwright/test";

export const OPERATOR_PASSWORD = process.env.E2E_OPERATOR_PASSWORD ?? "demo-password";

export async function login(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Логин").fill("operator");
  await page.getByLabel("Пароль").fill(OPERATOR_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("navigation", { name: "Разделы" })).toBeVisible();
}

export async function filterByMarketplace(page: Page, label: string): Promise<void> {
  await page.getByLabel("Площадка").selectOption({ label });
  const items = page.getByTestId("chat-item");
  await expect(items.first()).toBeVisible();
  await expect
    .poll(async () => new Set(await items.evaluateAll((els) => els.map((e) => e.dataset.marketplace))))
    .toEqual(new Set([label === "Ozon" ? "ozon" : label === "Wildberries" ? "wildberries" : "yandex_market"]));
}

export async function noHorizontalScroll(page: Page): Promise<void> {
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(scroll).toBeLessThanOrEqual(client);
}
