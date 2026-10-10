/** Frozen numeric PCA coordinates: mathematical structure, not validated musical similarity. */
const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
const positioned = row => Array.isArray(row.position) && row.position.length === 2 && row.position.every(Number.isFinite);
const PAGE_SIZE = 50;

export async function renderDescriptorMap({state,config,json,genres,artists,rows,heading,status,current,onStateChange,registerCleanup,playbackTracks=[],onPlay}) {
  heading.textContent = 'Audio descriptor map';
  status.textContent = 'Loading frozen coordinates…';
  if (!config) { status.textContent = 'This export has no descriptor map.'; return; }
  const section = element('section'); section.className = 'fma-descriptor-map';
  section.dataset.evidenceRole = 'frozen_descriptor_pca_projection'; rows.append(section);
  let manifest;
  try {
    manifest = await json(typeof config === 'string' ? config : config.manifest_path ?? config.manifest);
    if (!current()) return;
    if (manifest.revision !== 'fma-descriptor-map-view-v1' || !Array.isArray(manifest.genres) || !Array.isArray(manifest.artist_shards)) throw Error('Unsupported coordinate manifest.');
  } catch { if (current()) status.textContent = 'Coordinate map unavailable. Reload to retry.'; return; }
  section.append(element('p', 'PC1 and PC2 are mathematical summaries of audio descriptors. Nearby points are not validated musical recommendations; these axes do not reproduce Every Noise’s musical meanings.'));
  const controls = element('form'); controls.className = 'descriptor-controls';
  const entityLabel = element('label', 'Show '), entitySelect = element('select');
  for (const [value,text] of [['genres','Genres'],['artists','Artists']]) { const option = element('option',text); option.value=value; entitySelect.append(option); }
  entitySelect.value = state.entity === 'artists' ? 'artists' : 'genres'; entityLabel.append(entitySelect);
  const searchLabel = element('label','Find '), search = element('input'); search.type='search'; search.id='descriptor-query'; search.placeholder='Name or native ID'; search.value=state.q ?? ''; searchLabel.append(search);
  const labelsLabel = element('label'), labels = element('input'); labels.type='checkbox'; labels.checked=entitySelect.value === 'genres'; labelsLabel.append(labels,element('span','Names on map'));
  controls.append(entityLabel,searchLabel,labelsLabel); section.append(controls);
  const toolbar = element('div'); toolbar.className='descriptor-toolbar';
  const canvas = element('canvas'); canvas.className='descriptor-canvas'; canvas.tabIndex=0; canvas.setAttribute('role','img'); canvas.setAttribute('aria-label','Descriptor map. Drag to pan; arrow keys pan, plus and minus zoom, Home resets. All entities also appear in the list below.');
  const frame = element('div'); frame.className='descriptor-frame'; frame.append(canvas);
  const xLabel = element('span','PC1 →'); xLabel.className='descriptor-x'; const yLabel=element('span','PC2 ↑'); yLabel.className='descriptor-y'; frame.append(xLabel,yLabel);
  const selection = element('p'); selection.className='descriptor-selection'; selection.setAttribute('aria-live','polite');
  const excerptChoices = element('div'); excerptChoices.className='descriptor-excerpts';
  const listing = element('ul'); listing.className='descriptor-list';
  const pagination=element('div'); pagination.className='descriptor-pages';
  section.append(toolbar,frame,selection,excerptChoices,listing,pagination);
  let entity=entitySelect.value, selected=state.selected == null ? null : Number(state.selected), page=0, zoom=1, panX=0,panY=0;
  let all=[],matches=[],points=[],extent=1,artistPositions=null,artistLoading=null,loadVersion=0,width=600,height=400;
  const ctx=canvas.getContext('2d');
  function button(text,action) { const b=element('button',text); b.type='button'; b.addEventListener('click',action); return b; }
  const announce = () => onStateChange?.({kind:'descriptor-map',entity,q:search.value,selected:selected ?? undefined});
  function reset() { zoom=1;panX=0;panY=0;draw(); }
  function magnify(factor) { zoom=Math.max(.5,Math.min(16,zoom*factor));draw(); }
  toolbar.append(button('Zoom in',()=>magnify(1.4)),button('Zoom out',()=>magnify(1/1.4)),button('Reset view',reset),element('span','Drag to pan · choose a point or a name below'));
  function coordinates(position) { const scale=Math.min(width,height)*.43*zoom/extent;return [width/2+panX+position[0]*scale,height/2+panY-position[1]*scale]; }
  function draw() {
    if (!current() || !ctx) return;
    width=Math.max(240,frame.clientWidth || 600);height=width<500?330:430;
    const ratio=Math.min(window.devicePixelRatio || 1,2);canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);canvas.style.height=`${height}px`;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
    ctx.strokeStyle='#ddd';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,height/2+panY);ctx.lineTo(width,height/2+panY);ctx.moveTo(width/2+panX,0);ctx.lineTo(width/2+panX,height);ctx.stroke();
    points=[];ctx.font='11px Arial';
    for (const row of matches) {
      if (!positioned(row)) continue;
      const [x,y]=coordinates(row.position);if(x < -5 || x > width+5 || y < -5 || y > height+5) continue;
      points.push({row,x,y});ctx.fillStyle=row.id===selected?'#a34800':'#154d94';ctx.beginPath();ctx.arc(x,y,row.id===selected?5:entity==='artists'?2:3,0,Math.PI*2);ctx.fill();
      if(labels.checked || row.id===selected) {ctx.fillStyle='#222';ctx.fillText(row.name,x+6,Math.max(12,y-4));}
    }
  }
  function select(id) {
    selected=id;selection.replaceChildren();excerptChoices.replaceChildren();
    const row=all.find(item=>item.id===id);
    if(row) {
      const link=element('a',row.name);link.href=`#${entity==='genres'?'genre':'artist'}=${id}`;
      selection.append(link,element('span',` · #${id}${positioned(row)?' · has descriptor coordinates':' · no supported coordinates'}`));
      const seenTracks=new Set();
      const available=playbackTracks.filter(track=>{
        const matched=Number.isSafeInteger(track.track_id) && track.track_id>0 && (entity==='genres'?(track.genre_ids ?? []).includes(id):track.artist_id===id);
        if(!matched || seenTracks.has(track.track_id))return false;
        seenTracks.add(track.track_id);return true;
      });
      if(!available.length) excerptChoices.append(element('p','No local excerpt for this selection.'));
      else {
        excerptChoices.append(element('p',`${Math.min(6,available.length)} of ${available.length} local excerpts · ${entity==='genres'?'direct track genre annotations':'exact native artist association'}`));
        if(onPlay) {
          const queueIds=available.slice(0,64).map(track=>track.track_id);
          const playAll=button('Play these excerpts',()=>{if(current())onPlay(queueIds[0],[...queueIds]);});
          playAll.className='descriptor-play-selection';
          playAll.setAttribute('aria-label',`Play ${queueIds.length} local excerpts for ${row.name}`);
          excerptChoices.append(playAll);
        }
        const choices=element('ul');
        for(const track of available.slice(0,6)) {
          const item=element('li'),link=element('a',track.title || `Track #${track.track_id}`);link.href=`#track=${track.track_id}`;item.append(link);
          if(onPlay) item.append(button(`Play excerpt #${track.track_id}`,()=>{if(current())onPlay(track.track_id);}));
          choices.append(item);
        }
        excerptChoices.append(choices);
      }
      if(positioned(row)) {const scale=Math.min(width,height)*.43*zoom/extent;panX=-row.position[0]*scale;panY=row.position[1]*scale;}
    } else selection.textContent='Choose a point or use the list below.';
    draw();announce();
  }
  function showList() {
    listing.replaceChildren();pagination.replaceChildren();
    const last=Math.max(0,Math.ceil(matches.length/PAGE_SIZE)-1);page=Math.min(page,last);
    for(const row of matches.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
      const item=element('li');const choose=button(row.name,()=>{select(row.id);selection.scrollIntoView({block:'nearest'});});choose.setAttribute('aria-label',`Select ${row.name}, native ID ${row.id}${positioned(row)?'':' — no coordinates'}`);
      const detail=element('a',entity==='genres'?'Tracks':'Artist');detail.href=`#${entity==='genres'?'genre':'artist'}=${row.id}`;
      item.append(choose,element('small',`#${row.id}${positioned(row)?'':' · no coordinates'}`),detail);listing.append(item);
    }
    if(!matches.length) listing.append(element('li','No matching names or native IDs. Clear Find to see every entity.'));
    const previous=button('Previous',()=>{page--;showList();}),next=button('Next',()=>{page++;showList();});previous.disabled=page===0;next.disabled=page===last;
    pagination.append(previous,element('span',`Page ${page+1} of ${last+1}`),next);
  }
  function filter(notify=true) {
    const q=search.value.trim().toLocaleLowerCase();matches=all.filter(row=>!q || row.name.toLocaleLowerCase().includes(q) || String(row.id)===q);
    const count=matches.filter(positioned).length;status.textContent=`${matches.length} matching ${entity} · ${count} with coordinates · ${matches.length-count} without coordinates. Full list below; map positions are descriptor summaries.`;
    page=0;showList();draw();if(notify) announce();
  }
  async function load() {
    const version=++loadVersion;entity=entitySelect.value;status.textContent='Loading coordinates…';
    all=[];matches=[];listing.replaceChildren();pagination.replaceChildren();selection.replaceChildren();excerptChoices.replaceChildren();draw();
    try {
      if(entity==='artists' && !artistPositions) {
        if(!artistLoading) artistLoading=(async()=>{
          const shards=new Array(manifest.artist_shards.length);let cursor=0,failed=false;
          const results=await Promise.allSettled(Array.from({length:Math.min(4,shards.length)},async()=>{
            while(cursor<shards.length) {
              if(!current() || failed)return;
              const index=cursor++;
              try {shards[index]=await json(manifest.artist_shards[index]);}
              catch(error){failed=true;throw error;}
            }
          }));
          const failure=results.find(result=>result.status==='rejected');if(failure)throw failure.reason;
          if(!current())return null;
          if(shards.some(shard=>!Array.isArray(shard)))throw Error('Invalid artist coordinate shard.');
          return new Map(shards.flat().map(row=>[row.id,row.position]));
        })();
        try {artistPositions=await artistLoading;}catch(error){artistLoading=null;throw error;}
      }
      if(!current() || version!==loadVersion)return;
      const positions=entity==='genres'?new Map(manifest.genres.map(row=>[row.id,row.position])):artistPositions;
      all=(entity==='genres'?[...genres.values()].map(row=>({id:row.genre_id,name:row.title})):artists.filter(row=>Number.isSafeInteger(row[0]) && row[0]>0 && positions.has(row[0])).map(row=>({id:row[0],name:row[1] || `Artist #${row[0]}`})))
        .map(row=>({...row,position:positions.get(row.id) ?? null})).sort((a,b)=>a.name.localeCompare(b.name)||a.id-b.id);
      extent=1;for(const row of all)if(positioned(row))extent=Math.max(extent,Math.abs(row.position[0]),Math.abs(row.position[1]));
      zoom=1;panX=0;panY=0;filter(false);select(selected);
    } catch {if(current() && version===loadVersion){status.textContent='Coordinate data unavailable. Switch view or reload to retry.';listing.replaceChildren(element('li','No partial coordinate results are shown.'));}}
  }
  entitySelect.addEventListener('change',()=>{entity=entitySelect.value;selected=null;labels.checked=entitySelect.value==='genres';announce();load();});
  search.addEventListener('input',()=>filter());labels.addEventListener('change',draw);
  controls.addEventListener('submit',event=>{event.preventDefault();filter();listing.querySelector('button')?.focus();});
  let drag=null;
  canvas.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY,panX,panY};canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{if(!drag)return;panX=drag.panX+event.clientX-drag.x;panY=drag.panY+event.clientY-drag.y;draw();});
  canvas.addEventListener('pointerup',event=>{
    if(!drag)return;const moved=Math.hypot(event.clientX-drag.x,event.clientY-drag.y);drag=null;
    if(moved>5)return;const bounds=canvas.getBoundingClientRect(),x=event.clientX-bounds.left,y=event.clientY-bounds.top;
    const nearest=points.map(point=>({...point,d:Math.hypot(point.x-x,point.y-y)})).filter(point=>point.d<=14).sort((a,b)=>a.d-b.d||a.row.id-b.row.id)[0];if(nearest)select(nearest.row.id);
  });
  canvas.addEventListener('pointercancel',()=>{drag=null;});
  canvas.addEventListener('keydown',event=>{const steps={ArrowLeft:[30,0],ArrowRight:[-30,0],ArrowUp:[0,30],ArrowDown:[0,-30]};if(steps[event.key]){event.preventDefault();panX+=steps[event.key][0];panY+=steps[event.key][1];draw();}else if(['+','=','-','Home'].includes(event.key)){event.preventDefault();if(event.key==='Home')reset();else magnify(event.key==='-'?1/1.4:1.4);}});
  if(typeof ResizeObserver!=='undefined') {
    const observer=new ResizeObserver(()=>{if(current())draw();else observer.disconnect();});
    observer.observe(frame);registerCleanup?.(()=>observer.disconnect());
  }
  await load();
}
