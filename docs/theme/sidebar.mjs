// SPDX-License-Identifier: GPL-3.0-only
export function toggleCurrentSection(event) {
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest?.('.VPSidebar .item > a.link');
  if (!link || link.target || link.hasAttribute('download') || link.href !== window.location.href) return;
  const caret = link.closest('.VPSidebarItem').querySelector(':scope > .item > .caret');
  if (!caret) return;
  event.preventDefault();
  caret.click();
}
