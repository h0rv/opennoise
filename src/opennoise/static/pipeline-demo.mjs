import {fitCamera,zoomAtCenter} from './map-atlas.mjs';

const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
const anchor=(text,href)=>{const node=el('a',text);node.href=globalThis.OPENNOISE_LOCAL_FILES?.[href]?URL.createObjectURL(new Blob([JSON.stringify(globalThis.OPENNOISE_LOCAL_FILES[href],null,2)],{type:'application/json'})):href;return node;};
const artistLink=(artist)=>anchor(artist.name,`#artist/${artist.id}`);
const external=(text,href)=>{const node=anchor(text,href);node.target='_blank';node.rel='noopener noreferrer';return node;};

export async function renderMap({main,profile,load,selected='',isCurrent=()=>true}) {
  const data=await load(profile.pipeline_demo.path);
  if(!isCurrent())return;
  const [requestedMode,focus]=selected.split('|');
  const audio=requestedMode==='audio';
  const artists=data.artists.filter(a=>!audio||a.acoustic_position);
  const byId=new Map(data.artists.map(a=>[a.id,a]));
  const edges=audio?data.acoustic_edges:data.source_edges;
  const degree=new Map(artists.map(a=>[a.id,0]));
  for(const edge of edges){degree.set(edge.source,(degree.get(edge.source)??0)+1);degree.set(edge.target,(degree.get(edge.target)??0)+1);}
  main.append(el('h1','Artists'));
  const scope=el('p',`Provisional local demo · metadata catalog: ${data.counts.catalog_artists} artists / ${data.counts.core_recordings} recordings. Including acoustic-only credits: ${data.counts.artists} artists / ${data.counts.recordings} recordings.`);scope.className='scope';main.append(scope);
  const modes=el('nav');modes.className='breadcrumbs';modes.setAttribute('aria-label','Relationship source');
  for(const [mode,label] of [['source','Source relationships'],['audio','Suggested from audio features']]){
    const link=anchor(label,`#map/${mode}`);if((mode==='audio')===audio)link.setAttribute('aria-current','page');modes.append(link);
  }
  main.append(modes);
  const caption=el('p',audio
    ?`${data.counts.acoustic_artists} artists / ${data.counts.descriptor_recordings} recordings have descriptors; ${data.counts.compatible_artists} artists / ${data.counts.compatible_recordings} recordings meet the strict extractor contracts. Only ${data.counts.supported_query_artists} query artists / ${data.counts.supported_query_recordings} held-out recordings emit suggestions. This layer is electronic/ambient-heavy.`
    :'Shared artist genre claims. Layout arranges links; it is not a map of sound. Unlinked artists remain in the list.');
  caption.className='scope';main.append(caption);
  const query=document.querySelector('#search'),controller=new AbortController();query.value='';query.setAttribute('aria-controls','demo-artist-list');
  const toolbar=el('div');toolbar.className='demo-tools';
  const button=(text,action)=>{const node=el('button',text);node.type='button';node.addEventListener('click',action);return node;};
  const status=el('p');status.id='demo-map-status';status.setAttribute('role','status');
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 1000 600');svg.setAttribute('role','group');svg.setAttribute('tabindex','0');
  svg.setAttribute('aria-label','Artist relationship map. Arrow keys move between artists, Enter opens one; Shift and arrows pan; plus and minus zoom; Home resets. The list includes every artist.');svg.classList.add('demo-map');
  const group=document.createElementNS(ns,'g');svg.append(group);
  const point=a=>audio?a.acoustic_position:a.position;
  const placed=artists.filter(a=>point(a)),xs=placed.map(a=>point(a)[0]),ys=placed.map(a=>point(a)[1]);
  const bounds={x0:Math.min(...xs)-50,y0:Math.min(...ys)-50,x1:Math.max(...xs)+50,y1:Math.max(...ys)+50};
  let camera=fitCamera(bounds,{width:1000,height:600}),page=0,matches=artists,activeId=focus??placed[0]?.id;
  const listing=el('ul');listing.className='artist-list';listing.id='demo-artist-list';
  const paging=el('nav');paging.className='pagination';paging.setAttribute('aria-label','Map artist pages');
  const related=new Set(edges.filter(e=>e.source===focus||e.target===focus).flatMap(e=>[e.source,e.target]));
  function draw(){
    group.replaceChildren();group.setAttribute('transform',`translate(${camera.x} ${camera.y}) scale(${camera.scale})`);
    const visible=new Set(matches.filter(a=>point(a)).map(a=>a.id));
    for(const edge of edges){
      if(!visible.has(edge.source)||!visible.has(edge.target))continue;
      const a=point(byId.get(edge.source)),b=point(byId.get(edge.target));
      const line=document.createElementNS(ns,'line');
      for(const [k,v] of Object.entries({x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:audio?'#527087':'#9ca4ab','stroke-opacity':'.35','stroke-width':1/camera.scale}))line.setAttribute(k,v);
      group.append(line);
    }
    const priority=[...matches].sort((a,b)=>(b.id===focus)-(a.id===focus)||(degree.get(b.id)??0)-(degree.get(a.id)??0)||a.name.localeCompare(b.name));
    const labels=new Set(priority.filter(a=>point(a)).slice(0,Math.min(28,Math.floor(14*camera.scale/fitCamera(bounds,{width:1000,height:600}).scale))).map(a=>a.id));
    const rectangles=[];
    for(const a of matches){
      if(!point(a))continue;
      const [x,y]=point(a),link=document.createElementNS(ns,'a');link.setAttribute('href',`#artist/${a.id}`);link.setAttribute('tabindex',a.id===activeId?'0':'-1');link.setAttribute('aria-label',a.name);link.dataset.artist=a.id;
      const circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('r',(a.id===focus?6:degree.get(a.id)?4:2.5)/camera.scale);circle.setAttribute('fill',a.id===focus?'#a23a1c':degree.get(a.id)?'#174c91':'#747b81');
      const title=document.createElementNS(ns,'title');title.textContent=a.name;circle.append(title);link.append(circle);
      if(labels.has(a.id)||related.has(a.id)||a.id===activeId){
        const px=camera.x+x*camera.scale,py=camera.y+y*camera.scale,w=a.name.length*7.5;
        const box={x:px+7,y:py-10,w,h:18};
        if(a.id===activeId||!rectangles.some(r=>box.x<r.x+r.w&&box.x+box.w>r.x&&box.y<r.y+r.h&&box.y+box.h>r.y)){
          rectangles.push(box);const text=document.createElementNS(ns,'text');text.setAttribute('x',x+7/camera.scale);text.setAttribute('y',y+4/camera.scale);text.setAttribute('font-size',14/camera.scale);text.textContent=a.name;link.append(text);
        }
      }
      group.append(link);
    }
  }
  function zoom(factor){camera=zoomAtCenter(camera,{width:1000,height:600},factor,{min:.02,max:50});draw();}
  toolbar.append(button('Zoom in',()=>zoom(1.5)),button('Zoom out',()=>zoom(1/1.5)),button('Fit map',()=>{camera=fitCamera(bounds,{width:1000,height:600});draw();}),anchor('All artists','#artists/0'));
  svg.addEventListener('keydown',event=>{
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'].includes(event.key))event.preventDefault();
    if(event.key==='+'||event.key==='=')zoom(1.4);else if(event.key==='-')zoom(1/1.4);
    else if(event.key==='Home'){camera=fitCamera(bounds,{width:1000,height:600});draw();}
    else if(event.key.startsWith('Arrow')&&event.shiftKey){camera={...camera,x:camera.x+(event.key==='ArrowLeft'?40:event.key==='ArrowRight'?-40:0),y:camera.y+(event.key==='ArrowUp'?40:event.key==='ArrowDown'?-40:0)};draw();}
    else if(event.key.startsWith('Arrow')){const options=matches.filter(a=>point(a));if(!options.length)return;const delta=['ArrowLeft','ArrowUp'].includes(event.key)?-1:1;activeId=options[(options.findIndex(a=>a.id===activeId)+delta+options.length)%options.length].id;draw();group.querySelector(`[data-artist="${activeId}"]`)?.focus({preventScroll:true});}
  });
  svg.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY<0?1.12:1/1.12);},{passive:false});
  let drag=null;
  svg.addEventListener('pointerdown',event=>{drag={x:event.clientX,y:event.clientY,camera};});
  svg.addEventListener('pointermove',event=>{if(!drag||Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<5)return;const rect=svg.getBoundingClientRect();camera={...drag.camera,x:drag.camera.x+(event.clientX-drag.x)*1000/rect.width,y:drag.camera.y+(event.clientY-drag.y)*600/rect.height};draw();});
  for(const type of ['pointerup','pointercancel','pointerleave'])svg.addEventListener(type,()=>{drag=null;});
  function showList(){
    listing.replaceChildren();paging.replaceChildren();
    for(const a of matches.slice(page*50,(page+1)*50)){const item=el('li');item.append(artistLink(a));if(!degree.get(a.id))item.append(el('small',audio?' · no suggested link':' · no observed genre links'));listing.append(item);}
    if(!matches.length)listing.append(el('li','No matching artists. Clear the search to see this layer.'));
    if(page>0)paging.append(button('Previous',()=>{page--;showList();}));
    paging.append(el('span',`Page ${page+1} of ${Math.max(1,Math.ceil(matches.length/50))}`));
    if((page+1)*50<matches.length)paging.append(button('Next',()=>{page++;showList();}));
    status.textContent=`${matches.filter(a=>point(a)).length} artists on the map · ${matches.length} of ${artists.length} in this complete layer list.`;
  }
  query.addEventListener('input',()=>{const q=query.value.trim().toLocaleLowerCase();matches=artists.filter(a=>a.name.toLocaleLowerCase().includes(q)||a.id===q);activeId=matches.find(a=>point(a))?.id;page=0;showList();draw();},{signal:controller.signal});
  main.append(toolbar,svg,status,listing,paging);
  const sources=el('details');sources.append(el('summary','Pipeline, coverage and sources'));
  sources.append(el('p',`The catalog retains ${data.counts.core_recordings} recording entries, ${data.counts.catalog_artists} artists and ${data.counts.genres} observed genre labels. The acoustic source retains all ${data.counts.acoustic_nominations} nominations: ${data.counts.descriptor_recordings} have descriptors and ${data.counts.compatible_recordings} meet the strict extractor contracts. Missing and unsupported recordings remain in the source ledger.`));
  sources.append(el('p',`Acoustic coverage: ${data.counts.acoustic_artists} credited artists have descriptor rows; ${data.counts.compatible_artists} artists have extractor-compatible rows; only ${data.counts.supported_query_recordings} held-out recordings from ${data.counts.supported_query_artists} artists emit suggestions. These coverage denominators differ from the complete metadata catalog.`));
  sources.append(el('p','Pipeline: retained numeric music descriptors → unchanged version-specific standardized frames → recording neighbors excluding the query credit component → exact native artist credits → suggested links. Source-genre relationships use Wikidata observations separately. Scores from different frames are never pooled.'));
  sources.append(el('p','This demonstration does not establish perceptual similarity, recommendation quality or EveryNoise parity. No audio playback is included. New derived data remains local; no new datasets were fetched.'));
  sources.append(anchor('Build receipt','receipt.json'),el('span',' · '),anchor('Full recording/feature ledger','pipeline.json'),el('span',' · '),anchor('About','#about'));
  main.append(sources);showList();draw();return ()=>{controller.abort();query.removeAttribute('aria-controls');};
}

