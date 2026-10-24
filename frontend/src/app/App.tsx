import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavLink, Route, Routes } from 'react-router-dom';

import { LoginPage } from '@/pages/LoginPage';
import { RadarPage } from '@/pages/RadarPage';
import { NavigatorPage } from '@/pages/NavigatorPage';
import { CalculatorPage } from '@/pages/CalculatorPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { getToken } from '@/api/client';
import '../styles/global.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function Shell() {
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
      </header>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/radar" element={<RadarPage />} />
        <Route path="/navigator" element={<NavigatorPage />} />
        <Route path="/calculator" element={<CalculatorPage />} />
      </Routes>
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {getToken() ? <Shell /> : <LoginPage />}
    </QueryClientProvider>
  );
}
