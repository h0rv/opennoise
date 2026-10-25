import {normalizeName} from './full-foundation-normalization.mjs';
import {mountListeningList} from './listening-list.mjs';
const main=document.querySelector('#main'),search=document.querySelector('#search'),form=document.querySelector('#search-form');
const listening=mountListeningList(document.querySelector('.header'));
const MBID=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
const link=(name,href)=>{const node=el('a',name);node.href=globalThis.OPENNOISE_LOCAL_FILES?.[href]?URL.createObjectURL(new Blob([JSON.stringify(globalThis.OPENNOISE_LOCAL_FILES[href],null,2)],{type:'application/json'})):href;return node;};
const external=(name,href)=>{const node=link(name,href);node.target='_blank';node.rel='noopener noreferrer';return node;};
const networkURL=id=>`artist-network/${globalThis.OPENNOISE_LOCAL_FILES?'OpenNoiseArtists.html':'index.html'}${id?'#artist/'+id:''}`;
const route=(kind,id='')=>`#${kind}/${encodeURIComponent(id)}`;
const name=row=>Array.isArray(row)?row[1]:row.name;
const identity=row=>Array.isArray(row)?row[0]:(row.artist_mbid??row.id);
const genreID=row=>row.genre_id??row.id;
let profile,genres,searchIndex,networkIndex,renderSequence=0,demoCleanup;
const demoModule=()=>Promise.resolve(globalThis.OPENNOISE_PIPELINE_DEMO??import('./pipeline-demo.mjs'));

