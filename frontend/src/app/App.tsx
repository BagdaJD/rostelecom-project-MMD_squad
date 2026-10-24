import { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';

import { LoginPage } from '@/pages/LoginPage';
import { RadarPage } from '@/pages/RadarPage';
import { NavigatorPage } from '@/pages/NavigatorPage';
import { CalculatorPage } from '@/pages/CalculatorPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { getToken, onSessionExpired, setToken } from '@/api/client';
import '../styles/global.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function Shell({ onLogout }: { onLogout: () => void }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <strong>Экосистема коммерческого блока</strong>
        <nav>
          <NavLink to="/">Дашборд</NavLink>
          <NavLink to="/radar">Радар присутствия</NavLink>
          <NavLink to="/navigator">Инвестиционный навигатор</NavLink>
          <NavLink to="/calculator">Калькулятор сделок</NavLink>
        </nav>
        <button type="button" onClick={onLogout}>
          Выйти
        </button>
      </header>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/radar" element={<RadarPage />} />
        <Route path="/navigator" element={<NavigatorPage />} />
        <Route path="/calculator" element={<CalculatorPage />} />
        {/* Неизвестный путь иначе рендерил пустой экран без навигации. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

export function App() {
  // Токен лежит в sessionStorage, а React про него не знает: держим зеркало в состоянии,
  // иначе «Выйти» очистит хранилище, но экран останется авторизованным до перезагрузки.
  const [authed, setAuthed] = useState(() => Boolean(getToken()));
  // Причина, по которой слетела сессия: без неё вход с экрана «Войти» выглядит молча.
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  useEffect(() => {
    const unsubscribe = onSessionExpired((reason) => {
      queryClient.clear();
      setAuthed(false);
      setSessionNotice(reason);
    });
    return unsubscribe;
  }, []);

  function logout() {
    setToken(null);
    queryClient.clear();
    setSessionNotice(null);
    setAuthed(false);
  }

  return (
    <QueryClientProvider client={queryClient}>
      {authed ? (
        <Shell onLogout={logout} />
      ) : (
        <LoginPage notice={sessionNotice} onDismissNotice={() => setSessionNotice(null)} />
      )}
    </QueryClientProvider>
  );
}
