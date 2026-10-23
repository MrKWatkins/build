// SPDX-License-Identifier: GPL-3.0-only
import DefaultTheme from 'vitepress/theme';
import { toggleCurrentSection } from './sidebar.mjs';
import './style.css';

// Theme imports run before VitePress installs its router's capture listener.
if (typeof window !== 'undefined') {
  window.addEventListener('click', toggleCurrentSection, true);
  if (import.meta.hot) {
    import.meta.hot.dispose(() => window.removeEventListener('click', toggleCurrentSection, true));
  }
}

export default DefaultTheme;
