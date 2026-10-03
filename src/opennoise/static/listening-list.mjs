/** A local list of exact credited metadata. No media lookup or provider requests. */
const MBID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const KEY = 'opennoise-listening-list-v1';
const LIMIT = 200;
function artistDestinations(artistId, rows) {
  return (Array.isArray(rows) ? rows : []).filter(row => MBID.test(artistId) && /^[a-f0-9]{64}$/.test(row.source_sha256) && typeof row.provider === 'string' && typeof row.relation_type === 'string' && (() => { try { const url = new URL(row.url); return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443'); } catch { return false; } })()).map(row => ({url: row.url, provider: row.provider, relation_type: row.relation_type, source_sha256: row.source_sha256, scope: 'artist_destination_not_recording_playback'}));
}
export function creditedRecording(row, artistId, artistName = '') {
  const id = row?.recording_mbid ?? row?.entity_id?.replace(/^musicbrainz:recording:/, '');
  const refs = row?.evidence_refs ?? (/^[a-f0-9]{64}$/.test(row?.source_sha256) ? [`sha256:${row.source_sha256}`] : []);
  if (!MBID.test(id) || !MBID.test(artistId) || !Array.isArray(row.credited_artist_mbids) || !row.credited_artist_mbids.includes(artistId) || !row.credited_artist_mbids.every(id => MBID.test(id)) || typeof row.title !== 'string' || !row.title.trim() || row.url !== `https://musicbrainz.org/recording/${id}` || !Array.isArray(refs) || !refs.length || !refs.every(ref => typeof ref === 'string' && ref.length)) return null;
  return {recording_mbid: id, title: row.title, artist_mbid: artistId, artist_name: artistName, credited_artist_mbids: [...row.credited_artist_mbids], evidence_refs: [...refs], metadata_url: row.url, audio_url: null, playback_availability: 'not_resolved', artist_destinations: []};
}
export function listeningExport(tracks) {
  return {schema: 'opennoise-listening-list-v1', scope: 'user_selected_exact_credit_metadata', musical_fit: 'not_assessed', playback_availability: 'not_resolved', tracks};
}
export function listeningTSV(tracks) {
  const cell = value => { const text = String(value ?? '').replace(/[\t\r\n]/g, ' '); return /^[=+@-]/.test(text) ? `'${text}` : text; };
  const columns = ['recording_mbid', 'title', 'artist_mbid', 'artist_name', 'credited_artist_mbids', 'metadata_url', 'evidence_refs', 'playback_availability', 'artist_destinations'];
  return [columns.join('\t'), ...tracks.map(track => columns.map(key => cell(key === 'artist_destinations' ? JSON.stringify(track[key] ?? []) : Array.isArray(track[key]) ? track[key].join('; ') : track[key])).join('\t'))].join('\n') + '\n';
}
export function mountListeningList(host = document.querySelector('.header')) {
  if (!host) return null;
  const el = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
  const button = (text, action) => { const node = el('button', text); node.type = 'button'; node.addEventListener('click', action); return node; };
  let tracks = [], persistent = true;
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (Array.isArray(stored)) tracks = stored.slice(0, LIMIT).flatMap(row => { const valid = creditedRecording({...row, url: row.metadata_url}, row.artist_mbid, row.artist_name); if (valid) valid.artist_destinations = artistDestinations(row.artist_mbid, row.artist_destinations); return valid ? [valid] : []; });
  } catch { persistent = false; }
  const destinations = new Map();
  const dialog = el('dialog'), title = el('h2', 'Listening list'), note = el('p', 'Credited examples you chose. Musical fit and playback availability are unassessed. Artist destinations do not identify track playback.');
  dialog.className = 'listening-dialog'; dialog.setAttribute('aria-labelledby', 'listening-title'); title.id = 'listening-title';
  const status = el('p'); status.setAttribute('role', 'status');
  const list = el('ol'); list.className = 'listening-tracks';
  const close = button('Close', () => dialog.close());
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(tracks)); } catch { persistent = false; } render(); };
  const download = (format) => {
    const payload = format === 'json' ? JSON.stringify(listeningExport(tracks), null, 2) + '\n' : listeningTSV(tracks);
    const url = URL.createObjectURL(new Blob([payload], {type: format === 'json' ? 'application/json' : 'text/tab-separated-values'}));
    const link = el('a'); link.href = url; link.download = `opennoise-listening-list.${format}`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const json = button('Download JSON', () => download('json')), tsv = button('Download TSV', () => download('tsv'));
  const trigger = button('Listening list (0)', () => { render(); dialog.showModal(); close.focus(); }); trigger.className = 'listening-list-toggle';
  const clear = button('Clear list', () => { tracks = []; save(); });
  function render() {
    trigger.textContent = `Listening list (${tracks.length})`;
    status.textContent = `${tracks.length} of ${LIMIT} recordings. ${persistent ? 'Saved in this browser.' : 'Browser storage unavailable; download to keep this list.'}`;
    list.replaceChildren();
    for (const [index, track] of tracks.entries()) {
      const row = el('li'), link = el('a', `${track.title}${track.artist_name ? ` — ${track.artist_name}` : ''}`);
      link.href = track.metadata_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      row.append(link, button('Remove', () => { tracks.splice(index, 1); save(); })); list.append(row);
    }
    if (!tracks.length) list.append(el('li', 'Add a credited recording from an artist’s music examples.'));
    json.disabled = tsv.disabled = clear.disabled = !tracks.length;
  }
  dialog.append(close, title, note, status, list, json, tsv, clear); document.body.append(dialog); host.append(trigger);
  const style = el('style'); style.textContent = '.listening-dialog{width:min(40rem,calc(100% - 2rem));max-height:85vh;padding:1rem;border:1px solid #777;overflow:auto}.listening-dialog::backdrop{background:#0006}.listening-dialog button{min-height:44px;margin:.2rem}.listening-tracks{padding-left:1.5rem}.listening-tracks li{padding:.4rem 0;overflow-wrap:anywhere}.listening-tracks a{margin-right:.5rem}.recording-action{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}.recording-action>a{flex:1;min-width:0}.recording-action button{min-height:44px}.listening-list-toggle{white-space:nowrap}@media(max-width:600px){.header{height:auto;min-height:64px;flex-wrap:wrap;padding:10px;gap:8px}.header .search{min-width:0;flex:1 1 65%}.listening-list-toggle{font-size:.9rem}}'; document.head.append(style);
  render();
  return {
    addButton(row, artistId, artistName) {
      const track = creditedRecording(row, artistId, artistName); if (!track) return null;
      const control = button('Add to list', () => {
        if (tracks.some(item => item.recording_mbid === track.recording_mbid)) { control.textContent = 'Already in list'; return; }
        if (tracks.length >= LIMIT) { control.textContent = 'List full (200)'; return; }
        track.artist_destinations = destinations.get(artistId) ?? []; tracks.push(track); save(); control.textContent = 'Added';
      }); control.setAttribute('aria-label', `Add ${track.title} to listening list`); return control;
    },
    // Call only with source-validated artist relations; never recording availability.
    setArtistDestinations(artistId, rows) {
      const safe = artistDestinations(artistId, rows);
      destinations.set(artistId, safe);
      for (const track of tracks) if (track.artist_mbid === artistId) track.artist_destinations = safe;
      save();
    }
  };
}
