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


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OpenNoise — reviewed source-evidence subset</title><style>body{font:17px/1.5 system-ui;margin:auto;max-width:1000px;padding:20px}input,select,button{font:inherit;padding:8px;max-width:100%}label{display:inline-block;margin:8px}li{padding:12px 0;border-bottom:1px solid #aaa}audio{width:100%}#player{position:sticky;top:0;background:white;padding:12px;border:1px solid #888}a{overflow-wrap:anywhere}button:focus-visible,a:focus-visible{outline:3px solid #185c9c}small{display:block}</style><body><h1>OpenNoise: reviewed source-evidence subset</h1><p>Matching supplied license declarations and reviewed credits. This is not a rights warranty. Local candidate only; no deployment authorized. Original audio bytes remain unchanged.</p><section id="player" aria-label="Player"><audio controls preload="none"></audio><p id="credit" aria-live="polite">Choose an excerpt. Nothing plays automatically.</p><div id="notices"></div><button id="stop">Stop</button></section><p>Metadata: <a href="https://github.com/mdeff/fma">FMA: A Dataset For Music Analysis</a>, Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier Bresson; <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Selected subset and minimized fields; source credits preserved.</p><main><label>Search title or artist <input id="search" type="search"></label><label>Genre <select id="genre"><option value="">All genres</option></select></label><label>Artist <select id="artist"><option value="">All artists</option></select></label><p id="count" aria-live="polite"></p><ul id="tracks"></ul><p id="error" role="alert"></p></main><script>
'use strict';const q=s=>document.querySelector(s),audio=q('audio');let rows=[];
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
function link(container,title,url){if(!url)return;const a=node('a',title);a.href=url;a.rel='noreferrer';container.append(a,document.createTextNode(' '));}
function play(row){audio.pause();q('#credit').textContent=row.attribution;const notices=q('#notices');notices.replaceChildren();link(notices,'License',row.license_url);if(row.source_url)link(notices,'Native source',row.source_url);else notices.append(node('span','Native source URL unknown. '));for(const url of row.embedded_source_urls)if(url!==row.source_url)link(notices,'Supplied embedded source',url);for(const key of ['composer','copyright_c','copyright_p'])if(row[key])notices.append(node('small',key+': '+row[key]));for(const [key,value] of Object.entries(row.embedded_notices))notices.append(node('small',key+': '+value));if(row.embedded_curators.length)notices.append(node('small','Supplied curators: '+row.embedded_curators.join('; ')));if(row.embedded_extra_text_present)notices.append(node('small','Original audio contains additional embedded text; it is not displayed here.'));audio.src=row.audio_path;audio.play().catch(()=>{q('#error').textContent='Playback failed. Choose the excerpt again to retry.';});}
function render(){const term=q('#search').value.toLowerCase(),genre=Number(q('#genre').value),artist=Number(q('#artist').value);const matches=rows.filter(r=>(!term||(r.title+' '+r.artist_name+' '+r.track_id).toLowerCase().includes(term))&&(!genre||r.genre_ids.includes(genre))&&(!artist||r.artist_id===artist));q('#count').textContent=matches.length+' of '+rows.length+' excerpts';q('#tracks').replaceChildren(...matches.map(r=>{const li=node('li','');li.dataset.trackId=r.track_id;const b=node('button','Play '+r.title+' — '+r.artist_name);b.addEventListener('click',()=>play(r));li.append(b,node('small','Native track '+r.track_id+' · '+r.license_title));return li;}));}
q('#stop').onclick=()=>{audio.pause();audio.removeAttribute('src');audio.load();};for(const id of ['search','genre','artist'])q('#'+id).addEventListener('input',render);
fetch('manifest.json').then(r=>{if(!r.ok)throw Error('manifest unavailable');return r.json();}).then(data=>{if(data.revision!=='fma-declared-license-candidate-v1'||data.public_deployment_authorized!==false||!Array.isArray(data.tracks)||data.tracks.length>64)throw Error('invalid candidate');rows=data.tracks;for(const g of data.genres){const o=node('option',g.title);o.value=g.genre_id;q('#genre').append(o);}for(const [id,name] of [...new Map(rows.map(r=>[r.artist_id,r.artist_name]))].sort((a,b)=>a[1].localeCompare(b[1]))){const o=node('option',name);o.value=id;q('#artist').append(o);}render();}).catch(()=>{q('#error').textContent='Candidate metadata could not be loaded.';});
</script></body></html>"""


def validate_candidate(directory: Path, manifest_sha256: str) -> dict[str, Any]:  # noqa: C901 -- closed artifact checks.
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
        or (directory / "index.html").read_bytes() != PAGE.encode()
    ):
        raise ValueError("Candidate inventory or budget differs")
    return manifest
