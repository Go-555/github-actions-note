import { promises as fs } from 'node:fs';
import { basename, extname, join, resolve } from 'node:path';
import matter from 'gray-matter';

const workspace = process.env.GITHUB_WORKSPACE || process.cwd();
const sourceDir = resolve(workspace, process.env.SOURCE_DIR || 'sources');
const processedDir = resolve(sourceDir, process.env.PROCESSED_DIR || 'processed');
const queueDir = resolve(workspace, process.env.QUEUE_DIR || 'articles-queue');
const defaultLimit = Number.parseInt(process.env.GENERATE_LIMIT || '1', 10);
const limit = Number.isFinite(defaultLimit) && defaultLimit > 0 ? defaultLimit : 1;

async function ensureDirectories() {
  for (const dir of [sourceDir, processedDir, queueDir]) {
    await fs.mkdir(dir, { recursive: true });
  }
}

function slugify(input) {
  return input
    .toString()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-');
}

function coerceTags(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map((v) => String(v)).filter(Boolean);
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
  }
  return [String(value)];
}

async function pickSources() {
  let entries;
  try {
    entries = await fs.readdir(sourceDir, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }

  const files = entries
    .filter((dirent) => {
      if (!dirent.isFile()) return false;
      if (extname(dirent.name).toLowerCase() !== '.md') return false;
      if (dirent.name.startsWith('_')) return false;
      if (dirent.name.toLowerCase() === 'readme.md') return false;
      return true;
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  return files.slice(0, limit).map((file) => file.name);
}

async function generateArticleFromSource(filename) {
  const sourcePath = join(sourceDir, filename);
  const raw = await fs.readFile(sourcePath, 'utf8');
  const parsed = matter(raw);
  const now = new Date();

  let title = parsed.data?.title;
  if (!title) {
    const firstLine = parsed.content.split('\n').find((line) => line.trim().length > 0) || '';
    title = firstLine.replace(/^#+\s*/, '').trim() || basename(filename, '.md');
  }

  const tags = coerceTags(parsed.data?.tags);
  const isPublic = Boolean(parsed.data?.is_public);
  const slugBase = slugify(parsed.data?.slug || title);
  const datePrefix = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  let targetSlug = `${datePrefix}-${slugBase}`;
  if (!targetSlug) {
    targetSlug = `${datePrefix}-${slugify(basename(filename, '.md'))}`;
  }

  let targetPath = join(queueDir, `${targetSlug}.md`);
  let dedupe = 1;
  while (true) {
    try {
      await fs.access(targetPath);
      dedupe += 1;
      targetPath = join(queueDir, `${targetSlug}-${dedupe}.md`);
    } catch (error) {
      if (error.code === 'ENOENT') break;
      throw error;
    }
  }

  const frontMatter = {
    title,
    tags,
    is_public: isPublic,
    source: filename,
    queued_at: now.toISOString(),
  };

  if (parsed.data?.cta) {
    frontMatter.cta = parsed.data.cta;
  }
  if (parsed.data?.summary) {
    frontMatter.summary = parsed.data.summary;
  }

  const body = parsed.content.trim() ? `${parsed.content.trim()}\n` : '';
  const output = matter.stringify(body, frontMatter, { lineWidth: 120 });
  await fs.writeFile(targetPath, output, 'utf8');

  const processedPath = join(processedDir, filename);
  await fs.mkdir(processedDir, { recursive: true });
  await fs.rename(sourcePath, processedPath);

  return { filename, targetPath };
}

async function main() {
  await ensureDirectories();
  const targets = await pickSources();
  if (targets.length === 0) {
    console.log('No source markdown files found. Nothing to queue.');
    return;
  }

  const results = [];
  for (const filename of targets) {
    const result = await generateArticleFromSource(filename);
    results.push(result);
  }

  console.log('Queued articles:');
  for (const result of results) {
    console.log(`- ${result.filename} -> ${result.targetPath}`);
  }
}

main().catch((error) => {
  console.error('Generation pipeline failed:', error);
  process.exitCode = 1;
});
