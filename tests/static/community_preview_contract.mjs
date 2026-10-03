import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const chromium = process.env.CHROMIUM_PATH ?? ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome'].find(existsSync);
const artistId = 'f22942a1-6f70-4f48-866e-238cb2308fbd';
const communityId = 'community-fixture';
const model = {
  role: 'inferred_emergent_music_communities', public_export_authorized: false,
  communities: [{
    id: communityId, label: 'ambient / electronic / experimental', level: 'broad',
    parent_id: null, child_ids: [], artist_count: 1, distinct_profile_count: 1,
    label_origin: 'derived_feature_descriptors', descriptors: [{
      feature_id: 'artist_genre:ambient', namespace: 'artist_genre', value: 'ambient', support_count: 1,
    }, { feature_id: 'artist_tag:drone', namespace: 'artist_tag', value: 'drone', support_count: 3 }], artist_ids: [artistId], x: 0.5, y: 0.5,
  }],
  artist_profiles: { [artistId]: { name: 'Fixture Artist', genre_ids: ['source-genre'] } },
};
const source = {
  scope: 'local_research_only', public_export_authorized: false, artists: {},
  genres: [{ id: 'source-genre', name: 'Direct folk observation' }],
};
const assignments = { artists: { [artistId]: { state: 'assigned', memberships: [{
  community_id: communityId, role: 'inferred_community_membership', score: 0.42,
}] } } };
const proposal = {
  feature_id: 'music:drone', value: 'drone', role: 'inferred_feature_proposal',
  native_fact: false, score_calibrated: false, score: 0.25,
  training_source_sha256: 'a'.repeat(64), training_input_sha256: 'a'.repeat(64), source_model_sha256: 'b'.repeat(64), training_target_artist_support: 3,
  contributing_cue_count: 1, explanation_cue_limit: 5,
  evidence: [{ cue_role: 'music', value: 'ambient', query_evidence_refs: ['fixture-source:ambient'],
    training_joint_artist_support: 2, training_cue_artist_support: 4, score_contribution: 0.25 }],
};
const suggestedAssignments = { artists: { [artistId]: {
  ...assignments.artists[artistId], observed_music_values: ['ambient'], feature_proposals: [
    proposal,
    { ...proposal, feature_id: 'music:false source claim', value: 'false source claim', role: 'direct_source_observation' },
    { ...proposal, feature_id: 'music:false native fact', value: 'false native fact', native_fact: true },
    { ...proposal, feature_id: 'music:ambient', value: 'ambient' },
    { ...proposal, feature_id: 'music:Direct folk observation', value: 'Direct folk observation' },
  ],
} } };

async function capture(url) {
  const profile = await mkdtemp(join(tmpdir(), 'opennoise-community-contract-'));
  const child = spawn(chromium, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  let socket, stderr = '';
  child.stderr.on('data', data => { stderr = (stderr + data).slice(-5000); });
  try {
    const endpoint = await new Promise((resolve, reject) => {
      const cleanup = () => { clearTimeout(timeout); child.off('error', onError); child.off('exit', onExit); child.stderr.off('data', onData); };
      const onError = error => { cleanup(); reject(error); };
      const onExit = (code, signal) => { cleanup(); reject(new Error(`Chromium exited before exposing DevTools (code=${code}, signal=${signal})`)); };
      const onData = () => {
        const match = stderr.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)\//);
        if (match) { cleanup(); resolve(`http://127.0.0.1:${match[1]}`); }
      };
      const timeout = setTimeout(() => { cleanup(); reject(new Error('Chromium did not expose DevTools')); }, 10_000);
      child.once('error', onError); child.once('exit', onExit); child.stderr.on('data', onData);
    });
    const target = await fetch(`${endpoint}/json/new?about:blank`, { method: 'PUT' }).then(response => response.json());
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
    let sequence = 0;
    const pending = new Map();
    socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data), callback = pending.get(message.id);
      if (callback) { pending.delete(message.id); callback(message); }
    });
    const command = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, message => message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result));
      socket.send(JSON.stringify({ id, method, params }));
    });
    await command('Page.navigate', { url });
    for (let attempt = 0; attempt < 200; attempt++) {
      const result = await command('Runtime.evaluate', { expression: "document.documentElement.dataset.communityPreviewReady", returnByValue: true });
      if (result.result?.value === 'true') break;
      await new Promise(resolve => setTimeout(resolve, 25));
      if (attempt === 199) throw new Error('Community preview did not become ready');
    }
    const result = await command('Runtime.evaluate', {
      expression: `(() => {
        document.querySelector('[name=search-scope][value=artists]').click();
        const search = document.querySelector('#model-search'); search.value = 'Fixture Artist';
        search.dispatchEvent(new Event('input'));
        return new Promise(resolve => {
          const poll = () => {
            const row = document.querySelector('#search-results [data-artist-id]');
            if (!row) { setTimeout(poll, 10); return; }
            row.click();
            const ready = () => {
              const memberships = document.querySelector('.membership-list');
              if (!memberships || document.querySelector('#detail').getAttribute('aria-busy') === 'true') { setTimeout(ready, 10); return; }
              document.querySelector('#about-toggle').click();
              resolve({
                modelRole: memberships.dataset.evidenceRole,
                modelLabel: document.querySelector('.membership-button')?.textContent,
                sourceRole: document.querySelector('.source-list')?.dataset.evidenceRole,
                sourceLabel: document.querySelector('.source-button')?.textContent,
                abstention: document.querySelector('[data-evidence-role=model_abstention][data-level=micro]')?.textContent,
                aboutVisible: !document.querySelector('#about').hidden,
                inferredHeading: [...document.querySelectorAll('#detail h3')].find(node => node.textContent === 'Overlapping model memberships')?.textContent,
                directRole: [...document.querySelectorAll('#detail .role-badge.source')].at(-1)?.textContent,
                suggestionRole: document.querySelector('.style-suggestions')?.dataset.evidenceRole,
                suggestionValues: [...document.querySelectorAll('.suggestion-card')].map(node => node.dataset.featureValue),
                suggestionNativeFacts: [...document.querySelectorAll('.suggestion-card')].map(node => node.dataset.nativeFact),
                suggestionEvidence: document.querySelector('.suggestion-evidence')?.textContent,
                rejectedSuggestionNotice: document.querySelector('.suggestion-notice')?.textContent,
                suggestionMeaning: document.querySelector('.style-suggestions>.section-description')?.textContent,
              });
            };
            ready();
          };
          poll();
        });
      })()`, awaitPromise: true, returnByValue: true,
    });
    const captured = result.result.value;
    if (captured.suggestionValues.length) {
      const exploration = await command('Runtime.evaluate', {
        expression: `(() => {
          document.querySelector('.suggestion-explore').click();
          return {query: document.querySelector('#model-search').value,
            scope: document.querySelector('[name=search-scope]:checked').value,
            matchingCommunities: document.querySelectorAll('#search-results [data-community-id]').length,
            sourceCount: document.querySelectorAll('.source-button').length,
            membershipCount: document.querySelectorAll('.membership-button').length,
            artistRetained: location.hash.includes('artist=${artistId}')};
        })()`, returnByValue: true,
      });
      captured.exploration = exploration.result.value;
    }
    return captured;
  } catch (error) {
    throw new Error(`${error.message}; browser=${chromium}; exit=${child.exitCode}; signal=${child.signalCode}; stderr(last 5000 chars):\n${stderr}`, { cause: error });
  } finally {
    socket?.close(); child.kill('SIGKILL');
    await new Promise(resolve => child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('close', resolve));
    await import('node:fs/promises').then(({ rm }) => rm(profile, { recursive: true, force: true }));
  }
}

