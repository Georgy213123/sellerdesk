import { expect, test } from "@playwright/test";
import { filterByMarketplace, login, noHorizontalScroll } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("US-01…US-03: лента → фильтр → чат → AI-черновик → правка → отправка → «Отвечен»", async ({
  page,
}, testInfo) => {
  const signature = `Хорошего вечера! (${testInfo.project.name})`;
  await filterByMarketplace(page, "Ozon");
  await page.getByTestId("chat-item").first().click();

  const card = page.getByRole("region", { name: "Карточка чата" });
  await card.getByRole("button", { name: "AI-черновик" }).click();
  const box = card.getByRole("textbox", { name: "Текст ответа" });
  await expect(box).toHaveValue(/Северный свет/);
  await expect(card.getByRole("status")).toContainText("Черновик не отправлен");
  // BUG-11: карточка показывает тот же статус, что и лента. Второй проект идёт по той же базе,
  // где первый уже ответил в этот чат, поэтому сравниваем статусы между собой, а не с константой.
  const feedStatus = page
    .locator(".feed-item.active")
    .getByTestId("chat-status");
  await expect
    .poll(
      async () =>
        (await card.getByTestId("card-status").textContent()) ===
        (await feedStatus.textContent()),
    )
    .toBe(true);

  const edited = `${await box.inputValue()}\n${signature}`;
  await box.fill(edited);
  await card.getByRole("button", { name: "Отправить" }).click();

  await expect(card.getByTestId("card-status")).toHaveText("Отвечен");
  await expect(card.locator(".msg-operator").last()).toContainText(signature);
  await expect(
    card.locator(".msg-operator").filter({ hasText: signature }),
  ).toHaveCount(1);
});

test("US-05: шаблон с неподставленной переменной остаётся черновиком с предупреждением", async ({
  page,
}) => {
  // Второй чат Яндекс Маркета в детерминированном сиде — без номера заказа.
  // Другой площадки, чем в US-02, чтобы сценарии не зависели от порядка запуска.
  await filterByMarketplace(page, "Яндекс Маркет");
  await page.getByTestId("chat-item").nth(1).click();
  const card = page.getByRole("region", { name: "Карточка чата" });
  await card.getByLabel("Шаблон").selectOption({ label: "Статус заказа" });
  await card.getByRole("button", { name: "Ответить шаблоном" }).click();

  await expect(card.getByRole("alert")).toContainText("order_number");
  await expect(card.getByRole("textbox", { name: "Текст ответа" })).toHaveValue(
    /\{\{order_number\}\}/,
  );
  await expect(card.getByTestId("card-status")).toHaveText("В работе");
});

test("US-06: «Обновить» ставит синхронизацию, лента остаётся доступной", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Обновить" }).click();
  await expect(page.getByTestId("chat-item").first()).toBeVisible();
  await expect(page.getByTestId("sync-status")).toContainText("Данные на", {
    timeout: 15_000,
  });
});

test("NFR-04: лента читается без горизонтального скролла", async ({ page }) => {
  await expect(page.getByTestId("chat-item").first()).toBeVisible();
  await noHorizontalScroll(page);
  await page.getByTestId("chat-item").first().click();
  await expect(
    page.getByRole("region", { name: "Карточка чата" }).locator("h2"),
  ).toBeVisible();
  await noHorizontalScroll(page);
  if (page.viewportSize()!.width < 760) {
    // на телефоне карточка открывается вместо ленты и закрывается кнопкой «К ленте»
    await expect(
      page.getByRole("region", { name: "Лента чатов" }),
    ).toBeHidden();
    await page.getByRole("button", { name: "← К ленте" }).click();
    await expect(page.getByTestId("chat-item").first()).toBeVisible();
  }
});
