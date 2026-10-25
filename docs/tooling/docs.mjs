#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
import { cp, mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import os from 'node:os';
import { apiNavigation } from './navigation.mjs';
import { files, validateLinks } from './links.mjs';

const tooling = path.dirname(fileURLToPath(import.meta.url));
const shared = path.dirname(tooling);
const root = await realpath(process.cwd());

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

async function repositoryPath(value, name, directory = root) {
  requireValue(typeof value === 'string' && value.length && !path.isAbsolute(value), `${name} must be repository-root-relative.`);
  const resolved = await realpath(path.resolve(directory, value));
  requireValue(resolved.startsWith(`${directory}${path.sep}`), `${name} must remain inside ${directory}.`);
  return resolved;
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', ...options });
    child.on('error', reject);
    child.on('exit', (code, signal) => code === 0 ? resolve() : reject(new Error(`${command} failed (${signal ?? code}).`)));
  });
}

function navigation(items, name) {
  requireValue(Array.isArray(items) && items.length, `${name} must be a nonempty array.`);
  for (const item of items) {
    requireValue(typeof item.text === 'string' && item.text.length, `${name}: each item needs text.`);
    requireValue(typeof item.link === 'string' && item.link.startsWith('/') && !item.link.startsWith('//'), `${name}: each link must start with /.`);
    if (item.items) navigation(item.items, name);
  }
  return items;
}

async function prepare(config, options, stage) {
  requireValue(config.schemaVersion === 1, 'site.json must use schemaVersion 1.');
  requireValue(typeof config.title === 'string' && config.title.length, 'site.json needs a title.');
  requireValue(/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(config.repository), 'repository must be an HTTPS GitHub repository URL.');
  requireValue(typeof config.base === 'string' && /^\/?[\w/-]*\/?$/.test(config.base) && !config.base.includes('..'), 'base must be a site path such as /Example/.');
  const base = `/${config.base.split('/').filter(Boolean).join('/')}/`.replace('//', '/');
  const content = await repositoryPath(config.contentDirectory ?? 'docs/content', 'contentDirectory');
  const guide = navigation(config.guide, 'guide');
  // Validate the entire source tree before copying; symlinks could otherwise escape it.
  await files(content);
  const source = path.join(stage, 'content');
  await cp(content, source, { recursive: true });
  requireValue(!(await readdir(source)).includes('.vitepress'), 'Keep VitePress configuration in the shared toolchain.');
  let api = [];
  if (config.api) {
    requireValue(config.api.generator === 'sesharp', 'The supported API generator is sesharp.');
    requireValue(Array.isArray(config.api.assemblies) && config.api.assemblies.length, 'api.assemblies must contain Release assembly paths.');
    requireValue(/^[a-f\d]{40}$/i.test(options['source-ref'] ?? ''), '--source-ref must be the full API source commit SHA.');
    const apiDirectory = options['api-directory'] === '.' ? root : await repositoryPath(options['api-directory'], 'api-directory');
    const assemblies = await Promise.all(config.api.assemblies.map(value => repositoryPath(value, 'api.assemblies', apiDirectory)));
    const generated = path.join(stage, 'generated');
    await run('sesharp', [...assemblies, '--output', generated, '--repository', config.repository, '--source-ref', options['source-ref']]);
    const manifest = JSON.parse(await readFile(path.join(generated, 'navigation.json'), 'utf8'));
    api = await apiNavigation(manifest, file => readFile(path.join(generated, file), 'utf8'));
    const destination = path.join(source, 'api');
    await mkdir(destination, { recursive: true });
    for (const file of await files(generated)) {
      const relative = path.relative(generated, file);
      if (!relative.endsWith('.md')) continue;
      const target = path.join(destination, relative);
      requireValue(!await readFile(target).then(() => true, () => false), `Generated API would overwrite handwritten content: api/${relative}`);
      await mkdir(path.dirname(target), { recursive: true });
      await cp(file, target);
    }
  }
  const introductions = config.api?.introductions ? navigation(config.api.introductions, 'api.introductions') : [];
  const theme = {
    nav: config.nav ? navigation(config.nav, 'nav') : [{ text: 'Guide', link: guide[0].link }, ...(api.length ? [{ text: 'API', link: '/api/' }] : [])],
    sidebar: { '/api/': [...introductions, { text: 'API', link: '/api/', items: api }], '/': guide },
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: config.repository }],
    outline: [2, 3]
  };
  const settings = {
    lang: 'en-GB', title: `${config.title} ${options.version === 'dev' ? '(development)' : `v${options.version}`}`,
    description: config.description ?? '', head: config.head ?? [], base, srcDir: source,
    outDir: path.join(stage, 'dist'), cacheDir: path.join(stage, 'cache'),
    ignoreDeadLinks: false, metaChunk: true, themeConfig: theme
  };
  if (config.publicDirectory) {
    const assets = await repositoryPath(config.publicDirectory, 'publicDirectory');
    await files(assets);
    const publicDirectory = path.join(stage, 'public');
    await cp(assets, publicDirectory, { recursive: true });
    settings.vite = { publicDir: publicDirectory };
  }
  await mkdir(path.join(stage, '.vitepress', 'theme'), { recursive: true });
  await symlink(path.join(tooling, 'node_modules'), path.join(stage, 'node_modules'));
  await writeFile(path.join(stage, '.vitepress', 'config.mjs'),
    `import { lazySidebar } from ${JSON.stringify(path.join(tooling, 'sidebar.mjs'))};\n` +
    `const config = ${JSON.stringify(settings, null, 2)};\n` +
    'config.vite = { ...config.vite, plugins: [lazySidebar()] };\nexport default config;\n');
  await cp(path.join(shared, 'theme'), path.join(stage, '.vitepress', 'theme'), { recursive: true });
  await lint(source, config, stage);
  return { base, source, content };
}

