"""Conservative, minimized local candidate; never authorizes deployment."""

from __future__ import annotations

# ruff: noqa: E501 -- self-contained minimal candidate page.
import hashlib
import json
import re
import resource
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from opennoise.deployment.fma_genre_discovery import genre_index
from opennoise.deployment.fma_playback import validate_playback_export

REVISION = "fma-declared-license-candidate-v1"
MAX_CLIPS = 64
MAX_AUDIO_BYTES = 64_000_000
MAX_CLIP_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 200_000
MAX_EVIDENCE_BYTES = 2_000_000
CREDIT_FIELDS = (
    "title",
    "artist_name",
    "license_title",
    "license_url",
    "source_url",
    "attribution",
    "composer",
    "copyright_c",
    "copyright_p",
)
NOTICE_FIELDS = ("copyright", "composer", "TSOC", "TEXT", "album_artist", "TOPE")
CHECKS = ("credits_reviewed", "source_url_reviewed", "privacy_reviewed", "no_contrary_notice")
CC_URL = re.compile(r"https?://creativecommons\.org/(?:licenses|publicdomain)/[a-zA-Z0-9./-]+")
CONTACT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:mailto:|paypal|venmo|cashapp|bitcoin:|iban\b)",
    re.IGNORECASE,
)


def _read(path: Path, cap: int = MAX_EVIDENCE_BYTES) -> Any:  # noqa: ANN401 -- bounded external JSON.
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > cap
    ):
        raise ValueError("Evidence file missing, symlinked or oversized")
    return json.loads(path.read_bytes())


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _texts(value: Any) -> list[str]:  # noqa: ANN401 -- recursive bounded JSON.
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for child in value.values() for s in _texts(child)]
    if isinstance(value, list):
        return [s for child in value for s in _texts(child)]
    return []


def _normal(url: str) -> str:
    return url.replace("https://", "http://").rstrip("/")


def _probe_limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512_000_000, 512_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))


def _probe(path: Path) -> dict[str, Any]:
    binary = shutil.which("ffprobe")
    if not binary:
        raise ValueError("Offline ffprobe required for embedded evidence replay")
    result = subprocess.run(  # noqa: S603 -- fixed offline probe arguments.
        [
            binary,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-f",
            "mp3",
            "-show_entries",
            "format_tags:stream_tags",
            "-of",
            "json",
            str(path.resolve()),
        ],
        capture_output=True,
        check=True,
        timeout=10,
        preexec_fn=_probe_limits,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "OPENBLAS_NUM_THREADS": "1"},
    )
    if len(result.stdout) > MAX_MANIFEST_BYTES:
        raise ValueError("Embedded tags exceed evidence bound")
    return json.loads(result.stdout)


