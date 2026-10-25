import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { installMocks } from '@/api/mocks';
import { App } from './App';

const container = document.getElementById('root');
if (!container) throw new Error('не найден корень приложения #root');

// До первого запроса: в dev мок подменяет fetch, когда бэкенд не поднят.
installMocks();

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
