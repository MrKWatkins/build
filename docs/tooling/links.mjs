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
  const strings = new Map();
  function intern(value) {
    if (!strings.has(value)) {
      // Parser slices can retain an entire HTML page. Copy each distinct value once.
      const copy = Buffer.from(value).toString();
      strings.set(copy, copy);
    }
    return strings.get(value);
  }
  for (const file of await files(directory)) {
    if (!file.endsWith('.html')) continue;
    const document = { ids: new Set(), links: new Set() };
    function visit(node) {
      const attributes = Object.fromEntries((node.attrs ?? []).map(a => [a.name, a.value]));
      if (attributes.id) document.ids.add(intern(attributes.id));
      for (const attribute of ['href', 'src', 'poster']) {
        if (attributes[attribute]) document.links.add(intern(attributes[attribute]));
      }
      if (attributes.srcset) {
        for (const item of attributes.srcset.split(',')) document.links.add(intern(item.trim().split(/\s+/)[0]));
      }
      for (const child of node.childNodes ?? []) visit(child);
    }
    visit(parse(await readFile(file, 'utf8')));
    documents.set(file, document);
  }
  const errors = new Set();
  // Every page repeats the navigation links. The built site is immutable here.
  const statuses = new Map();
  async function status(file) {
    if (!statuses.has(file)) statuses.set(file, await stat(file).catch(() => null));
    return statuses.get(file);
  }
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
      else if (!(await status(target)) && !path.extname(target)) target += '.html';
      if (!(await status(target))?.isFile()) {
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
