#!/usr/bin/env python3
"""Export observed player evidence and transparent 8-manager auction scenarios.

Valuations allocate a fixed role budget using provider FVM weights. They are
planning references, not learned clearing-price forecasts or neural predictions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.db import database, repository
from src.utils.name_matching import normalize_name

SLOTS = {'P':3,'D':8,'C':8,'A':6}
BUDGETS = {'con_modificatore':{'P':45,'D':85,'C':125,'A':235},
           'senza_modificatore':{'P':45,'D':65,'C':130,'A':250}}


def allocate_market(frame: pd.DataFrame, role_budgets: dict, managers: int = 8) -> pd.Series:
    """Spend role budgets across the expected league slots, reserving 1 per slot."""
    result = pd.Series(1.0,index=frame.index)
    for role, slots in SLOTS.items():
        pool = frame[frame.role.eq(role)].sort_values(['fvm','source_ref'],ascending=[False,True]).head(managers*slots)
        if len(pool) < managers*slots:
            raise ValueError(f'Insufficient eligible {role} players')
        remaining = managers*role_budgets[role]-len(pool)
        weights = pool.fvm.fillna(0).clip(lower=0)
        if weights.sum() == 0:
            weights = pd.Series(1.0,index=pool.index)
        result.loc[pool.index] = 1 + remaining*weights/weights.sum()
    return result


def build(data_dir: Path, as_of: str):
    season_dir = data_dir/'season_2026_27'
    out = season_dir/'outputs'/f'asta_8_500_{as_of.replace("-","_")}'
    out.mkdir(parents=True,exist_ok=True)
    conn = database.get_connection(data_dir/'fantapredictor.db')
    season_id = conn.execute("SELECT id FROM seasons WHERE name='2026/27'").fetchone()[0]
    frame = pd.read_sql_query('''SELECT pp.player_id,pp.source_ref,p.full_name player,
        p.normalized_name player_normalized,c.name club,
        pp.role_classic role,pp.price_current quotazione,pp.fvm,pp.in_league_list,pp.fuori_lista,
        EXISTS(SELECT 1 FROM roster_memberships r WHERE r.player_id=pp.player_id AND r.club_id=pp.club_id
          AND r.season_id=pp.season_id AND r.status='confirmed') confirmed
        FROM player_prices pp JOIN players p ON pp.player_id=p.id JOIN clubs c ON c.id=pp.club_id
        WHERE pp.season_id=?''',conn,params=(season_id,))
    frame.source_ref = frame.source_ref.astype(int)
    last_md = int(conn.execute('SELECT MAX(matchday) FROM player_match_ratings WHERE season_id=?',(season_id,)).fetchone()[0])
    next_md = last_md+1
    current = pd.read_csv(season_dir/'fantacalcio/prices.csv').set_index('source_ref')
    frame['player'] = frame.source_ref.map(current.player).fillna(frame.player)
    frame['eligible'] = frame.in_league_list.eq(1)&frame.fuori_lista.eq(0)&frame.confirmed.eq(1)
    observed = pd.read_sql_query('''SELECT player_id,count(vote) presenze_voto,avg(vote) media_voto,
        avg(fantavoto) fantamedia,min(vote) voto_min,max(vote) voto_max,
        avg(CASE WHEN vote>=6 THEN 1.0 ELSE 0 END) quota_sufficienze,
        sum(goals) gol,sum(assists) assist,sum(yellow_cards) gialli,sum(red_cards) rossi,
        sum(goals_conceded) gol_subiti,sum(penalties_saved) rigori_parati,
        sum(penalties_scored) rigori_segnati,sum(penalties_missed) rigori_sbagliati,
        avg(CASE WHEN matchday>=? THEN vote END) mv_ultime_due,
        avg(CASE WHEN matchday>=? THEN fantavoto END) fm_ultime_due
        FROM player_match_ratings WHERE season_id=? GROUP BY player_id''',conn,params=(last_md-1,last_md-1,season_id))
    history = pd.read_sql_query('''SELECT r.player_id,count(r.vote) presenze_2526,avg(r.vote) mv_2526,
        avg(r.fantavoto) fm_2526 FROM player_match_ratings r JOIN seasons s ON s.id=r.season_id
        WHERE s.name='2025/26' GROUP BY player_id''',conn)
    advanced = pd.read_sql_query('''SELECT ps.player_id,ps.games partite_understat,ps.minutes minuti,
        ps.xg,ps.xa,ps.npxg,ps.xg_chain,ps.xg_buildup,ps.shots tiri,ps.key_passes passaggi_chiave,
        ps.goals gol_understat,ps.assists assist_understat
        FROM player_season_stats ps JOIN sources s ON s.id=ps.source_id
        WHERE season_id=? AND s.slug='understat' ''',conn,params=(season_id,))
    if advanced.player_id.duplicated().any():
        raise ValueError('Multiple active Understat aggregates for one player; reconcile first')
    frame = frame.merge(observed,on='player_id',how='left',validate='one_to_one').merge(history,on='player_id',how='left',validate='one_to_one')
    frame = frame.merge(advanced,on='player_id',how='left',validate='one_to_one')
    summary=pd.read_sql_query('''SELECT player_id,metric,value FROM player_season_stat_values
        WHERE season_id=? AND category='fantacalcio_summary' AND metric IN ('pg','mv','mfv')''',conn,params=(season_id,))
    summary=summary.pivot(index='player_id',columns='metric',values='value').reset_index().rename(
        columns={'pg':'presenze_riepilogo_fonte','mv':'mv_riepilogo_fonte','mfv':'fm_riepilogo_fonte'})
    frame=frame.merge(summary,on='player_id',how='left',validate='one_to_one')
    frame['presenze_voto'] = frame.presenze_voto.fillna(0).astype(int)
    frame['discrepanza_riepilogo']=(frame.presenze_voto.ne(frame.presenze_riepilogo_fonte)
        | (frame.media_voto-frame.mv_riepilogo_fonte).abs().gt(.011)
        | (frame.fantamedia-frame.fm_riepilogo_fonte).abs().gt(.011)) & frame.presenze_riepilogo_fonte.notna()
    frame['gol_meno_xg'] = frame.gol_understat-frame.xg
    for col in ['xg','xa','npxg','xg_chain','xg_buildup','tiri','passaggi_chiave']:
        frame[col+'_90'] = frame[col]*90/frame.minuti.replace(0,np.nan)
    frame['npxg_xa_90'] = (frame.npxg+frame.xa)*90/frame.minuti.replace(0,np.nan)
    frame['campione_minuti_ridotto'] = frame.minuti.lt(180)|frame.minuti.isna()
    formations = pd.read_csv(season_dir/'coaches/probable_formations_2026_27.csv')
    starting_ids = {int(ref) for refs in formations.source_refs for ref in str(refs).split(';')}
    frame[f'probabile_titolare_g{next_md}'] = frame.source_ref.isin(starting_ids)
    availability = pd.read_csv(season_dir/'coaches/availability_current.csv').fillna('')
    availability['key'] = availability.player.map(normalize_name)
    frame['key'] = frame.player.map(normalize_name)
    frame = frame.merge(availability[['key','club','kind','note','source_url']],on=['key','club'],how='left',validate='one_to_one')
    frame = frame.drop(columns='key')
    frame['rischio_disponibilita'] = frame.kind.notna()
    frame['fvm_500_riferimento'] = frame.fvm/2
    # Keep conditional evidence visible; do not invent a precise recovery date.
    eligible = frame[frame.eligible].copy()
    for name,budgets in BUDGETS.items():
        eligible['riferimento_'+name] = allocate_market(eligible,budgets).round(1)
    eligible['soglia_prudente'] = (eligible.riferimento_con_modificatore*.85).clip(lower=1).round()
    max_one_player = eligible.role.map({r:b-SLOTS[r]+1 for r,b in BUDGETS['con_modificatore'].items()})
    eligible['soglia_estesa'] = np.minimum((eligible.riferimento_con_modificatore*1.1).clip(lower=1).round(),max_one_player)
    eligible['soglia_prudente'] = np.minimum(eligible.soglia_prudente,eligible.soglia_estesa)
    eligible['fascia_ruolo'] = eligible.groupby('role').fvm.rank(method='first',ascending=False).map(
        lambda rank:'prima' if rank<=8 else 'seconda' if rank<=16 else 'terza' if rank<=24 else 'completamento')
    eligible = eligible.sort_values(['role','fvm','player'],ascending=[True,False,True])
    fixtures = pd.read_sql_query('''SELECT m.matchday giornata,m.match_date data_ora_fonte,h.name casa,a.name trasferta,
        m.home_goals gol_casa,m.away_goals gol_trasferta,m.home_xg xg_casa,m.away_xg xg_trasferta
        FROM matches m JOIN clubs h ON h.id=m.home_club_id JOIN clubs a ON a.id=m.away_club_id
        JOIN sources s ON s.id=m.source_id WHERE m.season_id=? AND s.slug='understat' ORDER BY m.matchday,m.match_date''',conn,params=(season_id,))
    completed = fixtures[fixtures.gol_casa.notna()&fixtures.gol_trasferta.notna()]
    team_stats = repository.load_team_match_stats(conn,'2627')
    team_stats = team_stats[team_stats.season.eq('2026/27')]
    teams = team_stats.groupby('team').agg(partite=('goals_for','size'),gol_fatti=('goals_for','sum'),gol_subiti=('goals_against','sum'),
                                        tiri_media=('shots','mean'),tiri_porta_media=('shots_on_target','mean')).reset_index().rename(columns={'team':'club'})
    xg_rows = []
    for r in completed.to_dict('records'):
        xg_rows.extend([{'club':r['casa'],'xg':r['xg_casa'],'xga':r['xg_trasferta']},
                        {'club':r['trasferta'],'xg':r['xg_trasferta'],'xga':r['xg_casa']}])
    teams = teams.merge(pd.DataFrame(xg_rows).groupby('club')[['xg','xga']].sum().reset_index(),on='club')
    coverage = frame.groupby('club').agg(listone=('player','size'),acquistabili=('eligible','sum'),con_voto=('presenze_voto',lambda s:int(s.gt(0).sum())),
                                       con_xg=('xg','count'),indisponibili=('rischio_disponibilita','sum')).reset_index()
    teams = teams.merge(coverage,on='club')
    coach_rows = pd.read_sql_query('''SELECT c.name club, co.full_name allenatore, co.preferred_module modulo,
        ccs.started_at allenatore_dal, ccs.ended_at FROM coach_club_seasons ccs JOIN coaches co ON co.id=ccs.coach_id
        JOIN clubs c ON c.id=ccs.club_id WHERE ccs.season_id=? ORDER BY ccs.started_at''',conn,params=(season_id,))
    changes = coach_rows[coach_rows.ended_at.notna()].groupby('club').allenatore.agg(lambda s:', '.join(s)).rename('esonerati_2026_27')
    current_coach = coach_rows[coach_rows.ended_at.isna()].drop(columns='ended_at')
    if not current_coach.empty:
        teams = teams.merge(current_coach,on='club',how='left').merge(changes,on='club',how='left')
        frame = frame.merge(current_coach[['club','allenatore']],on='club',how='left')
        eligible = eligible.merge(current_coach[['club','allenatore']],on='club',how='left')
    budget = pd.DataFrame([{'scenario':scenario,'ruolo':role,'posti':SLOTS[role],'crediti':credit,'crediti_lega':credit*8}
                          for scenario,roles in BUDGETS.items() for role,credit in roles.items()])
    paths = {'Giocatori':eligible,'Listone_completo':frame,'Squadre':teams,'Calendario':fixtures,
             'Indisponibili':availability.drop(columns='key'),f'Probabili_G{next_md}':formations,'Budget':budget,
             'Discrepanze_fonte':frame[frame.discrepanza_riepilogo][['player','club','presenze_voto','media_voto','fantamedia',
                'presenze_riepilogo_fonte','mv_riepilogo_fonte','fm_riepilogo_fonte']],
             'Identita_da_verificare':pd.read_csv(season_dir/'reports/understat_identity_bridge.csv').query("status == 'unresolved'")}
    for name,data in paths.items():
        data.to_csv(out/(name.lower()+'.csv'),index=False)
    with pd.ExcelWriter(out/'Dossier_asta_8_500.xlsx',engine='openpyxl') as writer:
        for name,data in paths.items():
            data.to_excel(writer,sheet_name=name,index=False)
            sheet=writer.sheets[name]
            sheet.freeze_panes='C2'
            sheet.auto_filter.ref=sheet.dimensions
            for cells in sheet.columns:
                values=[len(str(c.value or '')) for c in list(cells)[:80]]
                sheet.column_dimensions[cells[0].column_letter].width=min(45,max(12,max(values)+2))
    conn.close()
    settings={'season':'2026/27','as_of':as_of,'managers':8,'budget':500,'auction_date':None,
              'auction_date_note':'Utente: sabato 25; 25 settembre 2026 venerdi, sabato 26. Da chiarire.',
              'format':'Classic assumed from supplied list','roster_slots_assumed':SLOTS,
              'defence_modifier':{'average_of':'goalkeeper + best 3 defenders','strict_thresholds':{'>6.5':1,'>7.0':3}},
              'role_budgets':BUDGETS,'reserve':10,
              'eligible':len(eligible),'current_votes':int(observed.presenze_voto.sum()),'completed_matches':len(completed),
              'fixture_source':'Understat; matchday derived from provider order and validated for club uniqueness',
              'league_list_as_of':'2026-09-05','neural_model_approved':False}
    (out/'impostazioni_e_limiti.json').write_text(json.dumps(settings,indent=2,ensure_ascii=False)+'\n')
    lines=[f'# Asta a 8, 500 crediti — aggiornamento {as_of}', '',
           f'{len(completed)} gare concluse, {len(fixtures)} incontri a calendario, {int(observed.presenze_voto.sum())} voti, '
           f'{len(eligible)} giocatori acquistabili secondo il listone di lega del 5 settembre.', '',
           'Aprire **Dossier_asta_8_500.xlsx**: filtri per ruolo, squadra, rischio, minutaggio e titolarità probabile. '
           'Il listone completo conserva anche gli esclusi; il foglio Giocatori contiene soltanto confermati e acquistabili.', '',
           '## Budget e metodo', '',
           'Classic 3P/8D/8C/6A. Modificatore: media portiere + migliori 3 difensori, soglie strette '
           '>6,5 = +1 e >7 = +3. Con modificatore: P 45, D 85, C 125, A 235, riserva 10. '
           'Senza modificatore: P 45, D 65, C 130, A 250, riserva 10.', '',
           'I riferimenti di spesa distribuiscono il budget di ciascun reparto sugli slot di tutte e 8 le squadre, '
           'in proporzione al FVM pubblico, riservando almeno 1 credito a ogni slot. Le soglie prudente/estesa '
           '(85%/110%) sono scelte di pianificazione, non probabilità né stime validate di aggiudicazione. '
           'Il FVM pubblico è riportato anche dimezzato sulla scala 500. Non sommare i tetti di tutti gli obiettivi: '
           'dopo ogni acquisto conservare almeno 1 credito per ogni posto ancora libero.', '',
           '## Lettura dei segnali', '',
           'Confrontare gol−xG per individuare finalizzazioni sopra/sotto attesa; npxG+xA/90 misura il coinvolgimento '
           'offensivo senza rigori. Sotto 180 minuti il rapporto per 90 è molto instabile. Confrontare le ultime due '
           f'giornate con la media 2025/26; {last_md} turni non bastano a stabilire il valore stagionale.', '',
           f'Le probabili sono della sola G{next_md}, non una garanzia di titolarità stagionale. Gli infortuni conservano '
           'la descrizione della fonte; la data di rientro usata dal modello traduce la finestra indicata '
           '("metà ottobre" = 15/10, "fine X" = ultimo giorno del mese) ed è una stima, non una certezza. '
           'Per i portieri xG offensivo non è una misura di abilità: usare gol subiti, voti, rigori parati e contesto squadra.', '',
           f'Il riepilogo stagionale del sito differisce dalle pagelle giornaliere per {int(frame.discrepanza_riepilogo.sum())} '
           'giocatori del listone. Il foglio Discrepanze_fonte conserva entrambi i valori. MV e FM principali sono '
           'ricalcolate dalle pagelle scaricate; il riepilogo non sovrascrive i singoli voti osservati.', '',
           '## Copertura e limiti', '',
           f'Understat offre aggregati per {int(frame.minuti.notna().sum())} giocatori del listone; le identità non abbinate restano nel foglio dedicato. '
           'Le celle vuote indicano assenza di copertura, non zero. Nessuno scraping FBref: dati di pressing, '
           'duelli e PSxG individuale non sono presenti in questo aggiornamento. Il modello SHASH non ha superato '
           'il gate di valutazione e non è usato per questi prezzi.', '',
           'La lista di lega risale al 5 settembre: i nuovi ingressi non presenti restano esclusi fino a un nuovo export. '
           'Il 25 settembre 2026 è venerdì, sabato è il 26: data d’asta ancora da confermare. '
           f'Dati aggiornati alla G{last_md}; questo dossier fotografa il {as_of}.', '',
           '## Prime fasce per ruolo', '']
    for role in SLOTS:
        lines.append(f'### {role}')
        lines.append('')
        for row in eligible[eligible.role.eq(role)].head(8).itertuples():
            risk=' — indisponibilità da verificare' if row.rischio_disponibilita else ''
            lines.append(f'- {row.player} ({row.club}): riferimento {row.riferimento_con_modificatore:.0f} crediti; '
                         f'MV {row.media_voto:.2f}, FM {row.fantamedia:.2f}, {row.presenze_voto} presenze a voto{risk}.')
        lines.append('')
    lines.extend(['## Tutte le 20 squadre', ''])
    for team in teams.itertuples():
        squad=eligible[eligible.club.eq(team.club)]
        signal=squad[squad.minuti.ge(180)&squad.role.ne('P')].sort_values('npxg_xa_90',ascending=False).head(2)
        examples='; '.join(f'{r.player} ({r.npxg_xa_90:.2f} npxG+xA/90, {r.minuti:.0f} minuti)' for r in signal.itertuples())
        coach=getattr(team,'allenatore',None)
        coach_text=f' Allenatore: {coach} ({team.modulo})' if isinstance(coach,str) else ''
        sacked=getattr(team,'esonerati_2026_27',None)
        if isinstance(sacked,str):
            coach_text+=f', dal {team.allenatore_dal} al posto di {sacked}'
        lines.append(f'- **{team.club}**:{coach_text}{"." if coach_text else ""} {team.gol_fatti:.0f} gol fatti / {team.gol_subiti:.0f} subiti; '
                     f'xG {team.xg:.2f} / xGA {team.xga:.2f}; {team.acquistabili} acquistabili. '
                     f'Segnali offensivi osservati: {examples or "campione insufficiente"}.')
    lines.extend(['','## Fonti','',
        f'- [Voti Fantacalcio, G{last_md}](https://www.fantacalcio.it/voti-fantacalcio-serie-a/2026-27/{last_md})',
        '- [Statistiche e quotazioni Fantacalcio](https://www.fantacalcio.it/statistiche-serie-a/2026-27)',
        '- [Understat Serie A 2026](https://understat.com/league/Serie_A/2026)',
        '- [Football-Data Serie A](https://www.football-data.co.uk/italym.php)',
        '- [Indisponibili Fantacalcio](https://www.fantacalcio.it/serie-a/indisponibili)',
        '- [Probabili formazioni Fantacalcio](https://www.fantacalcio.it/probabili-formazioni-serie-a)'])
    (out/'LEGGIMI.md').write_text('\n'.join(lines)+'\n')
    from openpyxl import load_workbook
    workbook=load_workbook(out/'Dossier_asta_8_500.xlsx')
    method=workbook.create_sheet('Metodo_e_limiti',0)
    for line in lines[:lines.index('## Prime fasce per ruolo')]:
        method.append([line])
    method.column_dimensions['A'].width=115
    from openpyxl.styles import Alignment
    for row in method:
        row[0].alignment=Alignment(wrap_text=True,vertical='top')
        method.row_dimensions[row[0].row].height=max(18,15*(1+len(str(row[0].value or ''))//110))
    workbook.save(out/'Dossier_asta_8_500.xlsx')
    return settings,out


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--as-of',required=True)
    args=parser.parse_args()
    settings,out=build(args.data_dir,args.as_of)
    print(json.dumps(settings,indent=2,ensure_ascii=False));print(out)
