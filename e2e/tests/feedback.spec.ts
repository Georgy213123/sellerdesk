import { expect, test } from "@playwright/test";
import { login, noHorizontalScroll } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Отзывы и вопросы" }).click();
});

test("US-04: ответ на отзыв", async ({ page }) => {
  await page.getByLabel("Тип").selectOption({ label: "Отзывы" });
  await page.getByLabel("Ответ", { exact: true }).selectOption({ label: "Без ответа" });
  const item = page.getByTestId("feedback-item").first();
  const text = await item.locator(".user-text").first().innerText();
  await item.getByRole("button", { name: "Ответить", exact: true }).click();
  await item.getByRole("button", { name: "AI-черновик" }).click();
  await expect(item.getByRole("textbox", { name: "Текст ответа" })).toHaveValue(/Северный свет/);
  await item.getByRole("button", { name: "Ответить", exact: true }).click();
  // ответ принят площадкой — отзыв пропал из фильтра «Без ответа»
  await expect(page.getByTestId("feedback-item").filter({ hasText: text })).toHaveCount(0);

  // отзыв ушёл из фильтра «Без ответа» — переключаемся и находим его с ответом
  await page.getByLabel("Ответ", { exact: true }).selectOption({ label: "С ответом" });
  const answered = page.getByTestId("feedback-item").filter({ hasText: text });
  await expect(answered.getByTestId("feedback-answer").first()).toContainText("Северный свет");
});

test("BUG-04: разметка в тексте отзыва показывается текстом", async ({ page }) => {
  let dialog = false;
  page.on("dialog", async (d) => {
    dialog = true;
    await d.dismiss();
  });
  const item = page.getByTestId("feedback-item").filter({ hasText: "onerror" }).first();
  await expect(item).toContainText("<img src=x onerror=alert('xss')>");
  await expect(item.locator("img")).toHaveCount(0);
  expect(dialog).toBe(false);
  await noHorizontalScroll(page);
});
