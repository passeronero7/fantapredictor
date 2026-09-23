# Masterplan — ottimizzatore d'asta e pipeline 2026/27

**Redatto:** 22 settembre 2026 · **Scadenza vincolante:** asta 25/26 settembre (data da confermare)

Origine: revisione critica dei commit `bed0510`, `de757d9`, `7ae8c87`. Ogni voce
indica file toccati, criterio di accettazione (DoD) e stima. L'ordine riflette
il rischio per la decisione d'asta, non l'eleganza.

## Stato al 23 settembre

- **Fase 0 completata** (commit `30c6df9`). Il rerun pubblicato quel giorno
  era però viziato: `FANTAPREDICTOR_DATA_DIR` non era impostato e il
  forecast aveva saltato in silenzio le probabili formazioni. Lo script ora
  si ferma se mancano; quella rosa è superata.
- **Fase 1 completata**: pavimento sulla quotazione (1.1), rose alternative e
  robustezza (1.2), premio del modificatore calibrato sui voti 2025/26 (1.3),
  scostamento dai budget di reparto nel JSON (1.4, solo report, nessun
  vincolo). Corretto anche il matching delle formazioni (ID ufficiali invece
  di sottostringhe su tutti i club).
- **Scoperte che hanno cambiato il piano**: il premio 1.1 contava meno del
  previsto perché le scelte a 1 credito erano soprattutto effetto del
  `p_plays` gonfiato; il modificatore di questa lega vale in media ~0,13
  punti a giornata; la tabella allenatori è vuota da almeno il 6 settembre,
  quindi quel condizionamento non è mai stato attivo (non riattivato: delta
  non validati).
- **Condizionamento allenatori attivo (23/09, richiesta utente)**: storia
  delle panchine 2015/16-2026/27 (cambi Fiorentina e Bologna inclusi),
  quote di gol e assist per reparto per allenatore, moltiplicatori per
  giocatore validati con backtest (effetto piccolo, forza 0,25). Vedi
  `docs/coach_conditioning.md`. Dati aggiornati alla G5.
- **Prossimo**: Fase 2 (asta dal vivo).

---

## Fase 0 — Correttezza (bloccante, entro il 23/09)

Senza questa fase la rosa consigliata non è affidabile.

### 0.1 Indici della matrice MILP
- **Problema:** `optimize_auction_roster` fa `reset_index` prima del filtro;
  con righe scartate `offset + player_index` esce dalla matrice (IndexError) o
  collide con la riga del budget, cancellando un vincolo "al più una volta".
- **Fix:** `reset_index(drop=True)` dopo il filtro in
  `src/models/auction_optimizer.py`; usare posizioni `range(len(frame))`.
- **Test:** pool con righe senza costo in testa → rosa valida, 25 giocatori unici.
- **Stima:** 30 min.

### 0.2 Doppio sconto indisponibilità
- **Problema:** `simulate_auction_propensity.py` sconta già `p_plays` per data di
  rientro; `optimize_auction_roster.py::build_pool` moltiplica di nuovo per
  0,75/0,35.
- **Fix:** un solo canale. Tenere quello strutturato (data di rientro nel
  forecast) e usare `availability_factor` solo per giocatori con
  `rischio_disponibilita` **senza** riga in `availability_notes`. Esportare dal
  forecast una colonna `availability_applied` per rendere esplicita la scelta.
- **Test:** giocatore con nota strutturata → fattore ottimizzatore = 1,0.
- **Stima:** 1 h.

### 0.3 Orizzonte deterministico
- **Problema:** `horizon_start = date.today()` rende il run non riproducibile.
- **Fix:** parametro `--as-of` (default: data dello snapshot) propagato a
  `horizon_factor`; registrarlo nel JSON di output.
- **Stima:** 30 min.

### 0.4 Riserva di budget
- **Problema:** rosa a 500/500 mentre il config prevede riserva 10.
- **Fix:** `AuctionOptimizationConfig.reserve`; vincolo `costo ≤ budget − reserve`;
  `--reserve` letto da `config/auction_2026_27.json` del workspace.