async function lint(source, config, stage) {
  const styles = path.join(stage, 'styles');
  await cp(path.join(shared, 'vale', 'styles'), styles, { recursive: true });
  let ini = await readFile(path.join(shared, 'vale', '.vale.ini'), 'utf8');
  ini = ini.replace('StylesPath = styles', `StylesPath = ${styles}`);
  if (config.vocabularyDirectory) {
    const vocabulary = await repositoryPath(config.vocabularyDirectory, 'vocabularyDirectory');
    await cp(vocabulary, path.join(styles, 'config', 'vocabularies', 'Project'), { recursive: true });
    ini = ini.replace('Vocab = Shared', 'Vocab = Shared, Project');
  }
  const file = path.join(stage, '.vale.ini');
  await writeFile(file, ini);
  await run('vale', ['--config', file, '--minAlertLevel=error', source]);
}

let stage;
try {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      config: { type: 'string', default: 'docs/site.json' },
      version: { type: 'string', default: 'dev' },
      output: { type: 'string', default: 'artifacts/docs' },
      'source-ref': { type: 'string' },
      'api-directory': { type: 'string', default: '.' },
      port: { type: 'string', default: '5173' }
    }
  });
  const command = positionals[0];
  requireValue(positionals.length === 1 && ['build', 'serve'].includes(command), 'Usage: docs build|serve [--config docs/site.json] [--version 1.2.3] [--source-ref SHA] [--output artifacts/docs]');
  requireValue(values.version === 'dev' || /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(values.version), 'version must be dev or a stable version without a v prefix.');
  requireValue(/^\d+$/.test(values.port) && Number(values.port) > 0 && Number(values.port) < 65536, 'port must be between 1 and 65535.');
  const config = JSON.parse(await readFile(await repositoryPath(values.config, 'config'), 'utf8'));
  stage = await mkdtemp(path.join(os.tmpdir(), 'shared-docs-'));
  const prepared = await prepare(config, values, stage);
  const vitepress = path.join(tooling, 'node_modules', 'vitepress', 'bin', 'vitepress.js');
  if (command === 'serve') {
    console.log('Preview uses a prepared copy; restart after editing source files.');
    await run(process.execPath, [vitepress, 'dev', stage, '--host', '0.0.0.0', '--port', values.port, '--strictPort']);
  } else {
    await run(process.execPath, [vitepress, 'build', stage]);
    await validateLinks(path.join(stage, 'dist'), prepared.base);
    const output = path.resolve(root, values.output);
    requireValue(output.startsWith(`${root}${path.sep}`) && !output.startsWith(`${prepared.content}${path.sep}`) && output !== prepared.content, 'output must be inside the repository and outside contentDirectory.');
    await mkdir(output, { recursive: true });
    requireValue((await readdir(output)).length === 0, `Output must be empty: ${output}`);
    await cp(path.join(stage, 'dist'), output, { recursive: true });
    await writeFile(path.join(output, 'build-info.json'), JSON.stringify({ version: values.version, sourceRef: values['source-ref'] ?? null, base: prepared.base }, null, 2) + '\n');
    console.log(`Documentation: ${output}`);
  }
} catch (error) {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
} finally {
  if (stage) await rm(stage, { recursive: true, force: true });
}
