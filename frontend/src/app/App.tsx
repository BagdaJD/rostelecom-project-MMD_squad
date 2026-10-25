import { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';

import { LoginPage } from '@/pages/LoginPage';
import { RadarPage } from '@/pages/RadarPage';
import { NavigatorPage } from '@/pages/NavigatorPage';
import { CalculatorPage } from '@/pages/CalculatorPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { CompanyCardPage } from '@/pages/CompanyCardPage';
import { api, onAuthenticated, onSessionExpired, setToken } from '@/api/client';
import { isMockMode } from '@/api/mocks';
import { GlobalFilter, GlobalRegionProvider, readGlobalRegion, writeGlobalRegion } from '@/components/GlobalFilter';
import { Loading } from '@/components/states';
import '../styles/global.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

/** Роль и состояние 2FA из GET /auth/me (ТЗ 13): шапка показывает, кто вошёл. */
function useAuthMe() {
  const [user, setUser] = useState<{ login: string; role: string; mfa_enabled: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((me) => {
        if (!cancelled) setUser({ login: me.login, role: me.role, mfa_enabled: me.mfa_enabled });
      })
      .catch(() => {
        // 401 обрабатывает клиент (onSessionExpired), остальное показывать не обязательно.
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return user;
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const demoMode = isMockMode();
  const [region, setRegion] = useState<number | null>(() => readGlobalRegion());
  const user = useAuthMe();
  const [regions, setRegions] = useState<{ id: number; name: string }[]>([]);

  useEffect(() => {
    api
      .regions()
      .then((items) => setRegions(items.map((item) => ({ id: item.id, name: item.name }))))
      .catch(() => setRegions([]));
  }, []);

  const globalRegion = region;

  function changeRegion(value: number | null) {
    setRegion(value);
    writeGlobalRegion(value);
  }

  return (
    <div className="app-shell">
      <GlobalRegionProvider value={region}>
        <header className="app-header">
        <strong>Экосистема коммерческого блока</strong>
        <nav>
          <NavLink to="/">Дашборд</NavLink>
          <NavLink to="/radar">Радар присутствия</NavLink>
          <NavLink to="/navigator">Инвестиционный навигатор</NavLink>
          <NavLink to="/calculator">Калькулятор сделок</NavLink>
        </nav>
        <GlobalFilter regions={regions} value={globalRegion} onChange={changeRegion} />
        {demoMode && (
          <span
            className="demo-badge"
            role="note"
            title="Синтетические данные и мок-сервер: не является реальной аналитикой"
          >
            Демо-режим: синтетические данные
          </span>
        )}
        {user && (
          <span
            className="user-chip"
            title={`Логин: ${user.login} · Роль: ${user.role} · 2FA: ${user.mfa_enabled ? 'включён' : 'выключен'}`}
          >
            {user.login} · {user.role} · 2FA:{' '}
            {user.mfa_enabled ? 'вкл' : 'выкл'}
          </span>
        )}
        <button type="button" onClick={onLogout}>
          Выйти
        </button>
      </header>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/radar" element={<RadarPage />} />
        <Route path="/companies/:id" element={<CompanyCardPage />} />
        <Route path="/navigator" element={<NavigatorPage />} />
        <Route path="/calculator" element={<CalculatorPage />} />
        {/* Неизвестный путь иначе рендерил пустой экран без навигации. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </GlobalRegionProvider>
    </div>
  );
}

export function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  // Вход и 2FA сообщают клиенту, что токен поставлен: Shell рендерится без перезагрузки.
  useEffect(() => {
    const unsubscribe = onAuthenticated(() => {
      setSessionNotice(null);
      setAuthed(true);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Access-токен не сохраняется между перезагрузками (ТЗ 13): при старте пробуем
    // молча продлить сессию по httpOnly-cookie; в моках refresh отдаёт новый токен.
    api
      .refresh()
      .then((tokens) => {
        if (cancelled) return;
        if (tokens.access_token) {
          setToken(tokens.access_token);
          setAuthed(true);
        } else {
          setAuthed(false);
        }
      })
      .catch(() => {
        if (!cancelled) setAuthed(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const unsubscribe = onSessionExpired((reason) => {
      queryClient.clear();
      setAuthed(false);
      setSessionNotice(reason);
    });
    return unsubscribe;
  }, []);

  async function logout() {
    try {
      // Сервер отзывает refresh-сессию; ошибка не должна блокировать локальный выход.
      await api.logout();
    } catch {
      // ignore: локальный выход обязателен
    }
    setToken(null);
    queryClient.clear();
    setSessionNotice(null);
    setAuthed(false);
  }

  return (
    <QueryClientProvider client={queryClient}>
      {authed === null ? (
        <main className="app-body login-boot">
          <Loading label="Проверяем сессию" />
        </main>
      ) : authed ? (
        <Shell onLogout={logout} />
      ) : (
        <LoginPage notice={sessionNotice} onDismissNotice={() => setSessionNotice(null)} />
      )}
    </QueryClientProvider>
  );
}