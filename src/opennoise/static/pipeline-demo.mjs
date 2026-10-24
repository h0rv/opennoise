import {fitCamera,zoomAtCenter} from './map-atlas.mjs';

const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
const anchor=(text,href)=>{const node=el('a',text);node.href=globalThis.OPENNOISE_LOCAL_FILES?.[href]?URL.createObjectURL(new Blob([JSON.stringify(globalThis.OPENNOISE_LOCAL_FILES[href],null,2)],{type:'application/json'})):href;return node;};
const artistLink=(artist)=>anchor(artist.name,`#artist/${artist.id}`);
const external=(text,href)=>{const node=anchor(text,href);node.target='_blank';node.rel='noopener noreferrer';return node;};

// A text atlas of observed relationships. Its axes have no acoustic meaning.
const palette=['#385c95','#76527d','#376a57','#935034','#635b1e','#435d70'];
const labelWidth=node=>Math.min(360,Math.max(66,node.name.length*8+22));
function layoutNames(rows){
  const nodes=rows.map(row=>({...row,groups:new Set(row.groups),width:labelWidth(row)})).sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
  const adjacent=new Map(nodes.map(node=>[node.id,[]]));
  const edges=[];
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    const common=[...nodes[i].groups].filter(id=>nodes[j].groups.has(id)).length;
    if(common){adjacent.get(nodes[i].id).push(nodes[j]);adjacent.get(nodes[j].id).push(nodes[i]);edges.push([nodes[i],nodes[j],common/Math.sqrt(nodes[i].groups.size*nodes[j].groups.size)]);}
  }
  const components=[],seen=new Set();
  for(const node of nodes){if(seen.has(node.id))continue;const group=[],queue=[node];seen.add(node.id);while(queue.length){const current=queue.pop();group.push(current);for(const other of adjacent.get(current.id))if(!seen.has(other.id)){seen.add(other.id);queue.push(other);}}components.push(group);}
  components.sort((a,b)=>b.length-a.length||a[0].name.localeCompare(b[0].name));
  let cursorY=30;
  for(const [componentIndex,group] of components.entries()){
    const isolated=group.length===1;
    for(const [index,node] of group.entries()){node.x=90+(index%6)*185;node.y=40+Math.floor(index/6)*68;node.color=palette[componentIndex%palette.length];node.isolated=isolated;}
    const localEdges=edges.filter(([a])=>group.includes(a));
    // Springs only use shared observed identities. Rectangle repulsion keeps names readable.
    for(let iteration=0;iteration<360;iteration++){
      const forces=new Map(group.map(node=>[node.id,[0,0]]));
      if(iteration<250)for(const [a,b,weight] of localEdges){const dx=b.x-a.x,dy=b.y-a.y,dist=Math.max(1,Math.hypot(dx,dy));const pull=(dist-135)*.008*weight;forces.get(a.id)[0]+=dx*pull;forces.get(a.id)[1]+=dy*pull;forces.get(b.id)[0]-=dx*pull;forces.get(b.id)[1]-=dy*pull;}
      for(let i=0;i<group.length;i++)for(let j=i+1;j<group.length;j++){
        const a=group[i],b=group[j],dx=b.x-a.x||.1,dy=b.y-a.y||.1;
        const overlapX=(a.width+b.width)/2+14-Math.abs(dx),overlapY=47-Math.abs(dy);
        if(overlapX>0&&overlapY>0){const axis=overlapX<overlapY?0:1;const push=(axis===0?overlapX:overlapY)*.55*Math.sign(axis===0?dx:dy);forces.get(a.id)[axis]-=push;forces.get(b.id)[axis]+=push;}
      }
      for(const node of group){const [fx,fy]=forces.get(node.id);node.x=Math.max(node.width/2+15,Math.min(1200-node.width/2-15,node.x+Math.max(-12,Math.min(12,fx))));node.y=Math.max(28,node.y+Math.max(-12,Math.min(12,fy)));}
    }
    const occupied=[];
    for(const node of [...group].sort((a,b)=>b.groups.size-a.groups.size||a.name.localeCompare(b.name))){
      const origin={x:node.x,y:node.y};
      for(let probe=0;probe<12000;probe++){
        const radius=probe?10*Math.sqrt(probe):0,angle=probe*2.399963229728653;
        const x=Math.max(node.width/2+15,Math.min(1200-node.width/2-15,origin.x+Math.cos(angle)*radius)),y=Math.max(28,origin.y+Math.sin(angle)*radius);
        const rect={x:x-node.width/2-5,y:y-24,w:node.width+10,h:48};
        if(!occupied.some(r=>rect.x<r.x+r.w&&rect.x+rect.w>r.x&&rect.y<r.y+r.h&&rect.y+rect.h>r.y)){
          node.x=x;node.y=y;occupied.push(rect);break;
        }
      }
    }
    const top=Math.min(...group.map(node=>node.y));
    for(const node of group)node.y=node.y-top+cursorY;
    cursorY=Math.max(...group.map(node=>node.y))+80;
    if(isolated)cursorY-=28;
  }
  return {nodes,width:1200,height:Math.max(360,cursorY)};
}
function textMap({main,rows,kind,label,query,filtered=false}){
  const layout=layoutNames(rows),controller=new AbortController();
  const toolbar=el('div');toolbar.className='atlas-tools';
  const viewport=el('div');viewport.className=`name-map ${kind==='genre'?'genre-map':'genre-artist-map'}`;viewport.tabIndex=0;viewport.setAttribute('role','region');viewport.setAttribute('aria-label',`${label}. Scroll to explore. Arrow keys scroll, Tab selects a name, Enter opens it.`);
  const surface=el('div');surface.className='name-surface';surface.style.width=`${layout.width}px`;surface.style.height=`${layout.height}px`;viewport.append(surface);
  const status=el('p',`${rows.length} ${kind==='genre'?'genres':'artists'} · shared ${kind==='genre'?'artists':'genres'}`);status.className='scope';status.setAttribute('role','status');
  let zoom=1;
  const button=(text,title,action)=>{const b=el('button',text);b.type='button';b.title=title;b.setAttribute('aria-label',title);b.addEventListener('click',action);return b;};
  const zoomTo=value=>{zoom=Math.max(.5,Math.min(2,value));surface.style.zoom=zoom;};
  toolbar.append(status,button('−','Zoom out',()=>zoomTo(zoom/1.2)),button('+','Zoom in',()=>zoomTo(zoom*1.2)),button('Reset','Reset map',()=>{zoomTo(1);viewport.scrollTo(0,0);}));
  for(const node of layout.nodes){const a=anchor(node.name,`#${kind}/${node.id}`);a.dataset[kind]=node.id;a.style.left=`${node.x-node.width/2}px`;a.style.top=`${node.y-22}px`;a.style.width=`${node.width}px`;a.style.color=node.color;a.className='map-name';a.title=`${node.name} · ${node.groups.size} observed ${kind==='genre'?'artists':'genres'}${node.isolated?' · no shared links':''}`;a.addEventListener('focus',()=>a.scrollIntoView({block:'nearest',inline:'nearest'}));surface.append(a);}
  viewport.addEventListener('keydown',event=>{if(event.target!==viewport)return;if(event.key==='+'||event.key==='='){event.preventDefault();zoomTo(zoom*1.2);}else if(event.key==='-'){event.preventDefault();zoomTo(zoom/1.2);}else if(event.key==='Home'){event.preventDefault();viewport.scrollTo(0,0);}else if(event.key==='Enter')surface.querySelector('a:not(.dimmed)')?.focus();});
  let drag;
  viewport.addEventListener('pointerdown',event=>{if(event.pointerType==='touch')return;drag={x:event.clientX,y:event.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved:false};});
  viewport.addEventListener('pointermove',event=>{if(!drag||!event.buttons)return;if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>5)drag.moved=true;if(drag.moved){viewport.scrollLeft=drag.left+drag.x-event.clientX;viewport.scrollTop=drag.top+drag.y-event.clientY;event.preventDefault();}});
  viewport.addEventListener('click',event=>{if(drag?.moved){event.preventDefault();event.stopPropagation();}drag=null;},true);
  viewport.addEventListener('pointerleave',()=>{drag=null;});
  if(query&&filtered){query.value='';query.addEventListener('input',()=>{const q=query.value.trim().toLocaleLowerCase();let count=0;for(const a of surface.querySelectorAll('a')){const match=!q||a.textContent.toLocaleLowerCase().includes(q);a.classList.toggle('dimmed',!match);if(match)count++;}status.textContent=q?`${count} matching ${kind==='genre'?'genres':'artists'}`:`${rows.length} ${kind==='genre'?'genres':'artists'} · shared ${kind==='genre'?'artists':'genres'}`;if(q)surface.querySelector('a:not(.dimmed)')?.scrollIntoView({block:'nearest',inline:'nearest'});},{signal:controller.signal});}
  main.append(toolbar,viewport);if(viewport.clientWidth<600)viewport.scrollLeft=Math.max(0,(layout.width-viewport.clientWidth)/2);return ()=>controller.abort();
}
function mapLinks(main,current,entries){const nav=el('nav');nav.className='view-links';nav.setAttribute('aria-label','View');for(const [name,href,key] of entries){const a=anchor(name,href);if(key===current)a.setAttribute('aria-current','page');nav.append(a);}main.append(nav);}
function sourceNote(main,data){const note=el('details');note.className='sources';note.append(el('summary','Sources'),el('p',`${data.counts.genres} genre labels; ${data.counts.artists_with_direct_genres} of ${data.counts.artists} artists have observed genre claims. Positions group shared source observations, not acoustic distances. Isolated labels have no shared artist links.`),el('p','MusicBrainz identities and recording credits; Wikidata genre claims; AcousticBrainz descriptors. Metadata: CC0. Suggested acoustic links are unvalidated and use a small electronic/ambient-heavy subset. Recordings link to source metadata. No audio playback.'),anchor('Source ledger','pipeline.json'),el('span',' · '),anchor('Build receipt','receipt.json'),el('span',' · '),anchor('About','#about'));main.append(note);}
export async function renderGenres({main,profile,genres,load,isCurrent=()=>true}){
  const data=await load(profile.pipeline_demo.path);if(!isCurrent())return;
  main.append(el('h1','Genres'));
  mapLinks(main,'map',[['Map','#','map'],['List','#genres','list']]);
  const rows=genres.map(g=>({id:g.genre_id,name:g.name,groups:g.artists.map(a=>a[0])}));
  const linked=rows.filter(a=>rows.some(b=>a!==b&&a.groups.some(id=>b.groups.includes(id))));
  const unlinked=rows.filter(a=>!linked.includes(a));
  const cleanup=textMap({main,rows:linked,kind:'genre',label:'Genre map',query:document.querySelector('#search'),filtered:true});
  if(unlinked.length){main.append(el('h2','No shared artist links'));const list=el('ul');list.className='unlinked-genres related-genres';for(const g of unlinked){const li=el('li');li.append(anchor(g.name,`#genre/${g.id}`));list.append(li);}main.append(list);}
  sourceNote(main,data);return cleanup;
}
export async function renderGenre({main,profile,load,genre,members,isCurrent=()=>true}){
  const data=await load(profile.pipeline_demo.path);if(!isCurrent())return;
  main.append(el('h1',genre.name));
  const isList=decodeURIComponent(location.hash).endsWith('|list');
  mapLinks(main,isList?'list':'map',[['← Genres','#','back'],['Map',`#genre/${genre.genre_id}`,'map'],['List',`#genre/${genre.genre_id}|list`,'list']]);
  const byId=new Map(data.artists.map(a=>[a.id,a]));
  const rows=members.map(a=>byId.get(a[0])).filter(Boolean);
  let cleanup=()=>{};
  if(isList){const list=el('ul');list.className='artist-list';for(const a of rows){const li=el('li');li.append(artistLink(a));list.append(li);}main.append(el('p',`${rows.length} observed artists`),list);}
  else cleanup=textMap({main,rows:rows.map(a=>({...a,groups:a.genres})),kind:'artist',label:`Artists in ${genre.name}`});
  const related=[];for(const [id,name] of Object.entries(data.genres)){if(id===genre.genre_id)continue;const overlap=rows.filter(a=>a.genres.includes(id)).length;if(overlap)related.push({id,name,overlap});}
  related.sort((a,b)=>b.overlap-a.overlap||a.name.localeCompare(b.name));
  if(related.length){main.append(el('h2','Shared artists with'));const list=el('ul');list.className='related-genres';for(const g of related){const li=el('li');li.append(anchor(g.name,`#genre/${g.id}`));list.append(li);}main.append(list);}
  const sources=el('details');sources.className='sources';sources.append(el('summary','Sources'),el('p','Observed genre claims from Wikidata. Positions group shared genre claims, not acoustic distance. Metadata: CC0.'),external('Wikidata genre',`https://www.wikidata.org/wiki/${genre.genre_id}`));main.append(sources);return cleanup;
}

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
  main.append(el('h1',audio?'Suggested artists':'Artists'));
  mapLinks(main,audio?'audio':'source',[['Map','#map/source','source'],['List','#artists/0','list'],['Suggested','#map/audio','audio']]);
  main.append(el('p',audio?'Suggested · audio descriptors':'Observed · shared genres'));
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
    for(const a of matches.slice(page*50,(page+1)*50)){const item=el('li');item.append(artistLink(a));listing.append(item);}
    if(!matches.length)listing.append(el('li','No matching artists. Clear the search to see this layer.'));
    if(page>0)paging.append(button('Previous',()=>{page--;showList();}));
    paging.append(el('span',`Page ${page+1} of ${Math.max(1,Math.ceil(matches.length/50))}`));
    if((page+1)*50<matches.length)paging.append(button('Next',()=>{page++;showList();}));
    status.textContent=`${matches.filter(a=>point(a)).length} on map · ${matches.length} in list`;
  }
  query.addEventListener('input',()=>{const q=query.value.trim().toLocaleLowerCase();matches=artists.filter(a=>a.name.toLocaleLowerCase().includes(q)||a.id===q);activeId=matches.find(a=>point(a))?.id;page=0;showList();draw();},{signal:controller.signal});
  main.append(toolbar,svg,status,listing,paging);
  sourceNote(main,data);showList();draw();return ()=>{controller.abort();query.removeAttribute('aria-controls');};
}