- **Stima:** 30 min.

### 0.5 Identità per ID, non per nome
- **Problema:** join su nome normalizzato, inner join che scarta in silenzio,
  unicità verificata sul nome (omonimi: Kamara, Thuram…).
- **Fix:** esportare `player_id` nel forecast; join su ID con fallback per nome
  loggato; stampare e salvare nel JSON il conteggio `dropped_forecast`,
  `dropped_dossier` con i nomi; unicità su `player_id`.
- **DoD:** run reale con 0 scarti non spiegati.
- **Stima:** 1,5 h.

### 0.6 Pulizie minori
- Commento obsoleto "Below 6.0" in `tests/test_lineup_optimizer.py`.
- Non sovrascrivere cartelle datate: il dossier del 22/09 va in
  `asta_8_500_2026_09_22/`; ripristinare quella del 16/09 dal manifest.
- **Stima:** 20 min.

---

## Fase 1 — Robustezza della raccomandazione (entro il 24/09)

L'obiettivo è passare da "una rosa ideale" a "una strategia difendibile".

### 1.1 Modello di costo realistico
- **Problema:** 331/531 giocatori a riferimento 1; l'ottimizzatore ne sceglie 7
  (Koopmeiners FVM 20 a 1 credito) sfruttando l'errore di prezzo.
- **Implementazione:**
  - costo minimo funzione di FVM/quotazione (es. `max(1, round(α·quotazione))`
    per chi ha FVM sopra il 60° percentile di ruolo), con α dichiarato;
  - colonna `cost_low / cost_mid / cost_high` (soglia prudente, riferimento,
    soglia estesa) già disponibile nel dossier;
  - ottimizzazione su `cost_high` per i primi slot di ogni reparto
    (i giocatori contesi), `cost_mid` per le riserve.
- **DoD:** nessun titolare (depth ≤ 3) sotto il 25° percentile di prezzo del
  ruolo senza flag esplicito "scommessa".
- **Stima:** 3 h.

### 1.2 Alternative e sensibilità
- **Implementazione:**
  - top-N rose con vincolo di esclusione (no-good cut: dopo ogni soluzione,
    `Σ x_selezionati ≤ 24`), N = 5;
  - Monte Carlo sui costi (moltiplicatore log-normale per giocatore, σ≈0,25)
    → frequenza di selezione di ogni giocatore su 200 risoluzioni;
  - output `robustezza.csv`: giocatore, % selezione, costo mediano quando scelto.
- **DoD:** l'output distingue "pilastri" (>70% selezione) da "intercambiabili".
- **Stima:** 3 h.

### 1.3 Modificatore derivato, non arbitrario
- **Problema:** premio ×1,04 fissato a mano, solo sui difensori, ignora il
  portiere e la correlazione di squadra.
- **Implementazione:** stimare con `LineupOptimizer` (simulazione già corretta)
  il bonus atteso medio per blocco P+D al variare della qualità del reparto;
  convertire in un premio additivo per slot P1 e D1–D4 (non su tutti i D);
  opzionale: bonus per coppia portiere/difensore della stessa squadra.
- **DoD:** premio documentato con numero e intervallo nella doc; test che il
  premio è 0 con `defence_modifier=False`.
- **Stima:** 3 h.

### 1.4 Rispetto dei budget di reparto (opzionale, vincoli morbidi)
- Aggiungere vincoli per ruolo con tolleranza ±15% rispetto a `BUDGETS`, oppure
  riportare lo scostamento nel JSON. Oggi la rosa spende D 65 vs 85, A 269 vs 235:
  o si aggiornano i budget, o si vincola l'ottimizzatore — non entrambe le verità.
- **Stima:** 1 h.

---

## Fase 2 — Strumento per l'asta dal vivo (entro il 25/09)

Un piano statico si rompe al secondo giocatore battuto. Serve ri-ottimizzare.

### 2.1 Stato d'asta
- File `asta/stato_asta.csv` (workspace): `player_id, acquirente, prezzo`.
- Lo script legge lo stato, rimuove i giocatori venduti ad altri, fissa i
  propri acquisti (`x = 1`, costo reale), aggiorna budget residuo.

