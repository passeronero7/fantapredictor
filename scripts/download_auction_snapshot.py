#!/usr/bin/env python3
"""Download a dated Serie A 2026/27 research snapshot without touching SQLite."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.download_understat_season import fetch_league_data, build_frame
from scripts.reconcile_official_transfers import fetch_transfers, FEED_URL
from src.data_processing.prices_processor import parse_prices_html
from src.data_processing.votes_processor import VotesProcessor


def download(snapshot: Path, last_matchday: int):
    if not 1 <= last_matchday <= 38:
        raise ValueError('last-matchday must be 1..38')
    snapshot.mkdir(parents=True,exist_ok=True)
    sources=[]
    def save(name,content,url):
        path=snapshot/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
        sources.append({'path':name,'source_url':url,'checked_at':datetime.now(UTC).isoformat(),
                        'sha256':hashlib.sha256(content).hexdigest(),'size':len(content)})
    with requests.Session() as session:
        session.headers['User-Agent']='FantaPredictor/0.8 personal research'
        payload,url=fetch_league_data(session,'Serie_A',2026)
        checked=datetime.now(UTC).isoformat()
        save('understat_payload.html',json.dumps(payload).encode(),url)
        build_frame(payload['players'],2026,checked).to_csv(snapshot/'understat_serie_a_2026_season.csv',index=False)
        for name,url in {
            'prices.html':'https://www.fantacalcio.it/quotazioni-fantacalcio',
            'statistics.html':'https://www.fantacalcio.it/statistiche-serie-a/2026-27',
            'formations.html':'https://www.fantacalcio.it/probabili-formazioni-serie-a',
            'injuries.html':'https://www.fantacalcio.it/serie-a/indisponibili',
            'football-data/2627/I1.csv':'https://www.football-data.co.uk/mmz4281/2627/I1.csv',
        }.items():
            response=session.get(url,timeout=30)
            response.raise_for_status()
            save(name,response.content,response.url)
        frame=parse_prices_html((snapshot/'prices.html').read_text(),season='2026-27')
        if frame.empty or frame.team.nunique()!=20:
            raise ValueError('Incomplete price snapshot')
        frame.to_csv(snapshot/'prices_public.csv',index=False)
        votes=[]
        processor=VotesProcessor()
        for md in range(1,last_matchday+1):
            url=f'https://www.fantacalcio.it/voti-fantacalcio-serie-a/2026-27/{md}'
            response=session.get(url,timeout=30)
            response.raise_for_status()
            save(f'votes_md{md:02d}.html',response.content,url)
            frame=processor.parse_matchday_html(response.text,season='2026-27',matchday=md)
            if frame.empty or frame.team.nunique()!=20:
                raise ValueError(f'Matchday {md} votes incomplete; snapshot not ready for ingestion')
            folder=snapshot/'votes'
            folder.mkdir(exist_ok=True)
            frame.to_csv(folder/f'Voti_Fantacalcio_Stagione_2026-27_Giornata_{md:02d}.csv',index=False)
            votes.append(frame)
        pd.concat(votes,ignore_index=True).to_csv(snapshot/'votes/Voti_Fantacalcio_Stagione_2026-27_Full.csv',index=False)
        _,pages=fetch_transfers(session)
        save('transfers_all_pages.json',json.dumps(pages).encode(),FEED_URL)
    manifest={'season':'2026/27','checked_at':datetime.now(UTC).isoformat(),'last_matchday':last_matchday,'sources':sources}
    (snapshot/'acquisition_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--last-matchday',type=int,required=True)
    args=parser.parse_args()
    print(json.dumps(download(args.snapshot,args.last_matchday),indent=2))