export async function appendArtistEvidence({main,evidence,profile,load,id,isCurrent=()=>true}) {
  const data=await load(profile.pipeline_demo.path);if(!isCurrent())return;
  const artist=data.artists.find(a=>a.id===id);if(!artist)return;
  const byId=new Map(data.artists.map(a=>[a.id,a]));
  const heading=el('h2','Shared genres with');main.append(heading);
  if(artist.position)main.append(anchor('Locate on the map',`#map/source|${id}`));
  else main.append(el('p','No shared genre links.','scope'));
  const neighbors=data.source_edges.filter(e=>e.source===id||e.target===id);
  if(neighbors.length){const list=el('ul');for(const edge of neighbors){const other=byId.get(edge.source===id?edge.target:edge.source),item=el('li');item.append(artistLink(other),el('small',` · ${edge.genres.map(g=>data.genres[g]).join(', ')}`));list.append(item);}main.append(list);}

  const suggested=data.acoustic_edges.filter(e=>e.source===id);
  if(suggested.length)main.append(el('h2','Suggested'));
  if(suggested.length){

    const list=el('ul');for(const edge of suggested){
      const item=el('li');item.append(artistLink(byId.get(edge.target)));
      const details=el('details');details.append(el('summary',`${edge.observations.length} recording comparisons · frame ${edge.contract.slice(0,8)}, fold ${edge.fold}`));
      for(const observation of edge.observations){const a=data.recordings[observation.query_recording_mbid],b=data.recordings[observation.candidate_recording_mbid];const p=el('p');p.append(external(a.title,a.url),el('span',' → '),external(b.title,b.url),el('span',` · standardized distance ${observation.distance.toFixed(4)} (within this frame only)`));details.append(p);}item.append(details);list.append(item);
    }main.append(list,anchor('Open the acoustic layer',`#map/audio|${id}`));
  }
  const features=data.features.filter(row=>row.artists.includes(id));
  if(features.length){
    const panel=el('details');panel.append(el('summary',`Recording features and provenance (${features.length})`));
    for(const row of features){
      const section=el('details');section.append(el('summary',`${row.title??'Recording '+row.id.slice(0,8)} · ${row.outcome.replaceAll('_',' ')}`));
      const p=el('p');p.append(external('MusicBrainz recording',`https://musicbrainz.org/recording/${row.id}`),el('span',' · '),external('AcousticBrainz source',row.source_url));section.append(p);
      const table=el('table'),head=el('tr');head.append(el('th','Source coordinate'),el('th','Value'));table.append(head);
      for(const [i,column] of data.columns.entries()){const tr=el('tr');tr.append(el('td',`${column.path}${column.index===null?'':`[${column.index}]`}`),el('td',row.values[i]===null?'missing':String(row.values[i])));table.append(tr);}section.append(table);panel.append(section);
    }evidence.append(panel);
  }else evidence.append(el('p','No acoustic feature rows are retained for this artist.'));
}
