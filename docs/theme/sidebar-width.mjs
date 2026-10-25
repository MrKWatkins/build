// SPDX-License-Identifier: GPL-3.0-only
export function fitSidebar() {
  const root = document.documentElement;
  let frame;
  let stopped = false;

  function measure() {
    const nav = document.querySelector('#VPSidebarNav');
    if (!nav) return root.style.removeProperty('--build-sidebar-content-width');

    // Measure every label, including collapsed sections, at its natural width.
    const copy = nav.cloneNode(true);
    copy.removeAttribute('id');
    copy.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
    copy.querySelectorAll('.collapsed').forEach(node => node.classList.remove('collapsed'));
    copy.querySelectorAll(':scope > .group').forEach(node => { node.style.width = 'max-content'; });
    copy.setAttribute('aria-hidden', 'true');
    copy.inert = true;
    Object.assign(copy.style, {
      position: 'fixed', visibility: 'hidden', left: '-10000px', top: '0',
      width: 'max-content', maxWidth: 'none'
    });
    nav.parentElement.append(copy);
    // VitePress adds 32px on either side; its extra wide-screen gutter stays intact.
    const width = Math.max(360, Math.ceil(copy.getBoundingClientRect().width) + 64);
    copy.remove();
    root.style.setProperty('--build-sidebar-content-width', `${width}px`);
  }

  function schedule() {
    if (stopped) return;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(measure);
  }

  const observer = new MutationObserver(records => {
    if (records.some(({ target, addedNodes }) =>
      target.closest?.('#VPSidebarNav') || target.parentElement?.closest('#VPSidebarNav') ||
      [...addedNodes].some(node => node.matches?.('.VPSidebar, #VPSidebarNav') || node.querySelector?.('#VPSidebarNav'))
    )) schedule();
  });
  observer.observe(document.body, { childList: true, characterData: true, subtree: true });
  window.addEventListener('resize', schedule);
  document.fonts.ready.then(schedule);
  schedule();

  return () => {
    stopped = true;
    observer.disconnect();
    window.removeEventListener('resize', schedule);
    cancelAnimationFrame(frame);
    root.style.removeProperty('--build-sidebar-content-width');
  };
}
