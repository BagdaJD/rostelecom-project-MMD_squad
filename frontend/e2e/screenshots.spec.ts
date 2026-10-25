import { expect, test, type Page } from '@playwright/test';

/**
 * Скриншоты трёх экранов (радар, навигатор, калькулятор) на трёх ширинах
 * (1440 / 768 / 390) в frontend/__screenshots/ — контроль адаптива из ТЗ 11.2.
 * Заодно проверяем, что у документа нет горизонтального скролла.
 */

const WIDTHS: Array<{ name: string; width: number; height: number }> = [
  { name: '1440', width: 1440, height: 900 },
  { name: '768', width: 768, height: 1024 },
  { name: '390', width: 390, height: 844 },
];

async function login(page: Page) {
  await page.goto('/?mock=1');
  await page.getByLabel('Логин или e-mail').fill('analyst');
  await page.getByLabel('Пароль').fill('password123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await page.getByLabel('Одноразовый код').fill('123456');
  await page.getByRole('button', { name: 'Подтвердить' }).click();
  await expect(page.getByRole('heading', { name: 'Главный дашборд' })).toBeVisible();
}

async function expectNoPageHorizontalScroll(page: Page) {
  const sizes = await page.evaluate(() => {
    const doc = document.scrollingElement;
    return {
      scrollWidth: doc?.scrollWidth ?? 0,
      clientWidth: doc?.clientWidth ?? 0,
    };
  });
  expect(sizes.scrollWidth).toBeLessThanOrEqual(sizes.clientWidth + 1);
}

async function gotoRadar(page: Page) {
  await page.getByRole('link', { name: 'Радар присутствия' }).click();
  await expect(page.getByText('Карта потенциала')).toBeVisible();
  await expect(page.getByText(/Нива-Агро ТЮ/).first()).toBeVisible();
}

for (const viewport of WIDTHS) {
  test.describe(`ширина ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test(`радар ${viewport.name}`, async ({ page }) => {
      await login(page);
      await gotoRadar(page);
      await expectNoPageHorizontalScroll(page);
      await page.screenshot({
        path: `__screenshots/radar-${viewport.name}.png`,
        fullPage: true,
      });
    });

    test(`навигатор ${viewport.name}`, async ({ page }) => {
      await login(page);
      await gotoRadar(page);
      await page.getByRole('link', { name: 'Инвестиционный навигатор' }).click();
      await expect(page.getByText('Строительство теплично-овощного комплекса «Нива-Агро»')).toBeVisible();
      await expectNoPageHorizontalScroll(page);
      await page.screenshot({
        path: `__screenshots/navigator-${viewport.name}.png`,
        fullPage: true,
      });
    });

    test(`калькулятор ${viewport.name}`, async ({ page }) => {
      await login(page);
      await page.getByRole('link', { name: 'Калькулятор сделок' }).click();
      await page.getByLabel('Тип проекта').selectOption('connectivity');
      await page.getByLabel('Масштаб').selectOption('medium');
      await page.getByRole('button', { name: 'Рассчитать диапазон' }).click();
      await expect(page.getByRole('heading', { name: 'Ценовая вилка' })).toBeVisible();
      await expectNoPageHorizontalScroll(page);
      await page.screenshot({
        path: `__screenshots/calculator-${viewport.name}.png`,
        fullPage: true,
      });
    });
  });
}