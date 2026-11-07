import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';

const engine = process.env.SHARED_PIN_ENGINE_DIR;
assert.ok(engine, 'SHARED_PIN_ENGINE_DIR must name the locked native engine install');
const mod = async p => import(pathToFileURL(path.join(engine, 'node_modules/renovate/dist', p)));
const { extractPackageFile } = await mod('modules/manager/custom/regex/index.js');
const { doAutoReplace } = await mod('workers/repository/update/branch/auto-replace.js');
const { validateConfig } = await mod('config/validation.js');
const { GlobalConfig } = await mod('config/global.js');
const { setCustomEnv } = await mod('util/env.js');
const { createSimpleGit } = await mod('util/git/index.js');
const root = path.resolve(import.meta.dirname, '..');
const adapter = path.join(root, 'runner/git_transport.py');
const git = (cwd, ...args) => execFileSync('/usr/bin/git', args, { cwd, encoding: 'utf8', env: { ...process.env, GIT_LFS_SKIP_SMUDGE: '1' } }).trim();

const oldSha = 'a'.repeat(40), newSha = 'b'.repeat(40);

test('locked native regex manager extracts and replaces uses and checkout ref, including reversed fields', async () => {
  const fixture = mkdtempSync(path.join(tmpdir(), 'pin-update-'));
  GlobalConfig.set({ localDir: fixture });
  for (const content of [
    `steps:\n  - uses: SylphxAI/.github/.github/actions/pr-review@${oldSha} # main\n`,
    `steps:\n  - uses: actions/checkout@v4\n    with:\n      repository: SylphxAI/.github\n      ref: '${oldSha}' # main\n      path: review-shared\n`,
    `steps:\n  - uses: actions/checkout@v4\n    with:\n      ref: "${oldSha}" # main\n      repository: SylphxAI/.github\n`,
  ]) {
    const escaped = content.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const config = { customType: 'regex', managerFilePatterns: ['/.github/workflows/a.yml/'],
      matchStrings: [escaped.replace(oldSha, '(?<currentDigest>[a-f0-9]{40})')],
      datasourceTemplate: 'github-digest', depNameTemplate: 'SylphxAI/.github',
      versioningTemplate: 'exact', currentValueTemplate: 'main' };
    const extracted = extractPackageFile(content, '.github/workflows/a.yml', config);
    assert.equal(extracted.deps.length, 1);
    assert.equal(extracted.deps[0].currentDigest, oldSha);
    const updated = await doAutoReplace({ ...config, ...extracted.deps[0], manager: 'regex',
      packageFile: '.github/workflows/a.yml', depIndex: 0, newDigest: newSha, newValue: 'main' }, content, false);
    assert.equal(updated, content.replace(oldSha, newSha));
  }
  rmSync(fixture, { recursive: true, force: true });
});

test('production native configuration parses without invalid options', async () => {
  const config = JSON.parse(readFileSync(path.join(root, 'runner/config.json')));
  const result = await validateConfig('global', config);
  assert.deepEqual(result.errors, []);
  assert.equal(config.gitNoVerify.length, 0);
  assert.equal(config.pruneStaleBranches, false);
});

test('native Renovate transport creates a new branch with plain push then refuses an existing branch update', async () => {
  const work = mkdtempSync(path.join(tmpdir(), 'pin-native-'));
  try {
    const repo = path.join(work, 'repo'), remote = path.join(work, 'remote.git');
    mkdirSync(repo); git(work, 'init', '--bare', remote); git(repo, 'init', '-b', 'main');
    git(repo, 'config', 'user.name', 'Kyle Tse'); git(repo, 'config', 'user.email', 'hi@kylet.se');
    writeFileSync(path.join(repo, 'file'), 'one'); git(repo, 'add', '.'); git(repo, 'commit', '-m', 'one');
    git(repo, 'remote', 'add', 'origin', remote); git(repo, 'push', 'origin', 'main');
    const branch = 'renovate/shared-ci-week-2026-46';
    git(repo, 'checkout', '-b', branch);
    const claim = path.join(work, 'push-claim');
    const env = { SHARED_PINS_BRANCH: branch, SHARED_PINS_PUSH_CLAIM: claim, SHARED_PINS_TEST_TRANSPORT: '1', SHARED_PINS_TEST_TRACE: path.join(work, 'git-trace.jsonl') };
    setCustomEnv(env);
    const native = createSimpleGit({ config: { baseDir: repo, binary: adapter } });
    await native.push('origin', `${branch}:${branch}`, { '--force-with-lease': null, '-u': null });
    const initial = git(work, '--git-dir', remote, 'rev-parse', `refs/heads/${branch}`);
    assert.equal(initial, git(repo, 'rev-parse', branch));
    rmSync(claim);
    writeFileSync(path.join(repo, 'file'), 'two'); git(repo, 'add', '.'); git(repo, 'commit', '-m', 'two');
    await assert.rejects(native.push('origin', `${branch}:${branch}`, { '--force-with-lease': null, '-u': null }), /unsafe or uncertain/);
    assert.equal(git(work, '--git-dir', remote, 'rev-parse', `refs/heads/${branch}`), initial);
    assert.notEqual(git(repo, 'rev-parse', branch), initial);
    assert.ok(readFileSync(claim, 'utf8').includes(branch));
    const trace = readFileSync(path.join(work, 'git-trace.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    const pushes = trace.filter(row => row[0] === '/usr/bin/git' && row.includes('push'));
    assert.equal(pushes.length, 1);
    assert.ok(!pushes[0].some(arg => arg.startsWith('--force') || arg === '-f' || arg.startsWith('+')));
  } finally { rmSync(work, { recursive: true, force: true }); }
});

test('synthetic credential stays out of native Git argv and persistent remote configuration', async () => {
  const secret = 'synthetic-shared-ci-credential-not-a-real-token';
  const { getGitAuthenticatedEnvironmentVariables } = await mod('util/git/auth.js');
  const url = 'git@github.com:SylphxAI/renovate-config.git';
  const env = getGitAuthenticatedEnvironmentVariables({}, url, { hostType: 'github', token: secret, matchHost: 'github.com' });
  assert.ok(JSON.stringify(env).includes(secret), 'credential is confined to environment');
  assert.ok(!JSON.stringify(['clone', url, '.']).includes(secret));
  assert.ok(Object.entries(env).some(([k, v]) => k.startsWith('GIT_CONFIG_KEY_') && v.includes(secret)));
  const work = mkdtempSync(path.join(tmpdir(), 'pin-secret-'));
  try {
    git(work, 'init'); git(work, 'remote', 'add', 'origin', url);
    const r = spawnSync(adapter, ['remote', '-v'], { cwd: work, env: { ...process.env, ...env }, encoding: 'utf8' });
    assert.equal(r.status, 0); assert.ok(!r.stdout.includes(secret)); assert.ok(!r.stderr.includes(secret));
    assert.ok(!readFileSync(path.join(work, '.git/config'), 'utf8').includes(secret));
  } finally { rmSync(work, { recursive: true, force: true }); }
});
