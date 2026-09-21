# AcousticBrainz Genre Dataset evaluation audit

## Decision

The AcousticBrainz Genre Dataset is a conditional source for a small,
metadata-only, held-out recording-label evaluation. It is not approved for
construction, public membership, layout fitting, or an artist genre gold set.
No pilot should run until a license review approves the intended local research
use and an exact recording-to-artist bridge is available from a separate,
sealed MusicBrainz source.

The result corrects an older inventory shorthand that described AcousticBrainz
as having recording IDs but no genre labels. The AcousticBrainz Genre Dataset
is a separate dataset. Its ground-truth TSV files contain recording and release
group MusicBrainz IDs plus genre labels.

## Evidence

The [official data page](https://mtg.github.io/acousticbrainz-genre-dataset/data/)
defines each annotation row as a recording MBID, a release-group MBID, and one
or more genre or subgenre labels. It states that validation archives contain
both the feature JSON files and matching ground truth. A metadata-only pilot
must download only the validation TSV. It must reject feature archives and must
not read any JSON feature file.

The same page describes four label sources. Discogs labels were propagated from
release metadata. Last.fm and Tagtraum labels are derived from collaborative
recording tags. AllMusic needs a separate agreement and is excluded from any
pilot. The public Discogs, Last.fm, and Tagtraum portions still carry the
dataset's CC BY-NC-SA 4.0 terms. The [project repository](https://github.com/MTG/acousticbrainz-genre-dataset)
also describes the collection as multi-source, multi-label genre metadata.

The TSV recording MBID can identify a recording. It cannot alone identify a
catalog artist. The dataset does not include an artist MBID column. The current
repository has receipt-bound MusicBrainz release-group and recording work, but
the evaluation boundary needs a declared, exact recording MBID to one canonical
artist MBID relation. Name matching, release title matching, and a many-artist
recording must abstain. The release-group ID can be a consistency check. It
cannot replace the recording-to-artist bridge.

## Construction and leakage boundary

The current source inventory says that no AcousticBrainz, Discogs, or retained
Last.fm source cache enters the graph or membership construction. The current
Last.fm adapters have no sealed response cache. The existing public factual
graph uses Wikidata and permitted aggregate similarity, while MusicBrainz
genre and release support stay local research evidence.

The candidate TSV labels must remain outside every builder input. A pilot must
record the source file byte hash, the selected source partition, and the hash
of the frozen predictions before reading source labels. It must verify that the
TSV hash is absent from construction receipts, model input bindings, layout
inputs, and prediction inputs. The label-to-seed normalization table must be
fixed from existing names before the held-out rows are read. The pilot cannot
add aliases, tune thresholds, select candidates, or change a graph edge after
seeing its labels.

Discogs, Last.fm, and Tagtraum need separate reports. Their rows can overlap,
and their annotation rules differ. A result from one source cannot validate a
claim that uses the same source later. AllMusic is excluded because its access
and research-only terms are more restrictive.

## MusicBrainz contamination check

The [MetaBrainz genre-matching repository](https://github.com/metabrainz/genre-matching/blob/master/README.md)
states that it added about six million MusicBrainz recording genre tags to more
than 1.3 million recordings in 2021 from the AcousticBrainz Genre Dataset. The
repository identifies Discogs, Last.fm, and Tagtraum source data, including the
train and validation TSVs. A later MusicBrainz dump can therefore contain
labels that originated in the proposed evaluation source. Recording IDs in the
dataset make an exact-row overlap check possible when the MusicBrainz tag
provenance is retained.

The current public factual graph does not use MusicBrainz tags or recording
genre rows. Its membership candidate uses direct Wikidata claims and permitted
aggregate similarity. A frozen prediction from that path is therefore not
known to consume the AcousticBrainz-derived MusicBrainz tags. The pilot must
still prove the selected prediction input bindings exclude MusicBrainz artist
tags, recording genre rows, release genre support, and any model derived from
them. The pilot cannot evaluate a local peer, release-support, or
MusicBrainz-tag model against these TSV labels without a separate contamination
audit.

Discogs is not independent of MusicBrainz in this setting because
genre-matching used its AcousticBrainz rows. Last.fm and Tagtraum have the same
contamination risk. The pilot must report a no-go for production gold if any
selected prediction uses the genre-matching import, an exact selected recording
has matching MusicBrainz imported genre provenance, or the required provenance
cannot be checked.

## Small pilot

The recommended pilot is at most 100 exact, unique recording-to-artist joins
from one source partition only after its construction-exclusion audit passes.
Discogs is eligible only if the frozen prediction has no MusicBrainz tag or
recording genre dependency and the record-level provenance check passes. The
pilot uses only the two MBID columns and nonempty labels. It stores a source
receipt, the approved license decision, a row count, rejected-row reasons, and
hashes. It does not store audio, acoustic features, feature JSON, or unneeded
TSV rows.

First, freeze the current artist-membership predictions and target name
normalizer. Second, choose rows by a stable hash of source recording MBID after
the exact artist bridge is complete. Third, map only exact predeclared labels to
existing target names. Fourth, report positive-only coverage and recall at the
frozen prediction cutoff. Missing dataset labels are unknown, not negatives.
Precision, threshold selection, and promotion remain out of scope until a
separate negative-label policy and an approved rights decision exist.

## Go or no-go

The recommendation is no-go for production gold today. The repository has no
retained TSV, receipt, approved license decision, declared exact
recording-to-artist bridge, or completed record-level contamination audit. A
diagnostic-only pilot is conditionally allowed for a frozen prediction that
excludes every MusicBrainz tag or recording genre input. Production gold needs
an exact record-level exclusion audit that proves the selected evaluation rows
are disjoint from every construction input. Passing a diagnostic pilot would
establish only source coverage and positive-only held-out evidence. It would
not approve a public model, change a sealed artifact, or make the dataset a
construction input.