def project_track(  # noqa: C901, PLR0912 -- explicit attribution gates.
    native: dict[str, Any], decision: dict[str, Any], tags: dict[str, Any]
) -> dict[str, Any]:
    """Require matching supplied declarations and reviewed exact credits, not absent ID3."""
    strings = _texts(tags)
    urls = {url for text in strings for url in CC_URL.findall(text)}
    if not urls or any(_normal(url) != _normal(native["license_url"]) for url in urls):
        raise ValueError("Missing or conflicting embedded license evidence")
    if any(CONTACT.search(text) for text in strings):
        raise ValueError("Embedded contact or payment content requires resolution")
    if (
        decision.get("status") != "include"
        or decision.get("audio_sha256") != native["audio_sha256"]
        or decision.get("track_id") != native["track_id"]
        or decision.get("checks") != dict.fromkeys(CHECKS, True)
    ):
        raise ValueError("Track lacks exact reviewed inclusion evidence")
    credit = decision.get("required_credit_fields", {})
    if set(credit) != set(CREDIT_FIELDS) | {
        "embedded_notices",
        "embedded_source_urls",
        "embedded_curators",
    }:
        raise ValueError("Credit projection fields differ from allowlist")
    if any(credit.get(key) != native[key] for key in CREDIT_FIELDS):
        raise ValueError("Required native credit changed or omitted")
    embedded = tags.get("format", {}).get("tags", {})
    notices = {
        key: embedded[key] for key in NOTICE_FIELDS if embedded.get(key) and embedded[key] != "null"
    }
    if credit["embedded_notices"] != notices:
        raise ValueError("Required embedded credit changed or omitted")
    comments = embedded.get("comment", "").splitlines()
    source_urls = [line[5:].strip() for line in comments if line.startswith("URL: ")]
    curators = [
        line.split(":", 1)[1].strip()
        for line in comments
        if line.startswith(("Curator:", "Curators:")) and line.split(":", 1)[1].strip()
    ]
    if credit["embedded_source_urls"] != source_urls or credit["embedded_curators"] != curators:
        raise ValueError("Supplied embedded source or curator attribution omitted")
    for line in comments:
        if line.startswith(("Composer:", "Copyright:")):
            supplied = line.split(":", 1)[1].strip()
            if supplied not in ("", "null") and supplied not in notices.values():
                raise ValueError("Additional comment credit requires explicit projection review")
    if embedded.get("publisher") not in (None, "", "null"):
        raise ValueError("Publisher credit requires explicit projection review")
    for stream in tags.get("streams", []):
        if any(key != "encoder" and value for key, value in stream.get("tags", {}).items()):
            raise ValueError("Additional stream credit requires explicit projection review")
    for key in ("embedded_source_urls", "embedded_curators"):
        values = credit[key]
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or any(
                not isinstance(v, str) or not v or not any(v in text for text in strings)
                for v in values
            )
        ):
            raise ValueError("Embedded provenance is not supplied in retained tags")
    for value in [credit["source_url"], *credit["embedded_source_urls"]]:
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or url.hostname not in {"freemusicarchive.org", "www.freemusicarchive.org"}
                or url.username
                or url.password
            ):
                raise ValueError("Source URL outside native source domain")
    if any(CONTACT.search(text) for text in _texts(credit)):
        raise ValueError("Public metadata contains contact or payment content")
    return (
        {
            key: native[key]
            for key in ("track_id", "artist_id", "audio_sha256", "audio_bytes", "duration_seconds")
        }
        | credit
        | {
            "audio_path": f"audio/{native['track_id']}.mp3",
            "license_evidence": "matching_supplied_declarations",
            "embedded_extra_text_present": any("lyric" in key.lower() for key in embedded),
        }
    )


