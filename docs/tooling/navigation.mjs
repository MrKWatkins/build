// SPDX-License-Identifier: GPL-3.0-only
const sections = [
  ['Constructors', 'Constructor'],
  ['Fields', 'Field'],
  ['Properties', 'Property'],
  ['Methods', 'Method'],
  ['Operators', 'Operator'],
  ['Events', 'Event']
];
const escapeText = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const link = entry => `/api/${entry.path.replace(/\.md$/, '').replace(/(^|\/)index$/, '$1')}`;
const compare = (a, b) => a.title < b.title ? -1 : a.title > b.title ? 1 : 0;

export async function apiNavigation(manifest, readPage) {
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
  const byParent = new Map();
  for (const entry of entries.values()) {
    // C# extension blocks expose compiler-generated containers alongside the real static methods.
    if (entry.path.split('/').some(segment => /^<[GM]>\$[0-9a-f]{32}$/i.test(segment))) continue;
    if (!byParent.has(entry.parent)) byParent.set(entry.parent, []);
    byParent.get(entry.parent).push(entry);
  }
  const categories = new Map();
  await Promise.all([...byParent.values()].flat().filter(entry => entry.kind === 'member').map(async entry => {
    const page = await readPage(entry.path);
    // Generated headings identify overloaded properties and methods alike; IDs alone cannot distinguish them.
    const heading = /^# (.+)\r?$/m.exec(page)?.[1];
    const section = sections.find(([, kind]) => new RegExp(` ${kind}s?$`).test(heading ?? ''));
    if (!section) throw new Error(`Cannot determine member category: ${entry.path}`);
    categories.set(entry.id, section[0]);
  }));
  function children(parent) {
    return (byParent.get(parent) ?? [])
      .filter(entry => entry.kind !== 'member')
      .sort(compare)
      .map(entry => {
        const members = byParent.get(entry.id) ?? [];
        const groups = sections.flatMap(([category]) => {
          const items = members.filter(member => categories.get(member.id) === category).sort(compare).map(member => ({
            text: escapeText(category === 'Constructors' ? entry.title : member.title),
            link: link(member)
          }));
          return items.length ? [{ text: category, link: `${link(entry)}#${category.toLowerCase()}`, collapsed: true, items }] : [];
        });
        const items = [...groups, ...children(entry.id)];
        return {
          text: escapeText(entry.title),
          link: link(entry),
          ...(items.length ? { collapsed: entry.kind !== 'namespace', items } : {})
        };
      });
  }
  return children(null);
}