const cache=new Map();
async function load(path,optional=false){if(globalThis.OPENNOISE_LOCAL_FILES){if(path in globalThis.OPENNOISE_LOCAL_FILES)return globalThis.OPENNOISE_LOCAL_FILES[path];if(optional)return null;throw Error(`Missing embedded file: ${path}`);}if(cache.has(path))return cache.get(path);const response=await fetch(path);if(optional&&response.status===404)return null;if(!response.ok)throw Error(`Cannot load ${path}: ${response.status}`);const data=await response.json();cache.set(path,data);if(cache.size>16)cache.delete(cache.keys().next().value);return data;}
function paragraph(text,className){const node=el('p',text);if(className)node.className=className;main.append(node);return node;}
function artistList(rows){const list=el('ul');list.className='artist-list';for(const row of rows){const item=el('li');item.append(link(name(row),route('artist',identity(row))));list.append(item);}if(!rows.length)list.append(el('li','No matching artists.'));main.append(list);}
function genreList(rows){const list=el('ul');list.className='genre-grid';for(const row of rows){const item=el('li'),anchor=link(row.name,route('genre',genreID(row)));anchor.append(el('small',`${row.artist_count??row.artist_mbids?.length??row.artists?.length??0} observed artists`));item.append(anchor);list.append(item);}main.append(list);}
function pagination(kind,page,total,size=500,query=''){
  if(total<=size)return;
  const nav=el('nav');nav.className='pagination';nav.setAttribute('aria-label','Pages');
  const pages=Math.max(1,Math.ceil(total/size)),href=p=>query?route(kind,`${query}|${p}`):route(kind,String(p));
  if(page>0)nav.append(link('First',href(0)),link('Previous',href(page-1)));
  nav.append(el('span',`Page ${page+1} of ${pages}`));
  if(page+1<pages)nav.append(link('Next',href(page+1)),link('Last',href(pages-1)));
  if(pages>2){const jump=el('form'),label=el('label','Page '),input=el('input');input.type='number';input.min='1';input.max=String(pages);input.value=String(page+1);input.style.width='6rem';label.append(input);const go=el('button','Go');jump.append(label,go);jump.addEventListener('submit',event=>{event.preventDefault();if(input.checkValidity())location.hash=href(Number(input.value)-1);});nav.append(jump);}
  main.append(nav);
}
function navigation(){
  const nav=document.querySelector('#music-navigation');nav.replaceChildren();
  const kind=location.hash.slice(1).split('/')[0];
  for(const [text,href,active] of [['Genres','#',!kind||kind==='genres'||kind==='genre-map'||kind==='genre'],['Artists',profile.pipeline_demo?networkURL(''):'#map/source',kind==='map'||kind==='artists'||kind==='artist']]){
    const item=link(text,href);if(active)item.setAttribute('aria-current','page');nav.append(item);
  }
}
function home(){main.append(el('h1','Genres'));if(profile.pipeline_demo){const nav=el('nav');nav.className='view-links';nav.append(link('Map','#'),link('List','#genres'));main.append(nav);}paragraph(`${(profile.counts?.artists??0).toLocaleString()} artist identities · ${(profile.counts?.artists_with_direct_genres??0).toLocaleString()} with observed genres.`,'scope');genreList(genres);if(profile.fma_catalog)main.append(link('FMA track catalog',profile.fma_catalog.path??'fma/'));if(profile.permitted_listening){paragraph('');main.append(link('Listen to licensed FMA clips',profile.permitted_listening.path??'fma-listening/'));}if(profile.fma_map){paragraph('');main.append(link('FMA sonic map',profile.fma_map.path??'fma-map/'));}}
function about(){
  main.append(el('h1','Sources'));
  paragraph('MusicBrainz identities and recording credits, Wikidata genre claims, and AcousticBrainz descriptors. Source metadata: CC0. Code: MIT.');
  if(profile.pipeline_demo){
    paragraph(`${profile.counts.genres} genres; ${profile.counts.artists_with_direct_genres} of ${profile.counts.artists} artists have observed genre claims. All identities remain searchable.`);
    paragraph('Genre positions group shared artists. Artist positions group shared genre claims. Neither map has musical axes or validated acoustic distances. Suggested links come from a separate, small descriptor subset and are unvalidated.');
    paragraph('Recordings preserve source titles and credits. They are examples from the retained catalog, not independently reviewed representatives. No audio playback is included.');
    main.append(link('Source ledger','pipeline.json'),el('span',' · '),link('Build receipt','receipt.json'));
  }else main.append(link('Source projection','profile.json'));
  const credit=el('p');credit.append(el('span','Interface reference: '),external('Every Noise at Once','https://everynoise.com/engenremap.html'),el('span',' by Glenn McDonald. OpenNoise is an independent reconstruction with different data.'));main.append(credit);
}
function recordingRows(rows){
  const seen=new Set(),titles=new Set();return rows.flatMap(row=>{
    const title=[row.title,row.display_title,row.name].find(value=>typeof value==='string'&&value.trim());
    const key=row.id??row.recording_mbid??row.url??title;
    if(!title||seen.has(key)||titles.has(normalizeName(title.trim())))return [];seen.add(key);titles.add(normalizeName(title.trim()));return [{...row,title:title.trim()}];
  });
}
async function artistDetail(id,sequence){
  if(!MBID.test(id)){missing('Invalid artist ID');return;}
  const bucket=await load(`artists/identity-${id.slice(0,2)}.json`);
  if(sequence!==renderSequence)return;
  const artist=(Array.isArray(bucket)?bucket:bucket.artists).find(row=>identity(row)===id);
  if(!artist){missing('Artist identity not found');return;}
  const detail=await load(`details/${id}.json`,true);let supplemental={};
  if(profile.research_contexts){const contexts=await load(`${profile.research_contexts.path}${id.slice(0,2)}.json`);supplemental=contexts[id]??{};}
  if(sequence!==renderSequence)return;
  main.append(el('h1',name(artist)));
  main.append(el('h2','Observed genres'));
  const observed=(detail?.direct_genres??detail?.genres??[]).map(row=>typeof row==='string'?genres.find(g=>genreID(g)===row):row).filter(Boolean);
  if(observed.length)genreList(observed);else paragraph(profile.pipeline_demo?'No observed genres.':'No direct genre evidence is available for this identity.','scope');
  const suggestions=supplemental.source_completion_proposals??detail?.suggested??[];
  if(suggestions.length){main.append(el('h2','Suggested from observed labels'));const list=el('ul');for(const suggestion of suggestions){const gid=suggestion.genre_qid??genreID(suggestion),genre=genres.find(row=>genreID(row)===gid),item=el('li');item.append(link(suggestion.name??genre?.name??gid,route('genre',gid)));list.append(item);}main.append(list);}
  main.append(el('h2','Recordings'));
  const recordings=recordingRows(detail?.recordings??[]);
  if(recordings.length){
    const list=el('ul');list.className='credits';
    for(const recording of recordings){
      const item=el('li');item.append(external(recording.title,recording.url??`https://musicbrainz.org/recording/${recording.id}`));
      for(const destination of recording.destinations??[]){const provider=new URL(destination.url).hostname.replace(/^www\./,'');item.append(el('span',' · '),external(`${provider} (availability unverified)`,destination.url));}
      const button=listening?.addButton(recording,id,name(artist));if(button)item.append(button);list.append(item);
    }main.append(list);
  }else paragraph('No recordings in this catalog.','scope');
  if(detail?.links?.length){main.append(el('h2','Artist links'));listening?.setArtistDestinations(id,detail.links);const list=el('ul');for(const destination of detail.links){const item=el('li');item.append(external(destination.provider,destination.url));list.append(item);}main.append(list);}
  const evidence=el('details');evidence.className='sources';evidence.append(el('summary','Sources'));
  const source=el('p');source.append(external('MusicBrainz artist',`https://musicbrainz.org/artist/${id}`),el('span',' · '),link('Source projection',`details/${id}.json`));evidence.append(source,el('p','Recording titles and artist credits are native source metadata. Examples are not independently reviewed representatives. Source metadata: CC0.'));
  if(Object.keys(supplemental).length)evidence.append(link('Suggestion and descriptor sources',`${profile.research_contexts.path}${id.slice(0,2)}.json`),el('p','Suggestions are unvalidated source-label completion. Descriptor positions are mathematical context.'));
  if(detail?.fma_track_context?.length){evidence.append(el('h2','FMA track context'),el('p','Native track annotations, separate from artist genres. FMA metadata: CC BY 4.0.'));for(const context of detail.fma_track_context){evidence.append(link(`FMA artist ${context.fma_artist_id}`,`fma/#artist=${context.fma_artist_id}`),el('p',context.attribution??'FMA dataset contributors; Defferrard et al., ISMIR 2017'));}}
  if(supplemental.fma_descriptor_context?.length)evidence.append(link('FMA sonic context','fma-map/'));
  if(profile.pipeline_demo){await(await demoModule()).appendArtistEvidence({main,evidence,profile,load,id,isCurrent:()=>sequence===renderSequence});if(sequence!==renderSequence)return;}
  main.append(evidence);
}
async function genreDetail(value,sequence){const [id,page]=splitQuery(value);const genre=genres.find(row=>genreID(row)===id);if(!genre){missing('Genre identity not found');return;}let members=genre.artists;if(!members){const cohort=await load(genre.path??`genres/${id}.json`);members=Array.isArray(cohort)?cohort:cohort.artists;}if(sequence!==renderSequence)return;if(profile.pipeline_demo){demoCleanup=await(await demoModule()).renderGenre({main,profile,load,genre,members,isCurrent:()=>sequence===renderSequence});return;}main.append(el('h1',genre.name));paragraph(`${members.length.toLocaleString()} directly observed artists in this build. Overlapping direct claims are retained.`,'scope');if(/^Q\d+$/.test(id))main.append(external('Wikidata genre',`https://www.wikidata.org/wiki/${id}`));const size=500;if(!Number.isInteger(page)||page<0||page>=Math.max(1,Math.ceil(members.length/size))){missing('Genre page not found');return;}pagination('genre',page,members.length,size,id);artistList(members.slice(page*size,(page+1)*size));pagination('genre',page,members.length,size,id);}
async function browse(page,sequence){const total=profile.counts.artists,size=profile.browse_page_size??500;const max=Math.max(0,Math.ceil(total/size)-1);if(!Number.isInteger(page)||page<0||page>max){missing('Artist page not found');return;}const data=await load(`browse/${String(page).padStart(6,'0')}.json`);if(sequence!==renderSequence)return;main.append(el('h1','All artists'));paragraph(`${total.toLocaleString()} artists`,'scope');pagination('artists',page,total,size);artistList(Array.isArray(data)?data:data.artists);pagination('artists',page,total,size);}
function splitQuery(value){const separator=value.lastIndexOf('|');return separator<0?[value,0]:[value.slice(0,separator),Number(value.slice(separator+1))];}
const compareNames=(left,right)=>{const a=[...left],b=[...right];for(let i=0;i<Math.min(a.length,b.length);i++){const difference=a[i].codePointAt(0)-b[i].codePointAt(0);if(difference)return difference;}return a.length-b.length;};
async function searchResults(value,sequence){
  const [query,page]=splitQuery(value);search.value=query;const normalized=normalizeName(query);
  if(profile.pipeline_demo)networkIndex??=await load('artist-network/catalog.json',true);if(sequence!==renderSequence)return;
  if(MBID.test(normalized)){if(networkIndex?.artists.some(row=>row.id===normalized)){location.href=networkURL(normalized);return;}await artistDetail(normalized,sequence);return;}
  main.append(el('h1',`Search: ${query}`));
  const matchingGenres=genres.filter(row=>normalizeName(row.name).includes(normalized)||genreID(row).toLowerCase()===normalized);
  if(matchingGenres.length){main.append(el('h2','Genres'));genreList(matchingGenres);}
  if(!normalized){paragraph('Enter an artist name prefix, a genre, or an exact MusicBrainz artist ID. Single-character names are searchable.');return;}
  if(networkIndex){const terms=normalized.split(/\s+/).filter(Boolean),rows=networkIndex.artists.filter(row=>terms.every(term=>normalizeName(row.name).includes(term))).sort((a,b)=>normalizeName(a.name).localeCompare(normalizeName(b.name))||a.id.localeCompare(b.id));const size=60;main.append(el('h2','Artists'));paragraph(`${rows.length.toLocaleString()} matches.`,'scope');if(!Number.isInteger(page)||page<0||page>=Math.max(1,Math.ceil(rows.length/size))){missing('Search page not found');return;}pagination('q',page,rows.length,size,query);const list=el('ul');list.className='artist-list';for(const row of rows.slice(page*size,(page+1)*size)){const item=el('li');item.append(link(row.name,networkURL(row.id)));list.append(item);}if(!rows.length)list.append(el('li','No matching artists.'));main.append(list);pagination('q',page,rows.length,size,query);return;}
  searchIndex??=await load('search/index.json');if(sequence!==renderSequence)return;
  const pages=searchIndex.pages.map((row,index)=>({path:`browse/${String(index).padStart(6,'0')}.json`,first:row[0],last:row[1],count:row[2],start:0,end:row[2]}));
  const searchRows=async metadata=>(await load(metadata.path)).map(row=>[normalizeName(row[1]),row[0],row[1]]);
  const sections=[];let count=0;
  for(const metadata of pages){
    if(compareNames(metadata.last,normalized)<0||(compareNames(metadata.first,normalized)>0&&!metadata.first.startsWith(normalized)))continue;
    let rows=null,length=metadata.count;
    if(!metadata.first.startsWith(normalized)||!metadata.last.startsWith(normalized)){
      rows=(await searchRows(metadata)).filter(row=>row[0].startsWith(normalized));length=rows.length;
      if(sequence!==renderSequence)return;
    }
    if(length){sections.push({metadata,rows,start:count,length});count+=length;}
  }
  const size=500;main.append(el('h2','Artists'));paragraph(`${count.toLocaleString()} name-prefix matches.`,'scope');
  if(!Number.isInteger(page)||page<0||page>=Math.max(1,Math.ceil(count/size))){missing('Search page not found');return;}
  const from=page*size,to=from+size,selected=[];
  for(const section of sections){if(section.start+section.length<=from||section.start>=to)continue;const rows=section.rows??await searchRows(section.metadata);if(sequence!==renderSequence)return;selected.push(...rows.slice(Math.max(0,from-section.start),Math.min(rows.length,to-section.start)).map(row=>[row[1],row[2]]));}
  pagination('q',page,count,size,query);artistList(selected);pagination('q',page,count,size,query);
}
function missing(text){main.append(el('h1',text));paragraph('Choose Genres, All artists, or search again.');}
async function render(){demoCleanup?.();demoCleanup=null;const sequence=++renderSequence;main.setAttribute('aria-busy','true');main.replaceChildren();navigation();paragraph('Loading…','loading');try{const value=location.hash.slice(1);const slash=value.indexOf('/');const kind=slash<0?value:value.slice(0,slash);const id=slash<0?'':decodeURIComponent(value.slice(slash+1));if((!kind||kind==='genre-map')&&profile.pipeline_demo){demoCleanup=await(await demoModule()).renderGenres({main,profile,genres,load,isCurrent:()=>sequence===renderSequence});}else if(kind==='map'&&profile.pipeline_demo){demoCleanup=await(await demoModule()).renderMap({main,profile,load,selected:id,isCurrent:()=>sequence===renderSequence});}else if(!kind||kind==='genres')home();else if(kind==='about')about();else if(kind==='artist')await artistDetail(id,sequence);else if(kind==='genre')await genreDetail(id,sequence);else if(kind==='artists')await browse(Number(id),sequence);else if(kind==='q')await searchResults(id,sequence);else missing('Page not found');if(sequence===renderSequence)document.title=`${main.querySelector('h1')?.textContent??'Music'} · OpenNoise`;}catch(error){if(sequence===renderSequence){main.replaceChildren();navigation();missing('This page could not load');paragraph('Check the source export, then reload.','scope');console.error(error);}}finally{if(sequence===renderSequence){main.querySelector('.loading')?.remove();main.setAttribute('aria-busy','false');}}}
document.querySelector('.skip').addEventListener('click',event=>{event.preventDefault();main.focus();});
form.addEventListener('submit',event=>{event.preventDefault();const hash=route('q',search.value.trim());if(location.hash===hash)render();else location.hash=hash;});
window.addEventListener('hashchange',()=>{render();main.focus({preventScroll:true});});
try{[profile,genres]=await Promise.all([load('profile.json'),load('genres.json')]);genres=Array.isArray(genres)?genres:genres.genres;if(profile.pipeline_demo){const toggle=document.querySelector('.listening-list-toggle');if(toggle)document.querySelector('footer').append(el('span',' · '),toggle);}await render();}catch(error){main.replaceChildren(el('h1','Catalog unavailable'),el('p','Check the build receipt and reload the complete export.'));console.error(error);}
