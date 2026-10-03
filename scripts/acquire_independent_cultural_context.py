"""Acquire/replay a curated, exact-ID Wikidata CC0 cultural evidence pack."""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from datetime import UTC, datetime
from pathlib import Path
import httpx
from opennoise.ingest.open_cultural_source import ENDPOINT, build_query, capture_raw_response, parse_bindings
try:
    from scripts.probe_open_cultural_sources import (
        _replay_batch,
        _verify_pack_file_hashes,
        sha256_file,
    )
except ModuleNotFoundError:
    from probe_open_cultural_sources import (
        _replay_batch,
        _verify_pack_file_hashes,
        sha256_file,
    )

# Curated roster (names are provenance/display only); stable QIDs and exact P434
# MusicBrainz IDs came from the retained exact-English-label crosswalk capture.
ROSTER = [
("Miles Davis","Q93341","561d854a-6a28-4aa7-8c99-323e6ce46c2a","jazz"),
("John Coltrane","Q7346","b625448e-bf4a-41c3-a421-72ad46cdb831","jazz"),
("Nina Simone","Q174957","2944824d-4c26-476f-a981-be849081942f","jazz"),
("Ella Fitzgerald","Q1768","54799c0e-eb45-4eea-996d-c4d71a63c499","jazz"),
("Thelonious Monk","Q109612","8e8c7417-c905-46b1-b42a-5260b4274ed4","jazz"),
("Duke Ellington","Q4030","3af06bc4-68ad-4cae-bb7a-7eeeb45e411f","jazz"),
("Björk","Q42455","87c5dedd-371d-4a53-9f7f-80522fb7f3cb","electronic/pop"),
("Fela Kuti","Q313868","6514cffa-fbe0-4965-ad88-e998ead8a82a","African popular"),
("Ali Farka Touré","Q334947","9be2a5ac-8201-489b-b5f6-91f958bf9060","African popular"),
("Celia Cruz","Q474045","7b8e1188-9ca4-4aa5-8393-172de6fa04de","Latin"),
("Caetano Veloso","Q309983","f07dbc2f-317b-470f-bad4-5f1b0eb6faf1","Latin"),
("Sufjan Stevens","Q319502","01d3c51b-9b98-418a-8d8e-37f6fab59d8c","folk/rock"),
("Joni Mitchell","Q205721","a6de8ef9-b1a1-4756-97aa-481bbb8a4069","folk/rock"),
("Joan Baez","Q131725","92d37892-6186-4459-9cc1-f0dde57652d0","folk"),
("Muddy Waters","Q220707","f86f1f07-d182-45ce-ae93-ef610880ca72","blues"),
("Son House","Q352999","8c87dda0-be58-4e48-a3b5-2626f26364c7","blues"),
("Johnny Cash","Q42775","d43d12a1-2dc9-4257-a2fd-0a3bb1081b86","country"),
("Wu-Tang Clan","Q52463","0febdcf7-4e1f-4661-9493-b40427de2c13","hip-hop"),
("A Tribe Called Quest","Q300602","9689aa5a-4471-4fb4-9721-07cecda0fa9f","hip-hop"),
("Public Enemy","Q209182","bf2e15d0-4b77-469e-bfb4-f8414415baca","hip-hop"),
("OutKast","Q472595","73fdb566-a9b1-494c-9f32-51768ec9fd27","hip-hop"),
("Nas","Q194220","cfbc0924-0035-4d6c-8197-f024653af823","hip-hop"),
("Kraftwerk","Q44892","5700dcd4-c139-4f31-aa3e-6382b9af9032","electronic"),
("Black Sabbath","Q47670","5182c1d9-c7d2-4dad-afa0-ccfeada921a8","metal"),
("Metallica","Q15920","65f4f0c5-ef9e-490c-aee3-909e7ae6b2ab","metal"),
("Celtic Frost","Q324645","d91b3683-4622-4d72-8a03-80f1ff59e639","metal"),
("Sepultura","Q239074","1d93c839-22e7-4f76-ad84-d27039efc048","metal"),
("Mastodon","Q548844","bc5e2ad6-0a4a-4d90-b911-e9a7e6861727","metal"),
("Iron Maiden","Q42482","ca891d65-d9b0-4258-89f7-e6ba29d83767","metal"),
("Johann Sebastian Bach","Q1339","24f1766e-9635-4d58-a4d4-9413f9f98a4c","classical"),
("Ludwig van Beethoven","Q255","1f9df192-a621-4f54-8850-2c5373b7eac9","classical"),
("Nina Hagen","Q159099","e4d32f51-bc57-42a4-8165-b80f7a86496d","rock"),
("Astor Piazzolla","Q172505","e280268a-a5ab-4bb0-be4d-ec470ca59131","Latin/classical"),
("Ravi Shankar","Q103774","697f8b9f-0454-40f2-bba2-58f35668cdbe","South Asian classical"),
("Anoushka Shankar","Q259379","40ee8fa3-c6d7-4556-b4e2-9f4114565043","South Asian classical"),
("Tinariwen","Q262317","5c98fc12-be83-4246-ae5b-2184192913b9","African popular"),
("King Sunny Adé","Q982678","3e110caa-e9e8-4c33-98dc-ebbf0c6d2494","African popular"),
("Miriam Makeba","Q146256","bc5c2918-4aba-4ef6-a245-100563a4487f","African popular"),
("Lata Mangeshkar","Q156347","aeb71bd8-447d-4415-8ea1-2b7d664f67e1","South Asian popular"),
("Manu Chao","Q207898","7570a0dd-5a67-401b-b19a-261eee01a284","Latin/rock"),
]
BASELINE = [
("Aphex Twin","f22942a1-6f70-4f48-866e-238cb2308fbd","Q223161"),
("Four Tet","3bcff06f-675a-451f-9075-99e8657047e8","Q959655"),
]
DOCS={"query_service":"https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service","license":"https://www.wikidata.org/wiki/Wikidata:Licensing","identity_property":"https://www.wikidata.org/wiki/Property:P434","properties":{"P136":"https://www.wikidata.org/wiki/Property:P136","P495":"https://www.wikidata.org/wiki/Property:P495","P740":"https://www.wikidata.org/wiki/Property:P740","P135":"https://www.wikidata.org/wiki/Property:P135"}}
def dump(p,obj): p.write_text(json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
def acquire(out:Path):
    out.mkdir(parents=True,exist_ok=False); (out/'raw').mkdir()
    # Preserve the exact English-label to P434 discovery response for roster provenance.
    discovery_names=[x[0] for x in ROSTER]+["Youssou N'Dour","Kendrick Lamar","Missy Elliott"]
    values=' '.join(json.dumps(n,ensure_ascii=False)+'@en' for n in discovery_names)
    discovery_query=f'''PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> SELECT ?label ?mbid ?artist WHERE {{ VALUES ?label {{ {values} }} ?artist rdfs:label ?label; wdt:P434 ?mbid. }}'''
    with httpx.Client(timeout=30,headers={'User-Agent':'OpenNoise/0.1 (bounded CC0 music metadata research)','Accept':'application/sparql-results+json'}) as client:
        dr=client.get(ENDPOINT,params={'query':discovery_query})
        dr.raise_for_status(); discovery_body=dr.content
    discovery_payload=json.loads(discovery_body)
    observed={(b['label']['value'],b['artist']['value'].rsplit('/',1)[-1],b['mbid']['value']) for b in discovery_payload['results']['bindings']}
    if any((name,qid,mbid) not in observed for name,qid,mbid,_ in ROSTER): raise ValueError('curated identity missing from retained discovery response')
    for miss in ["Youssou N'Dour","Kendrick Lamar","Missy Elliott"]:
        if any(b['label']['value']==miss for b in discovery_payload['results']['bindings']): raise ValueError('omitted artist has an exact discovery match; review before acquisition')
    discovery_raw=out/'raw'/'roster-discovery.json'; discovery_raw.write_bytes(discovery_body)
    ids=[x[2] for x in ROSTER]+[x[1] for x in BASELINE]
    if len(set(ids))!=len(ids): raise ValueError('duplicate exact MBID in curated cohort')
    batch=tuple(ids)
    with httpx.Client(timeout=30,headers={'User-Agent':'OpenNoise/0.1 (bounded CC0 music metadata research)','Accept':'application/sparql-results+json'}) as client:
        query,body,status=capture_raw_response(batch,client=client)
    payload=json.loads(body); all_rows=parse_bindings(payload,set(batch))
    expected_qids={x[2]:x[1] for x in ROSTER}
    expected_qids.update({x[1]:x[2] for x in BASELINE})
    evidence=tuple(e for e in all_rows if expected_qids[e.musicbrainz_artist_id] in (None,e.wikidata_artist_id))
    if len({e.musicbrainz_artist_id for e in evidence}) != len(evidence): raise ValueError('multiple curated QIDs resolved to one exact MBID')
    raw=out/'raw'/'batch-00.json'; raw.write_bytes(body)
    cohort=[{'artist_mbid':mbid,'name':name,'role':'curated_cross_scene','qid':qid,'curation_context':context} for name,qid,mbid,context in ROSTER]
    cohort += [{'artist_mbid':mbid,'name':name,'role':'baseline','qid':qid} for name,mbid,qid in BASELINE]
    manifest={'revision':'independent-cultural-context-wikidata-20261002-v1','acquired_utc':datetime.now(UTC).isoformat(),'endpoint':ENDPOINT,'license':'CC0','docs':DOCS,'properties':['P135','P136','P495','P740'],'identity_rule':'construction joins only by exact MusicBrainz UUID through Wikidata P434; display names and curation context are not labels','discovery':{'query_sha256':hashlib.sha256(discovery_query.encode()).hexdigest(),'response_sha256':hashlib.sha256(discovery_body).hexdigest(),'response_bytes':len(discovery_body),'http_status':dr.status_code,'returned_binding_count':len(discovery_payload['results']['bindings']),'raw_path':'raw/roster-discovery.json','identity_rule':'exact English label plus exact P434 UUID and manually curated QID; all direct claim acquisition is subsequently exact-MBID based'},'selection':{'method':'curated cross-scene/country roster fixed before query; no EveryNoise observations or MusicBrainz genre associations used','extra_artist_count':len(ROSTER),'request_count_including_crosswalk':2,'omitted_discovery_candidates':['Youssou N\'Dour','Kendrick Lamar','Missy Elliott'],'omission_reason':'No exact English rdfs:label plus P434 crosswalk result in the retained discovery response.'},'cohort':cohort,'requested_artist_count':len(ids),'batch_count':1,'request_count':2,'response_bytes_total':len(body),'discovery_response_bytes':len(discovery_body),'total_acquired_response_bytes':len(body)+len(discovery_body),'matched_artist_count':len(evidence),'raw_qid_conflict_row_count':len(all_rows)-len(evidence),'unmatched_artist_count':len(ids)-len(evidence),'unmatched_artist_mbids':sorted(set(ids)-{e.musicbrainz_artist_id for e in evidence}),'direct_claim_count':sum(len(e.claims) for e in evidence),'batches':[{'index':0,'requested_mbids':list(batch),'query_sha256':hashlib.sha256(query.encode()).hexdigest(),'response_sha256':hashlib.sha256(body).hexdigest(),'response_bytes':len(body),'http_status':status,'returned_binding_count':len(payload['results']['bindings']),'matched_artist_count':len(all_rows),'unmatched_artist_mbids':sorted(set(ids)-{e.musicbrainz_artist_id for e in all_rows}), 'raw_qid_conflict_rows':len(all_rows)-len(evidence),'raw_path':'raw/batch-00.json'}]}
    dump(out/'manifest.json',manifest); dump(out/'artist-evidence.json',[e.model_dump(mode='json') for e in evidence])
    receipt={'revision':manifest['revision'],'source':ENDPOINT,'license':'CC0','license_scope':'Wikidata exact P434 identity crosswalk and direct P136/P495/P740/P135 claims only','sha256':{str(p.relative_to(out)):sha256_file(p) for p in [out/'manifest.json',out/'artist-evidence.json',raw,discovery_raw]}}
    dump(out/'receipt.json',receipt)
    print(f'acquired {len(ids)} exact-ID requests; {len(evidence)} matched; {manifest["direct_claim_count"]} direct claims; {len(body)} response bytes')
def replay(path:Path):
    _verify_pack_file_hashes(path)
    m=json.loads((path/'manifest.json').read_text())
    discovery=m['discovery']
    curated=[a for a in m['cohort'] if a['role']=='curated_cross_scene']
    omitted=m['selection']['omitted_discovery_candidates']
    names=[a['name'] for a in curated]+omitted
    values=' '.join(json.dumps(name,ensure_ascii=False)+'@en' for name in names)
    discovery_query=f'''PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> SELECT ?label ?mbid ?artist WHERE {{ VALUES ?label {{ {values} }} ?artist rdfs:label ?label; wdt:P434 ?mbid. }}'''
    raw_discovery=(path/discovery['raw_path']).read_bytes()
    if hashlib.sha256(discovery_query.encode()).hexdigest()!=discovery['query_sha256']:
        raise ValueError('discovery query hash mismatch')
    if hashlib.sha256(raw_discovery).hexdigest()!=discovery['response_sha256'] or len(raw_discovery)!=discovery['response_bytes']:
        raise ValueError('discovery response hash or byte count mismatch')
    discovery_rows=json.loads(raw_discovery)['results']['bindings']
    observed={(row['label']['value'],row['artist']['value'].rsplit('/',1)[-1],row['mbid']['value']) for row in discovery_rows}
    if any((a['name'],a['qid'],a['artist_mbid']) not in observed for a in curated):
        raise ValueError('curated roster does not replay from exact P434 discovery')
    if any(row['label']['value'] in omitted for row in discovery_rows):
        raise ValueError('an omitted artist has a discovery match')
    b=m['batches'][0]
    req,all_rows,size=_replay_batch(path,b)
    qids={x['artist_mbid']:x.get('qid') for x in m['cohort'] if x.get('qid')}
    evidence=tuple(e for e in all_rows if qids.get(e.musicbrainz_artist_id) in (None,e.wikidata_artist_id))
    expected=json.loads((path/'artist-evidence.json').read_text())
    if [e.model_dump(mode='json') for e in evidence]!=expected: raise ValueError('projection does not replay')
    if len(req)!=m['requested_artist_count'] or len(evidence)!=m['matched_artist_count'] or size!=m['response_bytes_total']: raise ValueError('manifest accounting mismatch')
    if m.get('raw_qid_conflict_row_count') != len(all_rows)-len(evidence): raise ValueError('raw identity conflict accounting mismatch')
    print(f'verified raw replay: {len(req)} requested, {len(evidence)} exact matches, {sum(len(e.claims) for e in evidence)} claims')
if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--acquire',type=Path); a.add_argument('--verify',type=Path); n=a.parse_args()
    if n.acquire: acquire(n.acquire)
    elif n.verify: replay(n.verify)
