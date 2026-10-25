// SPDX-License-Identifier: GPL-3.0-only
export function lazySidebar() {
  return {
    name: 'lazy-sidebar',
    enforce: 'pre',
    transform(source, id) {
      if (!id.endsWith('/theme-default/components/VPSidebarItem.vue')) return;
      const condition = 'v-if="item.items && item.items.length" class="items"';
      if (!source.includes(condition)) throw new Error('VitePress sidebar template changed; update lazy-sidebar.');
      return {
        code: source.replace(condition, 'v-if="item.items && item.items.length && !collapsed" class="items"'),
        map: null
      };
    }
  };
}
