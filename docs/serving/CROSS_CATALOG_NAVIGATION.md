# Searches between catalogs

An atlas artist can open a name search in Connections. A Connections artist can
open a name search in the atlas. Each result keeps its original source ID and
name, including qualifiers and ambiguous matches.

The atlas offers "Search connections" when the listening catalog contains the
same normalized name. If the full name has no match, the lookup can remove a
final parenthesized qualifier. The action always opens search results, even when
only one exact name is available. It does not create an identity link.

The retained catalogs provide 7,401 such atlas search paths. Full names account
for 5,619 paths, and names without a final qualifier account for 1,782. There are
42 atlas rows with two native exact-name candidates. The counts describe name
availability, and they do not measure verified identities or recommendation
quality.

Connections uses `#browse/QUERY/PAGE`. Atlas artist searches use
`#artists/search/QUERY/PAGE`, with the same matching and ordering as the Artists
section of the existing global search. The complete artist directory remains at
`#artists/PAGE`. All data files and source contracts remain unchanged.

The optional Connections lookup runs separately from atlas facts. A pending or
failed catalog response cannot block the artist page, and an obsolete response
cannot add an action to a different artist.

The browser gate checks both directions on desktop and phones, complete scoped
search results for Can, Yes and Love, ambiguous native names, history and reload.
It also checks the complete offline export and simulated local catalog failures,
including a response held until after the selected atlas artist changes.
