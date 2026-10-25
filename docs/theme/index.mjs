// SPDX-License-Identifier: GPL-3.0-only
import DefaultTheme from 'vitepress/theme';
import { toggleCurrentSection } from './sidebar.mjs';
import { fitSidebar } from './sidebar-width.mjs';
import './style.css';

// Theme imports run before VitePress installs its router's capture listener.
if (typeof window !== 'undefined') {
  const stopFittingSidebar = fitSidebar();
  window.addEventListener('click', toggleCurrentSection, true);
  if (import.meta.hot) {
    import.meta.hot.dispose(() => {
      stopFittingSidebar();
      window.removeEventListener('click', toggleCurrentSection, true);
    });
  }
}

export default DefaultTheme;