### 2.2 Comando di ri-ottimizzazione
- `scripts/optimize_auction_roster.py --state asta/stato_asta.csv` → in < 5 s:
  rosa residua ottimale, **prezzo massimo** per ogni obiettivo (differenza di
  obiettivo tra la rosa con e senza il giocatore, convertita in crediti), e le
  prime 3 alternative per slot.
- **DoD:** simulazione di un'asta di prova con 20 aggiudicazioni fittizie senza
  errori; tempo per ri-ottimizzazione < 5 s.
- **Stima:** 4 h.

### 2.3 Vincolo "bid-max"
- Il prezzo massimo di 2.2 sostituisce `soglia_estesa` come guida operativa.
  Documentare in `docs/auction_refresh.md`.

---

## Fase 3 — Qualità del modello (post-asta, ottobre)

### 3.1 Calendario reale nel simulatore
- Sostituire l'abbinamento casuale degli avversari con il calendario ufficiale
  (`calendario.csv` già esportato); forza avversario dal contesto squadra.
- **DoD:** backtest walk-forward 2025/26 con MAE non peggiore dell'attuale.

### 3.2 Obiettivo sopra rimpiazzo
- Utilità = contributo atteso oltre il sostituto di panchina (o soglia di
  rimpiazzo di ruolo), non fantavoto grezzo × p_plays. I pesi di profondità
  diventano derivati dalla simulazione di formazione invece che fissi.

### 3.3 Orizzonte stagionale
- Estendere la previsione oltre 8 giornate con decadimento di confidenza e
  scenari di mercato di gennaio; misurare quanto cambia la rosa.

### 3.4 Calibrazione prezzi della lega
- Dopo l'asta, registrare i prezzi reali di aggiudicazione (8 manager) e
  stimare la funzione prezzo = f(FVM, ruolo, quotazione). Base per aste di
  riparazione e per la prossima stagione.

### 3.5 Monitoraggio settimanale
- Dopo ogni giornata: confronto previsto vs osservato (MAE, calibrazione di
  `p_plays` e `p_good_mark`), salvato in `reports/`. Il controllo del modello
  neurale resta attivo: lo si rivaluta solo se batte il modello di base in
  walk-forward.

---

## Fase trasversale — Riproducibilità e repository

| Voce | Azione |
|---|---|
| Doppia copia del core | Un'unica checkout: `fantapredictor-workspace/fantapredictor_core` come submodule; eliminare o rendere symlink `fantapredictor/` |
| Workspace non committato | Commit del puntatore submodule e di config/report; DB e raw restano fuori da Git ma referenziati nel manifest con hash |
| Run manifest | Ogni output d'asta salva: commit core, hash snapshot, seed, `as_of`, parametri CLI |
| Test end-to-end | Un test su un mini-dataset sintetico che esegue forecast → dossier → ottimizzatore |

---

## Riepilogo priorità

| # | Voce | Fase | Stima | Bloccante per l'asta |
|---|---|---|---|---|
| 0.1 | Indici MILP | 0 | 0,5 h | sì |
| 0.2 | Doppio sconto indisponibilità | 0 | 1 h | sì |
| 0.3 | `as_of` deterministico | 0 | 0,5 h | sì |
| 0.4 | Riserva budget | 0 | 0,5 h | sì |
| 0.5 | Join per ID | 0 | 1,5 h | sì |
| 1.1 | Costi realistici | 1 | 3 h | sì |
| 1.2 | Alternative + sensibilità | 1 | 3 h | fortemente consigliato |
| 1.3 | Modificatore derivato | 1 | 3 h | consigliato |
| 2.x | Ri-ottimizzazione live | 2 | 4 h | fortemente consigliato |
| 3.x | Modello e calibrazione | 3 | — | no |

Totale fasi 0–2: circa 21 ore di lavoro, compatibile con la finestra fino al
25/09 solo se la Fase 1.3 e 1.4 vengono sacrificate in caso di ritardo.
