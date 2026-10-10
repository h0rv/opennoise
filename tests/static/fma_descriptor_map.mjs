import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const walk=node=>[node,...node.children.flatMap(walk)];
class Node {
  constructor(tag){this.tagName=tag;this.children=[];this.style={};this.dataset={};this.handlers={};this.attributes={};this.clientWidth=360;this.context=new Proxy({},{get:(target,key)=>target[key]??(()=>{}),set:(target,key,value)=>{target[key]=value;return true;}});}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(event,handler){this.handlers[event]=handler;}
  getContext(){return this.context;}
  querySelector(tag){return walk(this).find(node=>node.tagName===tag);}
  focus(){this.focused=true;}
  scrollIntoView(){}
}
const source=await readFile(new URL('../../src/opennoise/static/fma-descriptor-map.js',import.meta.url),'utf8');
const {renderDescriptorMap}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
function setup(t){const document=globalThis.document,window=globalThis.window;globalThis.document={createElement:tag=>new Node(tag)};globalThis.window={devicePixelRatio:1};t.after(()=>{globalThis.document=document;globalThis.window=window;});return {rows:new Node('div'),heading:new Node('h1'),status:new Node('p')};}
const manifest={revision:'fma-descriptor-map-view-v1',genres:[{id:1,position:[1,2]},{id:2,position:null}],artist_shards:[]};
const genres=new Map([[1,{genre_id:1,title:'Known name'}],[2,{genre_id:2,title:'Unpositioned name'}]]);

test('descriptor map preserves missing-position genres and exact native links without audio or artist requests',async t=>{
  const nodes=setup(t),requests=[],states=[];
  await renderDescriptorMap({...nodes,state:{q:'Unpositioned'},config:{manifest_path:'coordinates.json'},json:async path=>{requests.push(path);return manifest;},genres,artists:[],current:()=>true,onStateChange:state=>states.push(state)});
  assert.deepEqual(requests,['coordinates.json']);assert.match(nodes.status.textContent,/1 matching genres · 0 with coordinates · 1 without/);
  const list=walk(nodes.rows).find(node=>node.className==='descriptor-list');
  assert.equal(list.children.length,1);assert.equal(walk(list).find(node=>node.tagName==='a').href,'#genre=2');
  walk(list).find(node=>node.tagName==='button').handlers.click();
  assert.equal(states.at(-1).selected,2);assert.match(walk(nodes.rows).find(node=>node.className==='descriptor-selection').children[1].textContent,/no supported coordinates/);
  assert.equal(walk(nodes.rows).filter(node=>node.tagName==='audio').length,0);
});

test('artist loading is bounded to four requests and full names/missing positions remain paginated',async t=>{
  const nodes=setup(t);let active=0,max=0;const calls=[];
  const artists=Array.from({length:57},(_,i)=>[i+1,'Native artist '+String(i+1).padStart(2,'0')]);
  const data={...manifest,artist_shards:Array.from({length:7},(_,i)=>'coordinates/'+i+'.json')};
  const json=async path=>{calls.push(path);if(path==='manifest.json')return data;active++;max=Math.max(max,active);await new Promise(resolve=>setTimeout(resolve,1));active--;const shard=Number(path.match(/(\d+)\.json/)[1]);return artists.filter((_,i)=>i%7===shard).map(([id])=>({id,position:id===57?null:[id/100,id/100]}));};
  await renderDescriptorMap({...nodes,state:{entity:'artists'},config:'manifest.json',json,genres,artists:[...artists,[999,'Missing source artist record']],current:()=>true});
  assert.equal(max,4);assert.equal(calls.length,8);assert.match(nodes.status.textContent,/57 matching artists · 56 with coordinates · 1 without/);
  const list=walk(nodes.rows).find(node=>node.className==='descriptor-list');assert.equal(list.children.length,50);
  const next=walk(nodes.rows).find(node=>node.tagName==='button' && node.textContent==='Next');next.handlers.click();assert.equal(list.children.length,7);
  assert.ok(walk(list).some(node=>node.textContent==='#57 · no coordinates'));
  assert.ok(walk(list).some(node=>node.href==='#artist=57'));
});

