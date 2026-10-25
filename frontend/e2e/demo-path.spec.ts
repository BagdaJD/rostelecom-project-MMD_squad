import { expect, test, type Page } from '@playwright/test';

/**
 * Демо-путь из ТЗ: вход → радар (фильтры, таблица, квадрант) → карточка компании →
 * навигатор (проект, потребности) → калькулятор (расчёт, выгрузки).
 * Вход двухфакторный, мок отвечает на любые креды (пароль ≥ 8 симв., код ≥ 6 цифр).
 */

async function login(page: Page) {
  await page.goto('/?mock=1');
  await expect(page.getByRole('heading', { name: 'Вход в систему' })).toBeVisible();
  await page.getByLabel('Логин или e-mail').fill('analyst');
  await page.getByLabel('Пароль').fill('password123');
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByRole('heading', { name: 'Подтверждение второго фактора' })).toBeVisible();
  await page.getByLabel('Одноразовый код').fill('123456');
  await page.getByRole('button', { name: 'Подтвердить' }).click();
  await expect(page.getByRole('heading', { name: 'Главный дашборд' })).toBeVisible();
}

test('демо-путь: радар → карточка компании → навигатор → калькулятор', async ({ page }) => {
  await login(page);

  // Шапка: глобальный фильтр региона и человек (роль + 2FA).
  const globalRegion = page.getByLabel('Глобальный фильтр региона').locator('select');
  await globalRegion.selectOption('3');
  await expect(globalRegion).toHaveValue('3');

  // Радар: фильтр региона применяется к срезу.
  await page.getByRole('link', { name: 'Радар присутствия' }).click();
  await expect(page.getByText('Карта потенциала')).toBeVisible();
  const row = page.locator('tr', { hasText: 'Нива-Агро ТЮ' });
  await expect(row).toBeVisible();

  // Сортировка по выручке и пагинация — элементы таблицы на месте.
  await page.getByRole('button', { name: 'Сортировать: Выручка, млн ₽' }).click();
  await expect(row).toBeVisible();
  await page.getByRole('button', { name: 'Карточка' }).first().click();
  await expect(page.getByText('Карточка компании')).toBeVisible();

  // Полная карточка компании.
  await page.getByRole('link', { name: /Открыть карточку целиком/ }).click();
  await expect(page).toHaveURL(/\/companies\/\d+/);
  await expect(page.getByRole('heading', { name: /Нива-Агро/ })).toBeVisible();

  // Инвестиционный навигатор: фильтр стадии и карточка проекта.
  await page.getByRole('link', { name: 'Инвестиционный навигатор' }).click();
  await page.getByLabel('Стадия').selectOption('design');
  await expect(page.getByText('Строительство теплично-овощного комплекса «Нива-Агро»')).toBeVisible();
  await page.getByRole('button', { name: /проект #201/ }).click();
  await expect(page.getByText('Вероятные потребности')).toBeVisible();
  await expect(page.getByText('IoT и АСУ ТП')).toBeVisible();

  // Калькулятор: расчёт и выгрузка.
  await page.getByRole('link', { name: 'Калькулятор сделок' }).click();
  await page.getByLabel('Тип проекта').selectOption('connectivity');
  await page.getByLabel('Масштаб').selectOption('medium');
  await page.getByRole('button', { name: 'Рассчитать диапазон' }).click();
  await expect(page.getByRole('heading', { name: 'Ценовая вилка' })).toBeVisible();
  await expect(page.getByText('Аналогов мало: оценка требует проверки специалистом')).toBeVisible();

  // Выход возвращает на экран входа.
  await page.getByRole('button', { name: 'Выйти' }).click();
  await expect(page.getByRole('heading', { name: 'Вход в систему' })).toBeVisible();
});

test('без активной сессии показывается форма входа, а не пустой экран', async ({ page }) => {
  // Access-токен живёт в памяти (ТЗ 13): перезагрузка без httpOnly-cookie → снова вход.
  await page.goto('/?mock=1');
  await expect(page.getByRole('heading', { name: 'Вход в систему' })).toBeVisible({ timeout: 10_000 });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вход в систему' })).toBeVisible({ timeout: 10_000 });
});