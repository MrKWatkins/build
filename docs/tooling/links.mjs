// SPDX-License-Identifier: GPL-3.0-only
import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { parse } from 'parse5';

export async function files(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`Symbolic links are not supported in documentation: ${file}`);
    if (entry.isDirectory()) result.push(...await files(file));
    else result.push(file);
  }
  return result;
}

export async function validateLinks(directory, base) {
  const documents = new Map();
  for (const file of await files(directory)) {
    if (!file.endsWith('.html')) continue;
    const document = { ids: new Set(), links: [] };
    function visit(node) {
      const attributes = Object.fromEntries((node.attrs ?? []).map(a => [a.name, a.value]));
      if (attributes.id) document.ids.add(attributes.id);
      for (const attribute of ['href', 'src', 'poster']) {
        if (attributes[attribute]) document.links.push(attributes[attribute]);
      }
      if (attributes.srcset) {
        document.links.push(...attributes.srcset.split(',').map(item => item.trim().split(/\s+/)[0]));
      }
      for (const child of node.childNodes ?? []) visit(child);
    }
    visit(parse(await readFile(file, 'utf8')));
    documents.set(file, document);
  }
  const errors = new Set();
  for (const [file, document] of documents) {
    const relative = path.relative(directory, file).split(path.sep).join('/');
    for (const link of document.links) {
      // External URLs (including protocol-relative URLs) are outside this offline check.
      if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(link)) continue;
      const url = new URL(link, `https://docs.invalid${base}${relative}`);
      if (!url.pathname.startsWith(base)) {
        errors.add(`${relative}: ${link} escapes site base ${base}`);
        continue;
      }
      let target = path.resolve(directory, decodeURIComponent(url.pathname.slice(base.length)));
      if (target !== directory && !target.startsWith(`${directory}${path.sep}`)) {
        errors.add(`${relative}: invalid local URL ${link}`);
        continue;
      }
      if (url.pathname.endsWith('/')) target = path.join(target, 'index.html');
      else if (!(await stat(target).catch(() => null)) && !path.extname(target)) target += '.html';
      if (!(await stat(target).catch(() => null))?.isFile()) {
        errors.add(`${relative}: missing target ${link}`);
      } else if (url.hash && documents.has(target) &&
          !documents.get(target).ids.has(decodeURIComponent(url.hash.slice(1)))) {
        errors.add(`${relative}: missing anchor ${link}`);
      }
    }
  }
  if (errors.size) throw new Error(`Site link validation failed:\n${[...errors].join('\n')}`);
  console.log(`Validated local links, assets and anchors in ${documents.size} HTML pages.`);
}
