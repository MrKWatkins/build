// SPDX-License-Identifier: GPL-3.0-only
export function apiNavigation(manifest) {
  if (manifest.schemaVersion !== 1 || !Array.isArray(manifest.entries)) {
    throw new Error('API navigation.json must use schemaVersion 1 and contain entries.');
  }
  const entries = new Map();
  for (const entry of manifest.entries) {
    if (typeof entry.id !== 'string' || entries.has(entry.id) ||
        typeof entry.title !== 'string' || typeof entry.path !== 'string' ||
        !/^[^\\?#]+\.md$/.test(entry.path) || entry.path.startsWith('/') ||
        entry.path.split('/').some(segment => segment === '..' || segment === '.') ||
        !['namespace', 'type', 'member'].includes(entry.kind)) {
      throw new Error(`Invalid or duplicate API navigation entry: ${JSON.stringify(entry)}`);
    }
    entries.set(entry.id, entry);
  }
  for (const entry of entries.values()) {
    const visited = new Set([entry.id]);
    let parent = entry.parent;
    while (parent !== null) {
      if (!entries.has(parent) || visited.has(parent)) {
        throw new Error(`Missing or cyclic API parent for ${entry.id}.`);
      }
      visited.add(parent);
      parent = entries.get(parent).parent;
    }
  }
  function children(parent) {
    return [...entries.values()]
      .filter(entry => entry.parent === parent && entry.kind !== 'member')
      .sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0)
      .map(entry => {
        const items = children(entry.id);
        return {
          text: entry.title,
          link: `/api/${entry.path.replace(/\.md$/, '').replace(/(^|\/)index$/, '$1')}`,
          ...(items.length ? { collapsed: true, items } : {})
        };
      });
  }
  return children(null);
}
