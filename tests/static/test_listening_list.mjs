import assert from 'node:assert/strict';
import test from 'node:test';
import {creditedRecording, listeningExport, listeningTSV} from '../../src/opennoise/static/listening-list.mjs';
const artist = '11111111-1111-4111-8111-111111111111', recording = '22222222-2222-4222-8222-222222222222';
const row = {recording_mbid: recording, title: '=spreadsheet\ttrack', credited_artist_mbids: [artist], source_sha256: 'a'.repeat(64), url: `https://musicbrainz.org/recording/${recording}`};

test('native exact recording facts retain identities and explicit playback missingness', () => {
  const track = creditedRecording(row, artist, 'Artist');
  assert.equal(track.recording_mbid, recording);
  assert.deepEqual(track.evidence_refs, ['sha256:' + 'a'.repeat(64)]);
  assert.equal(track.audio_url, null);
  assert.equal(listeningExport([track]).musical_fit, 'not_assessed');
  assert.match(listeningTSV([track]), /'=spreadsheet track/);
});

test('incorrect credits, external metadata URLs and absent evidence cannot enter list', () => {
  assert.equal(creditedRecording({...row, credited_artist_mbids: [recording]}, artist), null);
  assert.equal(creditedRecording({...row, url: 'https://example.com/track'}, artist), null);
  assert.equal(creditedRecording({...row, source_sha256: undefined}, artist), null);
  assert.equal(creditedRecording({...row, recording_mbid: 'not-an-id'}, artist), null);
});