def build_candidate(  # noqa: C901, PLR0912, PLR0915 -- ordered custody gates.
    site: Path, audit_directory: Path, decisions_path: Path, output: Path, decision_sha256: str
) -> dict[str, Any]:
    """Build a fresh <=64-clip review artifact with strict attribution projection."""
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Candidate output must be fresh and nonsymlinked")
    decisions = _read(decisions_path)
    if _hash(decisions_path) != decision_sha256:
        raise ValueError("Frozen review decision hash differs")
    for name, digest in decisions["input_hashes"].items():
        if Path(name).name != name or _hash(audit_directory / name) != digest:
            raise ValueError("Audit evidence binding differs")
    comparison = _read(audit_directory / "embedded-license-comparison.json")
    if decisions["audit_sha256"] != _hash(audit_directory / "embedded-license-comparison.json"):
        raise ValueError("License audit binding differs")
    audited = {row["track_id"]: row for row in comparison["records"]}
    tag_rows = _read(audit_directory / "embedded-audio-tags.json")
    tags = {row["track_id"]: row["tags"] for row in tag_rows}
    index = genre_index(site)
    native = {}
    paths = {}
    parents = {}
    for origin in ("original", "expanded", "coverage"):
        base = site / origin / "audio"
        manifest = validate_playback_export(base)
        parents[origin] = _hash(base / "manifest.json")
        for key, track in manifest["tracks"].items():
            if key in native and native[key] != track:
                raise ValueError("Conflicting duplicate native playback identity")
            native[key] = track
            paths[key] = base / track["audio_path"]
    selected = [r for r in decisions["records"] if r["status"] == "include"]
    if not 0 < len(selected) <= MAX_CLIPS or len({r["track_id"] for r in selected}) != len(
        selected
    ):
        raise ValueError("Candidate roster exceeds bounds or duplicates IDs")
    projected = []
    total = 0
    for decision in sorted(selected, key=lambda r: r["track_id"]):
        key = str(decision["track_id"])
        track = native[key]
        audit = audited[track["track_id"]]
        if (
            audit["status"] != "matching_declaration"
            or audit["audio_sha256"] != track["audio_sha256"]
            or audit["declared_license_url"] != track["license_url"]
        ):
            raise ValueError("Candidate includes held or misbound audit record")
        fresh = _probe(paths[key])
        if fresh != tags[track["track_id"]]:
            raise ValueError("Embedded tag evidence differs from actual bytes")
        row = project_track(track, decision, fresh)
        facts = index["tracks"][key]
        if (
            facts["artist_id"] != row["artist_id"]
            or facts["title"] != row["title"]
            or facts["artist_name"] != row["artist_name"]
        ):
            raise ValueError("Catalog identity differs from playback")
        row["genre_ids"] = facts["genre_ids"]
        projected.append(row)
        total += track["audio_bytes"]
    if total > MAX_AUDIO_BYTES:
        raise ValueError("Candidate audio exceeds original64MB bound")
    used_genres = {g for row in projected for g in row["genre_ids"]}
    manifest = {
        "revision": REVISION,
        "public_deployment_authorized": False,
        "source_evidence_gate": "passed_matching_declarations_and_reviewed_attribution",
        "rights_warranty": False,
        "metadata_license": "CC-BY-4.0",
        "metadata_attribution": {
            "creators": "Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst, Xavier Bresson",
            "title": "FMA: A Dataset For Music Analysis",
            "source_url": "https://github.com/mdeff/fma",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "changes": "Selected native tracks and genres; omitted contact/payment/freeform fields; retained source credits and separate embedded notices.",
        },
        "decision_sha256": decision_sha256,
        "parent_manifest_sha256": parents,
        "audio_bytes": total,
        "tracks": projected,
        "genres": [
            {"genre_id": g["genre_id"], "title": g["title"]}
            for g in index["genres"]
            if g["genre_id"] in used_genres
        ],
        "limitations": [
            "Matching supplied declarations are evidence, not a warranty of uploader authority.",
            "Missing and conflicting declarations are excluded.",
            "Original MP3 bytes preserve embedded tags; extra text is flagged but not projected.",
            "No public upload or deployment authorized by this receipt.",
        ],
    }
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Candidate metadata exceeds200KB")
    output.mkdir(parents=True)
    (output / "audio").mkdir()
    for row in projected:
        data = paths[str(row["track_id"])].read_bytes()
        if (
            len(data) != row["audio_bytes"]
            or hashlib.sha256(data).hexdigest() != row["audio_sha256"]
        ):
            raise ValueError("Audio changed during export")
        (output / row["audio_path"]).write_bytes(data)
    (output / "manifest.json").write_bytes(payload)
    (output / "index.html").write_text(PAGE)
    validate_candidate(output, hashlib.sha256(payload).hexdigest())
    return manifest


