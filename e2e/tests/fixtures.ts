import { expect, test as base } from "@playwright/test";

type GuardOptions = {
  /** HTTP-статусы 4xx/5xx от /api/, которые тест вызывает намеренно (и их строки в консоли браузера). */
  allowedStatuses: number[];
};

/**
 * Общая проверка после каждого теста: нет ошибок консоли и pageerror, нет ответов /api/ со
 * статусом ≥ 400 и нет горизонтального скролла. Ожидаемые 4xx разрешаются в describe:
 * `test.use({ allowedStatuses: [422] })`.
 */
export const test = base.extend<{ guard: void } & GuardOptions>({
  allowedStatuses: [[], { option: true }],
  guard: [
    async ({ page, allowedStatuses }, use) => {
      const problems: string[] = [];
      page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        const text = message.text();
        // Браузер сам пишет в консоль «Failed to load resource … status of 422» на каждый 4xx.
        const status = /status of (\d{3})/.exec(text)?.[1];
        if (status && allowedStatuses.includes(Number(status))) return;
        problems.push(`console.error: ${text}`);
      });
      page.on("response", (response) => {
        const status = response.status();
        if (status < 400 || allowedStatuses.includes(status)) return;
        if (new URL(response.url()).pathname.startsWith("/api/")) {
          problems.push(`HTTP ${status}: ${response.request().method()} ${response.url()}`);
        }
      });

      await use();

      if (!page.isClosed()) {
        const { scroll, client } = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }));
        if (scroll > client) problems.push(`горизонтальный скролл: scrollWidth ${scroll} > clientWidth ${client}`);
      }
      expect(problems, "ошибки браузера и API за время теста").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
