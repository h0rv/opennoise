/* Deterministic map interaction. Geometry and LOD arrive in map-data.json. */
(() => {
  const stage = document.querySelector('#map-stage');
  if (!stage) return;
  const svg = stage.querySelector('svg');
  const controls = document.querySelector('#map-controls');
  const detail = document.querySelector('#map-detail');
  const search = document.querySelector('#query');
  let data, state, drag, pointers = new Map();
  const pad = 42, maxLabels = [30, 68, 130, 220];
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const box = () => stage.getBoundingClientRect();
  const fit = () => {
    const r = box(), usableW = r.width - 2 * pad, usableH = r.height - 2 * pad;
    const w = data.world, width = w.max_x - w.min_x, height = w.max_y - w.min_y;
    const scale = Math.max(.01, Math.min(usableW / width, usableH / height));
    state = { scale, x: r.width / 2 - ((w.min_x + w.max_x) / 2 - .5) * scale, y: r.height / 2 - ((w.min_y + w.max_y) / 2 - .5) * scale, focus: null };
    render();
  };
  const world = (node) => ({ x: state.x + (node.x - .5) * state.scale, y: state.y + (node.y - .5) * state.scale });
  const level = () => clamp(Math.floor(Math.log2(state.scale / Math.min(box().width, box().height)) + 2), 0, 3);
  const labels = () => {
    const candidates = new Set(data.lod[String(level())] || []), occupied = [];
    return data.nodes.filter(n => candidates.has(n.id)).filter(n => {
      const p = world(n), width = Math.min(170, 7 * n.name.length + 14), b = [p.x + 5, p.y - 10, p.x + width, p.y + 8];
      if (p.x < 0 || p.x > box().width || p.y < 0 || p.y > box().height || occupied.some(o => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1])) return false;
      occupied.push(b); return occupied.length <= maxLabels[level()];
    });
  };
  const render = () => {
    const r = box(), visible = data.nodes.filter(n => { const p = world(n); return p.x > -8 && p.x < r.width + 8 && p.y > -8 && p.y < r.height + 8; });
    const shown = labels(), labelIds = new Set(shown.map(n => n.id));
    const focused = state.focus;
    const edges = focused ? data.peers.filter(e => e.source === focused || e.target === focused).slice(0, 12) : [];
    svg.setAttribute('viewBox', `0 0 ${r.width} ${r.height}`);
    svg.replaceChildren();
    const ns = 'http://www.w3.org/2000/svg';
    for (const e of edges) { const a=data.nodes.find(n=>n.id===e.source), b=data.nodes.find(n=>n.id===e.target); if (!a || !b) continue; const ap=world(a),bp=world(b),line=document.createElementNS(ns,'line'); line.setAttribute('x1',ap.x);line.setAttribute('y1',ap.y);line.setAttribute('x2',bp.x);line.setAttribute('y2',bp.y);line.setAttribute('stroke','currentColor');line.setAttribute('opacity','.24');svg.append(line); }
    for (const n of visible) { const p=world(n), g=document.createElementNS(ns,'g'), c=document.createElementNS(ns,'circle'); c.setAttribute('cx',p.x);c.setAttribute('cy',p.y);c.setAttribute('r', n.id===focused ? '5' : '2.5');c.setAttribute('fill','var(--node)');c.setAttribute('tabindex','0');c.setAttribute('role','button');c.setAttribute('aria-label',n.name);c.addEventListener('click',()=>focus(n.id,true));c.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focus(n.id,true)}});g.append(c);if(labelIds.has(n.id)||n.id===focused){const t=document.createElementNS(ns,'text');t.textContent=n.name;t.setAttribute('x',p.x+6);t.setAttribute('y',p.y+4);t.setAttribute('font-size','12');t.setAttribute('fill','currentColor');t.setAttribute('paint-order','stroke');t.setAttribute('stroke','var(--bg)');t.setAttribute('stroke-width','3');g.append(t)}svg.append(g); }
    controls.querySelector('[data-map-action="back"]').hidden = !focused;
  };
  const focus = (id, push) => { const n=data.nodes.find(x=>x.id===id); if(!n)return; state.focus=id; const r=box();state.scale=Math.max(state.scale,Math.min(r.width,r.height)*1.8);state.x=r.width/2-(n.x-.5)*state.scale;state.y=r.height/2-(n.y-.5)*state.scale; if(push) history.pushState({genre:id},'',`?genre=${encodeURIComponent(id)}`); detail.hidden=false; detail.replaceChildren();const h=document.createElement('h2');h.textContent=n.name;detail.append(h);const peers=data.peers.filter(e=>e.source===id||e.target===id).slice(0,12);if(peers.length){const ul=document.createElement('ul');for(const e of peers){const other=data.nodes.find(x=>x.id===(e.source===id?e.target:e.source));if(!other)continue;const b=document.createElement('button');b.textContent=other.name;b.onclick=()=>focus(other.id,true);const li=document.createElement('li');li.append(b);ul.append(li)}detail.append(ul)}render(); };
  const zoom = (factor, x=box().width/2, y=box().height/2) => { const next=clamp(state.scale*factor,Math.min(box().width,box().height)*.72,Math.max(box().width,box().height)*20);state.x=x-(x-state.x)*(next/state.scale);state.y=y-(y-state.y)*(next/state.scale);state.scale=next;render(); };
  controls.addEventListener('click',e=>{const a=e.target.dataset.mapAction;if(a==='fit'){history.pushState({},'',location.pathname);detail.hidden=true;fit()}if(a==='in')zoom(1.35);if(a==='out')zoom(1/1.35);if(a==='back'){history.back()}});
  stage.addEventListener('wheel',e=>{e.preventDefault();const r=box();zoom(e.deltaY<0?1.15:1/1.15,e.clientX-r.left,e.clientY-r.top)},{passive:false});
  stage.addEventListener('pointerdown',e=>{stage.setPointerCapture(e.pointerId);pointers.set(e.pointerId,[e.clientX,e.clientY]);drag=[e.clientX,e.clientY]});
  stage.addEventListener('pointermove',e=>{if(!pointers.has(e.pointerId))return;const prior=pointers.get(e.pointerId);pointers.set(e.pointerId,[e.clientX,e.clientY]);if(pointers.size===1&&drag){state.x+=e.clientX-drag[0];state.y+=e.clientY-drag[1];drag=[e.clientX,e.clientY];render()}else if(pointers.size===2){const pts=[...pointers.values()];const old=Math.hypot(prior[0]-pts[0][0],prior[1]-pts[0][1]);const now=Math.hypot(pts[0][0]-pts[1][0],pts[0][1]-pts[1][1]);if(old)zoom(now/old)}});
  stage.addEventListener('pointerup',e=>{pointers.delete(e.pointerId);drag=null}); window.addEventListener('resize',render); window.addEventListener('popstate',()=>{const id=new URLSearchParams(location.search).get('genre');if(id)focus(id,false);else{detail.hidden=true;fit()}});
  fetch(stage.dataset.mapUrl).then(r=>r.json()).then(value=>{data=value;fit();const id=new URLSearchParams(location.search).get('genre');if(id)focus(id,false);if(search)search.addEventListener('change',()=>{const q=search.value.trim().toLowerCase();const n=data.nodes.find(x=>x.name.toLowerCase()===q)||data.nodes.find(x=>x.name.toLowerCase().includes(q));if(n)focus(n.id,true)});});
})();