export async function appendArtistEvidence({main,profile,load,id,isCurrent=()=>true}) {
  const data=await load(profile.pipeline_demo.path);if(!isCurrent())return;
  const artist=data.artists.find(a=>a.id===id);if(!artist)return;
  const byId=new Map(data.artists.map(a=>[a.id,a]));
  const heading=el('h2','Artist relationships');main.append(heading);
  if(artist.position)main.append(anchor('Locate on the map',`#map/source|${id}`));
  else main.append(el('p','This artist has no source-map position; it remains in the complete artist list.'));
  const neighbors=data.source_edges.filter(e=>e.source===id||e.target===id);
  if(neighbors.length){const list=el('ul');for(const edge of neighbors){const other=byId.get(edge.source===id?edge.target:edge.source),item=el('li');item.append(artistLink(other),el('span',` · shared source genres: ${edge.genres.map(g=>data.genres[g]).join(', ')}`));list.append(item);}main.append(list);}
  else main.append(el('p','No shared source-genre relationships are observed for this identity.'));
  const suggested=data.acoustic_edges.filter(e=>e.source===id);
  main.append(el('h2','Suggested from audio features'));
  if(suggested.length){
    main.append(el('p','Recording descriptor neighbors lifted through exact artist credits. These are unvalidated suggestions; frames remain separate.'));
    const list=el('ul');for(const edge of suggested){
      const item=el('li');item.append(artistLink(byId.get(edge.target)));
      const details=el('details');details.append(el('summary',`${edge.observations.length} recording comparisons · frame ${edge.contract.slice(0,8)}, fold ${edge.fold}`));
      for(const observation of edge.observations){const a=data.recordings[observation.query_recording_mbid],b=data.recordings[observation.candidate_recording_mbid];const p=el('p');p.append(external(a.title,a.url),el('span',' → '),external(b.title,b.url),el('span',` · standardized distance ${observation.distance.toFixed(4)} (within this frame only)`));details.append(p);}item.append(details);list.append(item);
    }main.append(list,anchor('Open the acoustic layer',`#map/audio|${id}`));
  }else main.append(el('p','No held-out acoustic suggestions are available for this artist. This is a coverage outcome, not a judgment that the artist is unrelated.'));
  const features=data.features.filter(row=>row.artists.includes(id));
  if(features.length){
    const panel=el('details');panel.append(el('summary',`Recording features and provenance (${features.length})`));
    for(const row of features){
      const section=el('details');section.append(el('summary',`${row.title} · ${row.outcome.replaceAll('_',' ')}`));
      const p=el('p');p.append(external('MusicBrainz recording',`https://musicbrainz.org/recording/${row.id}`),el('span',' · '),external('AcousticBrainz source',row.source_url));section.append(p);
      const table=el('table'),head=el('tr');head.append(el('th','Source coordinate'),el('th','Value'));table.append(head);
      for(const [i,column] of data.columns.entries()){const tr=el('tr');tr.append(el('td',`${column.path}${column.index===null?'':`[${column.index}]`}`),el('td',row.values[i]===null?'missing':String(row.values[i])));table.append(tr);}section.append(table);panel.append(section);
    }main.append(panel);
  }else main.append(el('p','No acoustic feature rows are retained for this artist.'));
}