async function preview(records, inspect) {
  const page = await readFile(new URL('../../src/opennoise/static/community-preview.html', import.meta.url), 'utf8');
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    if (path === '/' || path === '/index.html') { response.setHeader('Content-Type', 'text/html'); response.end(page); }
    else if (path === '/listening-list.mjs') { response.setHeader('Content-Type', 'text/javascript'); response.end(await readFile(new URL('../../src/opennoise/static/listening-list.mjs', import.meta.url))); }
    else if (path === '/community-preview.js') { response.setHeader('Content-Type', 'text/javascript'); response.end(await readFile(new URL('../../src/opennoise/static/community-preview.js', import.meta.url))); }
    else if (path === '/community-preview.css') { response.setHeader('Content-Type', 'text/css'); response.end(await readFile(new URL('../../src/opennoise/static/community-preview.css', import.meta.url))); }
    else if (path === '/community-data.json') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(model)); }
    else if (path === '/data.json') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(source)); }
    else if (path === '/artist-search.json') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ artists: [[artistId, 'Fixture Artist']] })); }
    else if (path === `/community-artists/${artistId.slice(0, 3)}.json`) { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(records)); }
    else { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const result = await capture(`http://127.0.0.1:${server.address().port}/`);
    await inspect(result);
  } finally { await new Promise(resolve => server.close(resolve)); }
}

test('artist view keeps inferred memberships distinct from direct source observations', { skip: !chromium, timeout: 60_000 }, async () => {
  await preview(assignments, result => {
    assert.equal(result.modelRole, 'inferred_community_membership');
    assert.match(result.modelLabel, /Model score 0\.420/);
    assert.equal(result.sourceRole, 'direct_source_observation');
    assert.equal(result.sourceLabel, 'Direct folk observation');
    assert.match(result.abstention, /No supported micro assignment/);
    assert.equal(result.aboutVisible, true);
    assert.equal(result.inferredHeading, 'Overlapping model memberships');
    assert.match(result.directRole, /DIRECT/);
    assert.equal(result.suggestionRole, undefined, 'older snapshots omit the optional suggestion section');
  });
});

test('style suggestions reject native claims and observed values while preserving artist facts', { skip: !chromium, timeout: 60_000 }, async () => {
  await preview(suggestedAssignments, result => {
    assert.equal(result.suggestionRole, 'inferred_feature_proposal');
    assert.deepEqual(result.suggestionValues, ['drone']);
    assert.deepEqual(result.suggestionNativeFacts, ['false']);
    assert.match(result.suggestionEvidence, /2 training artists have both/);
    assert.match(result.suggestionEvidence, /4 have this cue/);
    assert.match(result.suggestionEvidence, /fixture-source:ambient/);
    assert.match(result.rejectedSuggestionNotice, /could not be verified/);
    assert.match(result.suggestionMeaning, /uncalibrated/);
    assert.match(result.suggestionMeaning, /add no source genre facts or community memberships/);
    assert.equal(result.sourceRole, 'direct_source_observation');
    assert.equal(result.modelRole, 'inferred_community_membership');
    assert.deepEqual(result.exploration, {query: 'drone', scope: 'communities', matchingCommunities: 1, sourceCount: 1, membershipCount: 1, artistRetained: true});
  });
});
