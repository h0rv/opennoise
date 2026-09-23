# ListenBrainz artist-session approximation

This local-only experiment uses exact artist MBIDs and a fixed duration of 180
seconds. It is not a reproduction of ListenBrainz production similarity: it
does not map recordings to artist credits, use recording duration, drop short
skips, or weight featured artists. It uses a 300-second timestamp gap,
per-user pair contribution cap of five, score strictly greater than ten, and
top-100 neighbor accounting. It retains aggregate counts only, never listener
or artist IDs, pairs, ranks, or a serving artifact.

The reader caps compressed archive bytes, every decompressed byte consumed by
the tar reader, each listen member and line, user, artist, session, and pair
state before pair expansion. It also bounds retained pair-support events. A
reported threshold pair needs both a score above ten and at least five distinct
contributing users. The 250,000-record prefix has no threshold pairs.

The first bounded receipt scans at most 250,000 records from one retained,
hash-verified daily archive. It is a feasibility result only. It is neither a
model input nor an independent evaluation; any future Labs comparison must be
against frozen local output and remain source-family dependent.

The first 250,000-record prefix from the 2026-08-24 archive retained 2,833
exact-artist-MBID listens across 589 users and 753 approximate sessions. It
formed 5,587 capped-contribution candidate pairs, with zero scores strictly
above ten. This is a single-archive prefix, not a seven-day result.