test('failed artist shard does not display partial coordinate results',async t=>{
  const nodes=setup(t);
  await renderDescriptorMap({...nodes,state:{entity:'artists'},config:'manifest.json',json:async path=>{if(path==='manifest.json')return {...manifest,artist_shards:['bad.json']};throw Error('missing');},genres,artists:[[1,'Native name']],current:()=>true});
  assert.match(nodes.status.textContent,/Coordinate data unavailable/);
  assert.equal(walk(nodes.rows).filter(node=>node.href).length,0);
});

test('resize redraws canvas geometry and route cleanup disconnects observer',async t=>{
  const nodes=setup(t),original=globalThis.ResizeObserver;let observer,cleanup;
  globalThis.ResizeObserver=class {constructor(callback){this.callback=callback;observer=this;}observe(target){this.target=target;}disconnect(){this.disconnected=true;}};
  t.after(()=>{globalThis.ResizeObserver=original;});
  await renderDescriptorMap({...nodes,state:{},config:'manifest.json',json:async()=>manifest,genres,artists:[],current:()=>true,registerCleanup:fn=>{cleanup=fn;}});
  const canvas=walk(nodes.rows).find(node=>node.tagName==='canvas');assert.equal(canvas.width,360);
  observer.target.clientWidth=800;observer.callback();assert.equal(canvas.width,800);assert.equal(canvas.height,430);
  cleanup();assert.equal(observer.disconnected,true);
});

test('map excerpts use exact direct tags and explicit play callbacks, without inherited tags or autoplay',async t=>{
  const nodes=setup(t),played=[];
  const playbackTracks=[{track_id:10,artist_id:7,genre_ids:[1]},{track_id:10,artist_id:7,genre_ids:[1]},{track_id:11,artist_id:7,genre_ids:[2]},...Array.from({length:7},(_,i)=>({track_id:20+i,artist_id:8,genre_ids:[1]}))];
  await renderDescriptorMap({...nodes,state:{selected:1},config:'manifest.json',json:async()=>manifest,genres,artists:[],current:()=>true,playbackTracks,onPlay:id=>played.push(id)});
  assert.deepEqual(played,[]);
  const excerpts=walk(nodes.rows).find(node=>node.className==='descriptor-excerpts');
  const buttons=walk(excerpts).filter(node=>node.tagName==='button' && node.className!=='descriptor-play-selection');assert.equal(buttons.length,6);
  assert.ok(!walk(excerpts).some(node=>node.href==='#track=11'));
  assert.equal(walk(excerpts).filter(node=>node.href==='#track=10').length,1);
  buttons[0].handlers.click();assert.deepEqual(played,[10]);
  assert.match(excerpts.children[0].textContent,/6 of 8 local excerpts/);
});

test('artist map excerpt buttons use exact artist ID only',async t=>{
  const nodes=setup(t),played=[];
  await renderDescriptorMap({...nodes,state:{entity:'artists',selected:7},config:'manifest.json',json:async path=>path==='manifest.json'?{...manifest,artist_shards:['artists.json']}:[{id:7,position:[0,0]}],genres,artists:[[7,'Verified native artist']],current:()=>true,playbackTracks:[{track_id:10,artist_id:7,genre_ids:[1]},{track_id:11,artist_id:8,genre_ids:[1]}],onPlay:id=>played.push(id)});
  const excerpts=walk(nodes.rows).find(node=>node.className==='descriptor-excerpts'),buttons=walk(excerpts).filter(node=>node.tagName==='button' && node.className!=='descriptor-play-selection');
  assert.equal(buttons.length,1);assert.deepEqual(played,[]);buttons[0].handlers.click();assert.deepEqual(played,[10]);
});

test('play these excerpts explicitly queues the full unique selection beyond six displayed clips',async t=>{
  const nodes=setup(t),played=[];
  const playbackTracks=[...Array.from({length:64},(_,i)=>({track_id:i+10,artist_id:7,genre_ids:[1]})),{track_id:10,artist_id:7,genre_ids:[1]},{track_id:99,artist_id:8,genre_ids:[2]}];
  await renderDescriptorMap({...nodes,state:{selected:1},config:'manifest.json',json:async()=>manifest,genres,artists:[],current:()=>true,playbackTracks,onPlay:(id,ids)=>played.push({id,ids})});
  assert.deepEqual(played,[]);
  const queue=walk(nodes.rows).find(node=>node.className==='descriptor-play-selection');
  assert.equal(queue.textContent,'Play these excerpts');queue.handlers.click();
  assert.deepEqual(played,[{id:10,ids:Array.from({length:64},(_,i)=>i+10)}]);
});
