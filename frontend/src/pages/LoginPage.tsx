import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { api } from '@/api/client';
import { isMockMode } from '@/api/mocks';

const loginSchema = z.object({
  login: z.string().min(2, 'Укажите логин или e-mail'),
  password: z.string().min(8, 'Минимум 8 символов'),
});

type FormValues = z.infer<typeof loginSchema>;

export function LoginPage({
  notice,
  onDismissNotice,
}: {
  notice?: string | null;
  onDismissNotice?: () => void;
} = {}) {
  const [partialToken, setPartialToken] = useState<string | null>(null);
  const [setupUri, setSetupUri] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const {
    register,
    handleSubmit,
    setError: setFieldError,
    formState: { errors },
  } = useForm<FormValues>({ mode: 'onSubmit' });

  async function onLogin(values: FormValues) {
    onDismissNotice?.();
    // Правила живут в zod-схеме: прогоняем её на отправке, иначе сообщения не показываются.
    const parsed = loginSchema.safeParse(values);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        if (issue.path[0] === 'login') setFieldError('login', { message: issue.message });
        if (issue.path[0] === 'password') setFieldError('password', { message: issue.message });
      }
      return;
    }
    setPending(true);
    setError(null);
    setSetupUri(null);
    try {
      const result = await api.login(values.login, values.password);
      if (result.mfa_required && result.partial_token) {
        if (result.mfa_setup_required) {
          const setup = await api.setup2fa(result.partial_token);
          setSetupUri(setup.otpauth_hint);
        }
        setPartialToken(result.partial_token);
        return;
      }
      setError('Сервер не вернул challenge для второго фактора');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Не удалось войти');
    } finally {
      setPending(false);
    }
  }

  async function onCode(event: React.FormEvent) {
    event.preventDefault();
    if (!partialToken) return;
    setPending(true);
    setError(null);
    try {
      const tokens = await api.verify2fa(partialToken, code);
      // setToken + уведомление App делает клиент: перезагрузка не нужна.
      void tokens;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Неверный код');
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="app-body" style={{ maxWidth: 460, margin: '0 auto' }}>
      {isMockMode() && (
        <div className="demo-badge demo-badge--card" role="note">
          Демо-режим: данные синтетические, сервер — мок. Вход с любыми логином и паролем
          (минимум 8 символов), код 2FA — любые 6 цифр.
        </div>
      )}
      {notice && (
        <div className="warning" role="alert">
          {notice}
        </div>
      )}
      <form className="card" onSubmit={handleSubmit(onLogin)} aria-busy={pending}>
        <h2>Вход в систему</h2>
        <p className="muted">
          Второй фактор обязателен по требованиям кейса: после ввода пароля потребуется код из
          приложения-аутентификатора.
        </p>

        <label>
          Логин или e-mail
          <input {...register('login')} autoComplete="username" />
          {errors.login && <span className="warning">{errors.login.message}</span>}
        </label>

        <label>
          Пароль
          <input type="password" {...register('password')} autoComplete="current-password" />
          {errors.password && <span className="warning">{errors.password.message}</span>}
        </label>

        {!partialToken && (
          <button type="submit" disabled={pending}>
            {pending ? 'Проверяем…' : 'Войти'}
          </button>
        )}
      </form>

      {partialToken && (
        <form className="card" onSubmit={onCode}>
          <h2>Подтверждение второго фактора</h2>
          {setupUri && (
            <p className="muted" role="note">
              Добавьте этот ключ в приложение-аутентификатор, затем введите одноразовый код:
              <br />
              <code>{setupUri}</code>
            </p>
          )}
          <label>
            Одноразовый код
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
            />
          </label>
          <button type="submit" disabled={pending || code.length < 6}>
            {pending ? 'Проверяем…' : 'Подтвердить'}
          </button>
          <p className="muted">Сессия подтверждения живёт 5 минут.</p>
        </form>
      )}

      {error && (
        <div className="warning" role="alert">
          {error}
        </div>
      )}
    </main>
  );
}
