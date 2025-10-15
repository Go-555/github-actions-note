import fs from 'node:fs';
import path from 'node:path';

const [, , markdownPathArg, repoOwner = process.env.GITHUB_REPOSITORY || '', branch = process.env.GITHUB_REF_NAME || 'main'] = process.argv;

if (!markdownPathArg) {
  console.error('usage: node path_rewriter.mjs <markdown_path> [repo] [branch]');
  process.exit(1);
}

const markdownPath = path.resolve(markdownPathArg);
const repo = repoOwner;
const rawBase = `https://raw.githubusercontent.com/${repo}/${branch}`;

let content;
try {
  content = fs.readFileSync(markdownPath, 'utf8');
} catch (error) {
  console.error('Failed to read markdown file:', error);
  process.exit(1);
}

const rewritten = content.replace(/\(\.\/assets\//g, `(${rawBase}/assets/`);
fs.writeFileSync(markdownPath, rewritten, 'utf8');
console.log('Rewrote asset paths for', markdownPath);