PAGE = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenNoise — genres</title>
<style>
body{font:17px/1.5 system-ui;margin:auto;max-width:1000px;padding:20px;color:#222;background:#fff}input,button{font:inherit;padding:8px}input{box-sizing:border-box;width:100%;max-width:650px}a{color:#15518a;overflow-wrap:anywhere}button,a,input{touch-action:manipulation}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #185c9c;outline-offset:3px}nav{display:flex;gap:20px;margin:12px 0}li{padding:10px 0;border-bottom:1px solid #ccc}ul{padding-left:20px}small{display:block;color:#555}audio{width:100%}#player{background:#fff;border-block:1px solid #aaa;padding:12px 0;margin:18px 0}#player p{margin:4px 0}h1{font-size:1.7rem;margin:8px 0}h2{font-size:1.35rem}.credit-link{margin-right:12px}details{margin:16px 0}#results li>a:first-child{font-size:1.1rem}.play{margin:8px 10px 0 0}.skip{position:absolute;left:-10000px}.skip:focus{position:static}#error{color:#8a2010}#main{scroll-margin-top:10px}@media(max-width:600px){body{padding:14px}nav{gap:15px}button{min-height:44px}}
</style>
<body>
<a class="skip" href="#main">Skip to music</a>
<header><h1><a href="#genres">OpenNoise</a></h1><nav aria-label="Browse"><a href="#genres">Genres</a><a href="#artists">Artists</a><a href="#tracks">Tracks</a></nav></header>
<section id="player" aria-label="Player"><audio controls preload="none"></audio><p id="credit" aria-live="polite">Choose an excerpt. Nothing plays automatically.</p><div id="notices"></div><button id="stop">Stop</button><p id="error" role="alert"></p></section>
<label id="search-label">Search genres <input id="search" type="search" maxlength="200" autocomplete="off"></label>
<main id="main" tabindex="-1" aria-busy="true"><p>Loading genres…</p></main>
<details id="about"><summary>About and sources</summary><p>This subset contains matching supplied license declarations and reviewed credits, not a rights warranty. Local candidate only; no deployment authorized. Original audio bytes remain unchanged. Counts refer to distinct recordings and artists in this subset, not the full FMA catalog. Genre links are supplied track tags, not model predictions.</p><p>Metadata: <a href="https://github.com/mdeff/fma">FMA: A Dataset For Music Analysis</a>, Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier Bresson; <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Selected subset and minimized fields; source credits preserved.</p></details>
<script>
'use strict';
const q=selector=>document.querySelector(selector), audio=q('audio');
let data=null, loading=false, playbackVersion=0;
const node=(tag,text)=>{const element=document.createElement(tag);element.textContent=text;return element;};
const nativeId=value=>Number.isSafeInteger(value)&&value>0;
function route(){
  const [path,query='']=location.hash.slice(1).split('?'), params=new URLSearchParams(query);
  if(!path||['genres','artists','tracks'].includes(path))return {kind:path||'genres',search:(params.get('q')||'').slice(0,200)};
  const match=/^(genre|artist|track)\/([1-9][0-9]*)$/.exec(path);
  return match&&nativeId(Number(match[2]))?{kind:match[1],id:Number(match[2])}:{kind:'invalid'};
}
function anchor(title,href){const a=node('a',title);a.href=href;return a;}
function external(container,title,url){if(url){const a=anchor(title,url);a.rel='noreferrer';a.className='credit-link';container.append(a);}}
function play(row){
  const version=++playbackVersion;audio.pause();q('#error').textContent='';
  const credit=q('#credit');credit.replaceChildren(anchor(row.title+' — '+row.artist_name,'#track/'+row.track_id),node('small',row.attribution));
  const notices=q('#notices');notices.replaceChildren();external(notices,'License',row.license_url);
  if(row.source_url)external(notices,'Native source',row.source_url);else notices.append(node('small','Native source URL unknown.'));
  for(const url of row.embedded_source_urls)if(url!==row.source_url)external(notices,'Supplied embedded source',url);
  for(const key of ['composer','copyright_c','copyright_p'])if(row[key])notices.append(node('small',key+': '+row[key]));
  for(const [key,value] of Object.entries(row.embedded_notices))notices.append(node('small',key+': '+value));
  if(row.embedded_curators.length)notices.append(node('small','Supplied curators: '+row.embedded_curators.join('; ')));
  if(row.embedded_extra_text_present)notices.append(node('small','Original audio contains additional embedded text; it is not displayed here.'));
  audio.src=row.audio_path;
  audio.play().catch(()=>{if(version===playbackVersion)q('#error').textContent='Playback failed. Choose the excerpt again to retry.';});
}
function playButton(row){const b=node('button','Play');b.className='play';b.dataset.playTrack=row.track_id;b.setAttribute('aria-label','Play '+row.title+' — '+row.artist_name);b.onclick=()=>play(row);return b;}
function list(){const ul=node('ul','');ul.id='results';return ul;}
function trackList(rows){
  const ul=list();for(const row of rows){const li=node('li','');li.dataset.trackId=row.track_id;
    li.append(anchor(row.title,'#track/'+row.track_id),document.createTextNode(' — '),anchor(row.artist_name,'#artist/'+row.artist_id),node('small','Native track '+row.track_id));
    li.append(playButton(row));ul.append(li);
  }return ul;
}
function genreLinks(rows){
  const ids=new Set(rows.flatMap(row=>row.genre_ids));const p=node('p','Genres: ');
  for(const genre of data.genres.filter(g=>ids.has(g.genre_id))){p.append(anchor(genre.title,'#genre/'+genre.genre_id),document.createTextNode(' · '));}
  if(!ids.size)p.append(document.createTextNode('No supplied genre tags.'));return p;
}
function notFound(){q('#main').append(node('h2','Not found'),node('p','This link does not identify an item in this subset.'),anchor('Browse genres','#genres'));}
function render(){
  if(!data)return;
  const state=route(),main=q('#main'),label=q('#search-label'),input=q('#search');main.replaceChildren();main.setAttribute('aria-busy','false');main.dataset.route=location.hash;document.documentElement.dataset.candidateReady='true';
  const directory=['genres','artists','tracks'].includes(state.kind);label.hidden=!directory;
  if(directory){label.firstChild.textContent='Search '+state.kind+' ';input.value=state.search;input.setAttribute('aria-label','Search '+state.kind);}
  document.querySelectorAll('nav a').forEach(a=>{if(a.hash==='#'+state.kind)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  const term=(state.search||'').toLocaleLowerCase();
  if(state.kind==='genres'){
    main.append(node('h2','Genres'));const ul=list();let count=0;
    for(const genre of data.genres){if(!(`${genre.title} ${genre.genre_id}`.toLocaleLowerCase().includes(term)))continue;
      const rows=data.tracks.filter(r=>r.genre_ids.includes(genre.genre_id)),artists=new Set(rows.map(r=>r.artist_id));
      const li=node('li','');li.dataset.genreId=genre.genre_id;li.dataset.trackCount=rows.length;li.dataset.artistCount=artists.size;
      li.append(anchor(genre.title,'#genre/'+genre.genre_id),node('small',`${rows.length} excerpts · ${artists.size} artists`));ul.append(li);count++;
    }main.append(node('p',`${count} of ${data.genres.length} genres`),ul);if(!count)main.append(node('p','No matching genres. Clear Search to see every genre.'));
  }else if(state.kind==='artists'){
    main.append(node('h2','Artists'));const ul=list();const artists=[...new Map(data.tracks.map(r=>[r.artist_id,r.artist_name]))].sort((a,b)=>a[1].localeCompare(b[1])||a[0]-b[0]);let count=0;
    for(const [id,name] of artists){if(!(`${name} ${id}`.toLocaleLowerCase().includes(term)))continue;const rows=data.tracks.filter(r=>r.artist_id===id),li=node('li','');li.dataset.artistId=id;li.dataset.trackCount=rows.length;li.append(anchor(name,'#artist/'+id),node('small',`${rows.length} excerpts`));ul.append(li);count++;}
    main.append(node('p',`${count} of ${artists.length} artists`),ul);if(!count)main.append(node('p','No matching artists. Clear Search to see every artist.'));
  }else if(state.kind==='tracks'){
    const rows=data.tracks.filter(r=>(`${r.title} ${r.artist_name} ${r.track_id}`).toLocaleLowerCase().includes(term));main.append(node('h2','Tracks'),node('p',`${rows.length} of ${data.tracks.length} excerpts`),trackList(rows));if(!rows.length)main.append(node('p','No matching tracks. Clear Search to see every track.'));
  }else if(state.kind==='genre'){
    const genre=data.genres.find(g=>g.genre_id===state.id);if(!genre){notFound();return;}
    const rows=data.tracks.filter(r=>r.genre_ids.includes(state.id));main.append(node('h2',genre.title),node('p',`${rows.length} excerpts · ${new Set(rows.map(r=>r.artist_id)).size} artists`),trackList(rows));
  }else if(state.kind==='artist'){
    const rows=data.tracks.filter(r=>r.artist_id===state.id);if(!rows.length){notFound();return;}
    main.append(node('h2',rows[0].artist_name),node('p',`${rows.length} excerpts · Native artist ${state.id}`),genreLinks(rows),trackList(rows));
  }else if(state.kind==='track'){
    const row=data.tracks.find(r=>r.track_id===state.id);if(!row){notFound();return;}
    main.append(node('h2',row.title),anchor(row.artist_name,'#artist/'+row.artist_id),node('p','Native track '+row.track_id),genreLinks([row]),playButton(row),node('p',row.attribution));
    external(main,'License',row.license_url);if(row.source_url)external(main,'Native source',row.source_url);else main.append(node('p','Native source URL unknown.'));
  }else notFound();
  document.documentElement.dataset.candidateReady='true';
}
function validate(value){
  if(value.revision!=='fma-declared-license-candidate-v1'||value.public_deployment_authorized!==false||!Array.isArray(value.tracks)||!value.tracks.length||value.tracks.length>64||!Array.isArray(value.genres)||value.genres.length>164)throw Error('Invalid candidate');
  const ids=new Set(),genres=new Set();
  for(const genre of value.genres){if(!nativeId(genre.genre_id)||genres.has(genre.genre_id)||typeof genre.title!=='string')throw Error('Invalid genre');genres.add(genre.genre_id);}
  for(const row of value.tracks){
    if(!nativeId(row.track_id)||!nativeId(row.artist_id)||ids.has(row.track_id)||row.audio_path!==`audio/${row.track_id}.mp3`||!Array.isArray(row.genre_ids)||new Set(row.genre_ids).size!==row.genre_ids.length||row.genre_ids.some(id=>!genres.has(id)))throw Error('Invalid identity');ids.add(row.track_id);
    for(const field of ['title','artist_name','attribution','license_url','source_url','composer','copyright_c','copyright_p'])if(typeof row[field]!=='string')throw Error('Invalid credit');
    if(!Array.isArray(row.embedded_source_urls)||!Array.isArray(row.embedded_curators)||!row.embedded_notices||typeof row.embedded_notices!=='object'||Array.isArray(row.embedded_notices))throw Error('Invalid embedded credit');
    for(const url of [row.license_url,row.source_url,...row.embedded_source_urls])if(url&&!/^https?:\/\//.test(url))throw Error('Unsafe link');
  }
  return value;
}
async function initialize(){
  if(loading)return;loading=true;q('#main').setAttribute('aria-busy','true');q('#main').replaceChildren(node('p','Loading genres…'));
  try{const response=await fetch('manifest.json');if(!response.ok)throw Error('Unavailable');const text=await response.text();if(new TextEncoder().encode(text).length>200000)throw Error('Oversized');data=validate(JSON.parse(text));render();}
  catch{const retry=node('button','Retry');retry.onclick=initialize;q('#main').replaceChildren(node('p','Candidate metadata could not be loaded.'),retry);q('#main').setAttribute('aria-busy','false');}
  finally{loading=false;}
}
q('#stop').onclick=()=>{playbackVersion++;audio.pause();audio.removeAttribute('src');audio.load();q('#error').textContent='';};
q('.skip').onclick=event=>{event.preventDefault();q('#main').focus();};
q('#search').addEventListener('input',()=>{const state=route();if(!['genres','artists','tracks'].includes(state.kind))return;const value=q('#search').value.slice(0,200);history.replaceState(null,'','#'+state.kind+(value?'?q='+encodeURIComponent(value):''));render();});
window.addEventListener('hashchange',render);initialize();
</script></body></html>
"""

LEGACY_PAGE_SHA256 = "fd4d39166545daa0688276bea9c1fa21857c5cf38a2fca77d6b5f6527c41fde9"
REVIEWED_MANIFEST_SHA256 = "242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf"


def validate_candidate(directory: Path, manifest_sha256: str) -> dict[str, Any]:
    """Verify the current page only; historical migration has a separate pinned entry point."""
    return _validate_candidate(
        directory, manifest_sha256, hashlib.sha256(PAGE.encode()).hexdigest()
    )


def _validate_candidate(directory: Path, manifest_sha256: str, page_sha256: str) -> dict[str, Any]:  # noqa: C901 -- unchanged closed artifact checks.
    """Verify a reviewer's exact manifest pin and closed byte-preserving candidate."""
    manifest = _read(directory / "manifest.json", MAX_MANIFEST_BYTES)
    if (
        _hash(directory / "manifest.json") != manifest_sha256
        or manifest.get("revision") != REVISION
        or manifest.get("public_deployment_authorized") is not False
        or manifest.get("rights_warranty") is not False
        or manifest.get("source_evidence_gate")
        != "passed_matching_declarations_and_reviewed_attribution"
    ):
        raise ValueError("Candidate manifest pin or scope differs")
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not 0 < len(tracks) <= MAX_CLIPS:
        raise ValueError("Invalid candidate track count")
    allowed = set(CREDIT_FIELDS) | {
        "track_id",
        "artist_id",
        "audio_sha256",
        "audio_bytes",
        "duration_seconds",
        "audio_path",
        "genre_ids",
        "embedded_notices",
        "embedded_source_urls",
        "embedded_curators",
        "license_evidence",
        "embedded_extra_text_present",
    }
    expected = {"manifest.json", "index.html"}
    seen = set()
    total = 0
    for row in tracks:
        tid = row.get("track_id")
        size = row.get("audio_bytes")
        name = f"audio/{tid}.mp3"
        if (
            set(row) != allowed
            or type(tid) is not int
            or tid <= 0
            or tid in seen
            or row.get("audio_path") != name
            or type(size) is not int
            or not 0 < size <= MAX_CLIP_BYTES
        ):
            raise ValueError("Candidate projection or audio identity differs")
        seen.add(tid)
        path = directory / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != size
            or _hash(path) != row["audio_sha256"]
        ):
            raise ValueError("Candidate audio bytes differ")
        expected.add(name)
        total += size
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlinked candidate content")
        if path.is_file():
            actual.add(path.relative_to(directory).as_posix())
        elif path != directory / "audio":
            raise ValueError("Unexpected candidate directory")
    if (
        total > MAX_AUDIO_BYTES
        or total != manifest.get("audio_bytes")
        or actual != expected
        or _hash(directory / "index.html") != page_sha256
    ):
        raise ValueError("Candidate inventory or budget differs")
    return manifest


def rebuild_candidate(prior: Path, output: Path, manifest_sha256: str) -> dict[str, Any]:
    """Migrate only the exact reviewed candidate page; preserve every manifest/audio byte."""
    if manifest_sha256 != REVIEWED_MANIFEST_SHA256:
        raise ValueError("Migration requires the exact reviewed 55-recording manifest pin")
    page_hash = _hash(prior / "index.html")
    if page_hash not in {LEGACY_PAGE_SHA256, hashlib.sha256(PAGE.encode()).hexdigest()}:
        raise ValueError("Prior page is not an explicitly pinned migration input")
    manifest = _validate_candidate(prior, manifest_sha256, page_hash)
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError("Migration output must be fresh and nonsymlinked")
    output.mkdir(parents=True)
    (output / "audio").mkdir()
    for row in manifest["tracks"]:
        shutil.copyfile(prior / row["audio_path"], output / row["audio_path"])
    shutil.copyfile(prior / "manifest.json", output / "manifest.json")
    (output / "index.html").write_text(PAGE)
    validate_candidate(output, manifest_sha256)
    return manifest
