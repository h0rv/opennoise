import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.handlers={}; this.attributes={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute(name,value) { this.attributes[name]=value; }
  addEventListener(name,handler) { this.handlers[name]=handler; }
}
const walk = node => [node,...node.children.flatMap(walk)];
const source = await readFile(new URL('../../src/opennoise/static/fma-playable-neighbors.js',import.meta.url),'utf8');
const {renderPlayableNeighbors} = await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const digest='a'.repeat(64);
function fixture(t) {
  const original=globalThis.document; globalThis.document={createElement:tag=>new Element(tag)}; t.after(()=>{globalThis.document=original;});
  const rows=new Element('div'), calls=[];
  const manifest={revision:'fma-playable-descriptor-neighbors-v1',audio_manifest_sha256:digest,labels_used:false,fitted:false,musical_relevance_established:false,components:{2:1,3:2,4:3},rows:[{track_id:2,neighbor_ids:[4,3],reason:null},{track_id:3,neighbor_ids:[2],reason:null},{track_id:4,neighbor_ids:[2],reason:null}]};
  const options={id:2,config:{manifest_path:'playable-neighbors/manifest.json'},playback:{manifest_sha256:digest,tracks:[{track_id:2,artist_id:10},{track_id:3,artist_id:11},{track_id:4,artist_id:12}]},json:async()=>manifest,tracksFor:async ids=>ids.map(id=>[id,`Title ${id}`,id+8]),artistIndex:new Map([[10,[10,'Artist 2']],[11,[11,'Artist 3']],[12,[12,'Artist 4']]]),rows,current:()=>true,onPlay:(...args)=>calls.push(args)};
  return {manifest,options,rows,calls};
}

test('attached suggestions preserve order, artist identities and explicit individual/queue playback',async t=>{
  const {options,rows,calls}=fixture(t); await renderPlayableNeighbors(options);
  assert.equal(rows.children[0].dataset.evidenceRole,'attached_excerpt_descriptor_neighbors');
  const elements=walk(rows);
  assert.ok(elements.some(node=>node.textContent==='Suggested excerpts'));
  assert.ok(elements.some(node=>node.textContent?.includes('Musical similarity has not been validated')));
  assert.deepEqual(elements.filter(node=>node.className==='playable-neighbor-track').map(node=>node.href),['#track=4','#track=3']);
  assert.deepEqual(elements.filter(node=>node.tagName==='a'&&node.href.startsWith('#artist')).map(node=>node.href),['#artist=12','#artist=11']);
  assert.deepEqual(calls,[]);
  elements.find(node=>node.className==='playable-neighbor-play').handlers.click();
  assert.deepEqual(calls,[[4,undefined]]);
  elements.find(node=>node.className==='playable-neighbors-queue').handlers.click();
  assert.deepEqual(calls[1],[4,[4,3]]);
  calls[1][1].pop(); elements.find(node=>node.className==='playable-neighbors-queue').handlers.click();
  assert.deepEqual(calls[2],[4,[4,3]],'queue callback receives an independent copy');
  assert.equal(elements.filter(node=>node.tagName==='audio').length,0);
});

test('optional suggestions never load on absent pack or unattached query and preserve abstention',async t=>{
  const {options,rows,manifest}=fixture(t); let requests=0; const original=options.json; options.json=async()=>{requests++;return original();};
  await renderPlayableNeighbors({...options,config:null}); await renderPlayableNeighbors({...options,id:999});
  assert.equal(requests,0); assert.equal(rows.children.length,0);
  manifest.rows[0].neighbor_ids = [3];
  manifest.rows[2] = {track_id:4,neighbor_ids:[],reason:'outside_training_support'};
  await renderPlayableNeighbors({...options,id:4});
  assert.ok(walk(rows).some(node=>node.textContent?.startsWith('No suggested excerpts:')));
  assert.equal(walk(rows).filter(node=>node.tagName==='button').length,0);
});

test('binding, native pool, component exclusions, duplicate IDs and malformed schemas fail only this section',async t=>{
  const {options,manifest}=fixture(t);
  const mutations=[
    m=>{m.audio_manifest_sha256='b'.repeat(64);},
    m=>{m.rows[0].neighbor_ids=[3,3];},
    m=>{m.rows[0].neighbor_ids=[2];},
    m=>{m.rows[0].neighbor_ids=[99];},
    m=>{m.components[4]=1;},
    m=>{m.components[4]=null;},
    m=>{m.rows[1].track_id=2;},
    m=>{m.rows.pop();},
    m=>{m.rows[0].reason='missing_feature_row';},
    m=>{m.fitted=true;},
    m=>{m.rows[2]={track_id:4,neighbor_ids:[],reason:'outside_training_support'};},
    m=>{m.rows[2]={track_id:4,neighbor_ids:[],reason:'unknown_reason'};},
    m=>{m.rows[0].neighbor_ids=[];},
  ];
  for(const mutate of mutations) {
    const changed=structuredClone(manifest); mutate(changed); const rows=new Element('div'); rows.append(new Element('existing-content'));
    await renderPlayableNeighbors({...options,rows,json:async()=>changed});
    assert.equal(rows.children[0].tagName,'existing-content');
    assert.ok(walk(rows).some(node=>node.textContent==='Suggested excerpts are unavailable for this local export.'));
    assert.equal(walk(rows).filter(node=>node.tagName==='button').length,0);
  }
});

test('stale async loads and already-rendered stale controls cannot render or start playback',async t=>{
  const {options,rows,calls,manifest}=fixture(t); let current=true;
  await renderPlayableNeighbors({...options,current:()=>current,json:async()=>{current=false;return manifest;}});
  assert.equal(rows.children.length,0);
  current=true;
  await renderPlayableNeighbors({...options,current:()=>current,tracksFor:async()=>{current=false;return []}});
  assert.equal(rows.children.length,0);
  current=true; await renderPlayableNeighbors({...options,current:()=>current}); current=false;
  for(const button of walk(rows).filter(node=>node.tagName==='button'))button.handlers.click();
  assert.deepEqual(calls,[]);
});

test('metadata identity failure or unavailable local file never exposes play controls',async t=>{
  const {options}=fixture(t);
  for(const override of [{json:async()=>{throw Error('404');}},{tracksFor:async()=>[[4,'Wrong artist',999],[3,'Track',11]]},{config:{manifest_path:'https://other.invalid/manifest.json'}}]) {
    const rows=new Element('div');await renderPlayableNeighbors({...options,...override,rows});
    assert.ok(walk(rows).some(node=>node.textContent?.includes('unavailable')));
    assert.equal(walk(rows).filter(node=>node.tagName==='button').length,0);
  }
});
