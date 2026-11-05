# Masterplan: modelli eseguibili e forma multiscala

Data: 5 novembre 2026. Stato: masterplan aggiornato con avanzamento verificabile; implementazione avviata, criteri di rilascio ancora da soddisfare.
Obiettivo: produrre distribuzioni riproducibili di presenza, minuti, voto e fantavoto per la prossima partita e usarle in un unico simulatore di formazione, con forma individuale, squadra, allenatore e disponibilità documentata.
Completamento: bundle caricabile in processo nuovo, replay senza informazioni future, backtest e calibrazione superati, formazione legale riproducibile e confronto con baseline. Un modello addestrato ma non validato resta NON PROMUOVIBILE.

## 1. Stato verificato e correzioni alla diagnosi iniziale

Ispezione core a039dba6c65510c80bd65983163c4d8a7d6c0383.
- `src/models/neural_network.py`: rete SHASH con teste voto/fantavoto, modelli giocatori di movimento/portieri, scaler; `save_model` scrive `.keras`, `load_latest_model` li legge. Non serve inventare un formato di pesi. Il caricamento seleziona però l'ultimo nome di metadati: occorre un registro di bundle completi e approvati, non ordinamento lessicografico.
- La cartella operativa ispezionata contiene metadati storici senza pesi. `is_fitted: true` in JSON non prova che un modello sia utilizzabile.
- `src/db/repository.py` ha già medie mobili last5 di punti/xG squadra e avversario con shift; `MatchDataBuilder` costruisce statistiche storiche espanse. Va estesa e unificata la copertura, non ricreato tutto.
- `docs/evaluation_results.md` documenta SHASH instabile e peggiore delle baseline; segnala forte mancanza di minuti Understat storici. Sono risultati storici documentati, non un nuovo backtest eseguito per questo piano.
- Advisory settimanale, propensity e simulazione privata seguono percorsi diversi: rischio di input, sconti presenza e aggiustamenti tattici discordanti.
- Ambiente rilevato: Python 3.12.3, TensorFlow 2.21.0, NumPy 2.5.2, pandas 3.0.5, scikit-learn 1.9.0; x86_64, i7-9750H, 6 core/12 thread, circa 15 GiB RAM. GPU non verificata: pianificare CPU. Versioni osservate non equivalgono a compatibilità certificata.

## 2. Decisione sui modelli e ricerca esterna

Scelta iniziale: mantenere baseline empiriche, completare SHASH esistente come candidato, aggiungere **un solo candidato tabellare CatBoost**. LightGBM è alternativa se il confronto controllato la giustifica. Non installare tutte le librerie insieme.

| Candidato | Tipo di artefatto | Impiego proposto | Vincoli / decisione |
|---|---|---|---|
| SHASH locale / Keras | Pesi da addestrare sui nostri target osservati | Voto e fantavoto condizionati a voto valido | Riutilizzo prioritario dell'infrastruttura, nessuna promozione automatica |
| CatBoost | Libreria, modello da addestrare; nessun peso Fantacalcio pronto verificato | Presenza, titolarità, minuti e quantili del rendimento; categorie ruolo/club/allenatore | CPU, dati tabellari; gestire esplicitamente missing categorici; priorità alta |
| LightGBM | Libreria, modello da addestrare | Benchmark tabellare alternativo | Aggiungerlo solo dopo benchmark minimo del primo candidato |
| NeuralForecast N-HiTS / TFT | Architetture da addestrare | Dinamica di squadra e giocatori con storia sufficiente | Dipendenza PyTorch separata, costo e sample size da misurare; fase successiva |
| Chronos-2 | Pesi generici preaddestrati, non sul nostro obiettivo | Esperimento su serie squadra/minuti e covariate | Modello generico; nessuna equivalenza a fantavoto Serie A. CPU/RAM da misurare; non prerequisito MVP |

Fonti primarie consultate il 5 novembre 2026:
- [Keras: salvataggio e caricamento](https://keras.io/guides/serialization_and_saving/): bundle `.keras`; verificare round-trip in processo separato.
- [CatBoost, repository ufficiale](https://github.com/catboost/catboost): boosting, classificazione/regressione, CPU/GPU; licenza Apache-2.0 da congelare al commit scelto.
- [LightGBM, repository ufficiale](https://github.com/lightgbm-org/LightGBM): boosting; alternativa CPU, licenza MIT da verificare al pin.
- [NeuralForecast, repository ufficiale](https://github.com/Nixtla/neuralforecast): N-HiTS/TFT e altri modelli, addestramento e forecast; licenza del commit da registrare.
- [Chronos, repository ufficiale](https://github.com/amazon-science/chronos-forecasting) e [model card Chronos-2](https://huggingface.co/autogluon/chronos-2/blob/main/README.md): pesi preaddestrati, covariate passate e future note, modello da 120M parametri. Registrare separatamente licenza codice e pesi.

Questa è una shortlist ragionata, non un benchmark eseguito né prova che sul web non esista altro. Nessun peso pronto specifico per il nostro scoring è stato verificato. Per ogni dipendenza: pin versione/commit, licenza, hash artefatti, compatibilità Python/CPU, prova offline, manutenzione; non eseguire codice remoto di checkpoint non verificato. Per modelli preaddestrati registrare cutoff/dataset di pretraining quando noti: se ignoti, backtest potenzialmente contaminato, solo evidenza prospettica per promozione.

## 3. Contratto temporale e acquisizione

Unità base: giocatore-partita, squadra-partita e gestione allenatore-partita, con ID stabili e identità datate. Ordinare per kickoff reale, non numero nominale della giornata; gestire recuperi, rinvii, trasferimenti e doppie gare.

Ogni fatto conserva `event_time`, `published_at` quando disponibile, `observed_at`, `available_at`, URL, provider, hash raw, revisione, qualità e scadenza. Una previsione al cutoff T vede solo fatti disponibili entro T. Se la pubblicazione storica non è dimostrabile, non ricostruire retroattivamente notizie/probabili usando lo snapshot odierno: segnare indisponibile e separare benchmark storico da raccolta prospettica.

Inventario iniziale obbligatorio: conteggi per stagione/ruolo/provider, copertura minuti e xG, missing, duplicati, cambi club, finestre allenatore, presenze senza voto. I soli voti non descrivono tutti i convocati: costruire il denominatore degli eleggibili e distinguere zero minuti, non convocato e dato ignoto.

Fonti: warehouse e voti ufficiali per target; calendari e tabellini con minuti; fonti ufficiali club per convocazioni, allenamento e disponibilità; notizie editoriali attribuite come seconda fonte. Integrare coppe/nazionali per carico quando la licenza e la copertura lo consentono. Senza tale copertura, etichettare il carico come parziale. FBref solo export manuali, nessun aggiramento dei blocchi. Per xG conservare provenienza e freschezza; non rendere corrente un dataset vecchio. Missing xG resta missing, mai zero implicito.

Eventuali nuovi schemi SQLite: migrazione versionata, ingestori idempotenti, backup e test di replay; versioni schema e progetto sincronizzate. Raw e dati personali rimangono nel workspace privato.

## 4. Motore della forma: finestre 3, 5, 10, 20 e lungo periodo

### Giocatore

Separare **ultime N presenze**, **ultime N partite della squadra** e finestre calendario 7/14/28 giorni. Un assente non scompare dalla misura di disponibilità solo perché si usano le presenze.
- Minuti, quota titolarità, quota partite a voto, permanenza fino al 60/75/90, sostituzioni e giorni dall'ultima presenza.
- Voto e fantavoto separati; gol, assist, rigori, ammonizioni/espulsioni; xG/xA, tiri, tocchi in area solo con copertura verificata.
- Statistiche per 90 minuti con denominatore minimo e regolarizzazione; non premiare un bonus in pochi minuti come forma consolidata.
- Medie/dispersione last3/5/10/20; differenze 5 meno 10/20; EWMA con emivite candidate 3/5/10 partite scelte nel training interno; livello stagionale e stagione precedente pesata.
- Residui rispetto a ruolo, minuti, forza avversario e campo stimati solo su passato; trend robusto e intervallo d'incertezza, non una pendenza trattata automaticamente come segnale.
- Dopo trasferimento separare storia personale e nuovo contesto, con shrinkage per pochi dati. Nessun azzeramento artificiale o carry-over integrale.

### Squadra e avversario

Finestre identiche su punti, gol fatti/subiti, xG/xGA se disponibili, tiri, clean sheet e ritmo. Aggiungere forza calendario stimata al cutoff, casa/trasferta, riposo, congestione, rotazioni e stabilità dell'XI. Separare risultati osservati e qualità delle occasioni; confronto 5 contro 10/20 e baseline stagionale. Non duplicare un effetto già incorporato in una previsione del giocatore.

### Allenatore

Gestione datata, partite dal cambio, moduli effettivamente osservati, stabilità della selezione, minuti/sostituzioni per ruolo, quote di gol/assist e stile della squadra. Finestre last5/10/20 della gestione e storia pregressa con pooling gerarchico; nuovo allenatore torna al prior finché la copertura è insufficiente. Separare forza rosa/avversario dall'associazione allenatore-rendimento: nessuna pretesa causale. Head-to-head e “effetto scossa” solo candidati da ablation, peso zero se instabili. Conservare il coefficiente attuale fino a nuova validazione.

### Condizione fisica e prontezza

Output distinto dalla forma tecnica: **disponibilità osservata** e **prontezza stimata**, non diagnosi o misura fisiologica diretta.
- Stato documentato: assente, differenziato, rientrato in gruppo, convocato, limitazione dichiarata dei minuti, informazione ignota; fonte, data e grado di certezza.
- Proxy: minuti 7/14/28 giorni, riposo, giorni dall'infortunio/rientro, progressione minuti nelle ultime gare, trasferte ove disponibili e copertura del carico.
- Minuti bassi possono dipendere da scelta tattica: includere ruolo/rotazione e non etichettarli automaticamente come problema fisico.
- Predire `P(convocato)`, `P(titolare|convocato)`, `P(minuti>0)`, distribuzione minuti e `P(voto valido|minuti,contesto)` con calibrazione. Tenere separati infortunio, squalifica e mancata scelta tecnica.
- Nessun indice “fitness 87/100” senza target e calibrazione. Se manca evidenza, mostrare “condizione non osservabile”; la proxy non diventa diagnosi né probabilità d'infortunio.

Tutte le feature hanno conteggio osservazioni, missing mask, quota di copertura, età del dato, versione e fallback. Requisito minimo per un trend individuale last5: almeno tre osservazioni valide, altrimenti prior e segnalazione; soglia da congelare prima del test.

## 5. Modello congiunto e bundle eseguibile

Pipeline proposta: dati al cutoff → feature multiscala → disponibilità/minuti → distribuzioni condizionate voto/bonus → simulazione congiunta → ottimizzazione XI/panchina/Switch.

Non moltiplicare due volte presenza, minuti o effetto allenatore. L'assenza è uno stato discreto distinto dal fantavoto zero; un voto mancante non è un target zero. Voto e fantavoto devono mantenere dipendenza per calcolare il modificatore. Prima fase: ricampionamento congiunto di residui osservati; successivamente distribuzione voto più eventi bonus/malus o copula validata. La SHASH a due marginali da sola non certifica la dipendenza.

Bundle immutabile per versione:
- pesi reali `.keras` / formato nativo del candidato; scaler/encoder e ordine/dtype feature;
- schema feature/target, regole scoring, unità e missing policy;
- cutoff training, fingerprint dati, git SHA, ambiente bloccato, seed, iperparametri;
- calibrazione, report OOS, metriche per ruolo e copertura; hash di ogni file;
- stato `trained`, `validated`, `shadow`, `approved`, `rejected`, motivo e ambito di validità.

Scrittura atomica in directory temporanea, verifica e pubblicazione del manifest per ultima. Loader per ID esplicito o puntatore locale al modello approvato; mai “ultimo file = migliore modello”. Bundle parziale/corrotto/incompatibile: rifiuto spiegato e fallback nominato. Test nuovo processo: stesse predizioni entro tolleranza numerica predefinita (inizialmente 1e-5), parametri finiti, scale positive, q10<=q50<=q90, campioni plausibili, assenza di target futuri. Pesare separatamente il gate portieri e movimento; fallback per coorte non coperta.

## 6. Simulatore e formazione

Un unico contratto versionato di predizione usato da `recommend_lineup.py`, optimizer e simulazioni del workspace. Report esplicito di modello realmente eseguito e fallback per giocatore.
- Campioni correlati per partita e squadra; un solo portiere per club, minuti e partecipazioni coerenti. Correlazioni stimate e confrontate con baseline indipendente.
- Modificatore, numero totale sostituzioni, ruoli e Basic Switch parametrizzati dalle regole reali. Nessuno Switch portiere automatico. Stesso modulo nei confronti che lo richiedono.
- Rendere la modulazione contesto capace di descrivere aumenti e riduzioni solo con distribuzioni valide; verificare l'attuale limite che attenua i bonus senza aumentarli.
- Ricerca su XI e panchina; budget di ricerca e seed dichiarati, campioni separati selezione/valutazione, benchmark esaustivo su casi ridotti. Non chiamare globale un ottimo euristico.
- Obiettivo default fantapunti attesi; rischio di giocare in dieci e quantili come diagnostica. Probabilità di vittoria soltanto con avversario osservato o scenario dichiarato.

## 7. Valutazione e criteri di promozione

Protocollo congelato prima del confronto: training espanso su stagioni precedenti, tuning/calibrazione su finestre cronologiche interne, test futuro intatto; nessuna divisione casuale delle righe giocatore-partita. Scaler, imputazione, forza avversario e selezione feature stimati nel training. Confronti appaiati su stesse partite, cutoff, rosa e regole.

Baseline obbligatorie: mediana di ruolo, prior espanso, EWMA, motore empirico attuale. Ablation: baseline → last5 → 3/5/10/20 → squadra/avversario → allenatore → carico/disponibilità → caratteristiche statiche. Valutare blocchi separati e combinazioni principali, non aggiungere tutti gli effetti presumendo additività.

Metriche: Brier/log-loss e curve di calibrazione per presenza/titolarità; errore e distribuzione minuti; MAE voto/fantavoto, pinball/CRPS e copertura/ampiezza q10–q90; fantapunti realizzati delle formazioni, coperture e giocatori senza voto. Report per ruolo, neoarrivati, rientri, pochi minuti, provider e missingness. Nessun modello deve vincere soltanto perché sceglie una popolazione più facile.

Soglie iniziali proposte da congelare prima del primo test, non risultati già acquisiti:
1. Gate tecnico e temporale tutti passati; zero leakage noto e target artificiali.
2. Almeno 3 finestre temporali disgiunte e almeno 30 giornate OOS complessive per tentare la promozione; contano blocchi partita/giornata, non migliaia di righe correlate. Verifica di potenza/MDE: il minimo non garantisce potenza.
3. Miglioramento relativo >=2% sulla metrica primaria probabilistica predefinita rispetto alla migliore baseline; CI 95% del delta con bootstrap a blocchi favorevole. Correzione Holm per confronti primari multipli; selezione modello nel tuning, non nel test.
4. Copertura aggregata intervallo 80% fra 75% e 85% e ampiezza/interval score non peggiori; valutare anche incertezza e sottogruppi. Nessuna garanzia conformal i.i.d. trasferita automaticamente a serie dipendenti.
5. Nessun peggioramento MAE >2% aggregato; analisi delle coorti con eventuale fallback. Per cambiare il consigliere formazione: guadagno medio pratico proposto >=0,25 punti/turno con CI a blocchi favorevole e nessun aumento dimostrato del rischio senza voto.
6. Evidenza insufficiente, metriche discordanti o campioni piccoli: NON PROMUOVIBILE; continuare shadow senza abbassare soglie dopo aver visto il test.

CI del Monte Carlo e CI del backtest sono cose diverse. Aumentare a 100.000 simulazioni riduce l'errore numerico, non prova accuratezza sul campo. Valutare almeno tre seed training per stabilità dei candidati stocastici.

## 8. Fasi, dipendenze e deliverable

| Fase | Lavoro e file principali | Evidenza di uscita | Stima lavoro attivo* |
|---|---|---|---|
| P0 | Inventario dati/artefatti, `audit_model_readiness.py`, ambiente | Matrice copertura, stato bundle e motivi di blocco; confronto requisiti disponibili | 1–2 giorni |
| P1 | Contratto temporale, ingestione minuti/news, repository e `MatchDataBuilder` | Replay cutoff, test rinvii/trasferimenti/revisioni, snapshot manifest | 3–5 giorni |
| P2 | `src/models/form_features.py`, `readiness.py`, feature 3/5/10/20 | Test finestre e missing; ablation descrittiva, nessuna promessa predittiva | 3–5 giorni |
| P3 | Rafforzare SHASH e `model_registry.py`; training baseline/CatBoost | Bundle completo e round-trip nuovo processo, predizioni offline | 2–4 giorni |
| P4 | `backtest_form_models.py`, evaluation, calibrazione | Protocollo e report OOS per tutti i candidati; approvato o NON PROMUOVIBILE | 3–5 giorni |
| P5 | Contratto unico advisory/simulatore, benchmark formazione | Parità di input, scoring e sostituzioni; test legali e riproducibilità | 2–4 giorni |
| P6 | Shadow operativo e revisione | Registro previsioni bloccate prima delle gare e confronto dopo voti ufficiali | almeno 6–8 giornate osservate |
| P7 opzionale | Chronos-2 / N-HiTS e pesi esterni isolati | Beneficio incrementale OOS e costo misurato; nessun cambio se non passano i gate | 3–6 giorni per candidato |

*Stime di pianificazione, non preventivo o runtime misurato. P0 precede tutto; P1→P2→P3→P4→P5→P6. Un bundle SHASH minimo può essere verificato in P0/P3 senza attendere feature complete, ma non promosso. La raccolta prospettica parte in P1; 6–8 turni shadow non sostituiscono i requisiti statistici.

Budget iniziale di benchmark proposto: CPU, massimo 4 thread, memoria di processo <=6 GiB, 10 configurazioni per candidato, 3 seed finalisti, <=2 ore per sessione di confronto. Misurare un piccolo pilot e rivedere il budget prima della griglia; nessun requisito GPU implicito. Target operativo da verificare: inferenza intera giornata <=60 secondi, simulazione selezione/valutazione <=5 minuti. Esperimenti PyTorch in ambiente separato, senza aggiornare l'ambiente produttivo per tentativi.

## 9. Test e rilascio

Test mirati: futuro aggiunto non cambia feature del passato; pubblicazione tardiva non visibile prima del cutoff; last5 presenze vs last5 gare corrette; missing distinto da zero; club/coach datati; carico coppe parziale marcato; bundle mancante/corrotto; encoder sconosciuti; round-trip; seed e hash; assenza non confusa con voto zero; dipendenza voto/fantavoto; modificatore e sostituzioni; parità dei diversi entrypoint.

Per implementazioni: suite core richiesta da AGENTS, gate release e validazione datata con dati reali locali; nessuna rete nei test unitari. Aggiornare README/CHANGELOG e documentazione di modello. Artefatti e dati privati esclusi dal core pubblico. Attivazione esplicita della versione validata con rollback alla precedente; niente riaddestramento/promozione silenziosa o invio automatico di formazioni.

Deliverable finale per l'utente: XI e panchina, alternative a modulo fisso, fonti/freschezza, modello per giocatore, motivazioni di forma e disponibilità, intervalli condizionati, confronto baseline e limiti. Se i dati non consentono di stimare condizione fisica o trend, dichiararlo nella riga del giocatore.


## 10. Avanzamento verificato e backlog eseguibile

Aggiornamento del 5 novembre 2026. Questo registro sostituisce interpretazioni del tipo “fase completata perché esiste il file”. Il completamento del piano progettuale non implica completamento dell'implementazione o promozione del modello.

| Fase | Stato effettivo | Evidenza disponibile | Lavoro necessario per chiuderla |
|---|---|---|---|
| P0 | Parziale | `audit_model_readiness.py` e `inventory_form_data.py`: snapshot SQLite con hash, conteggi per stagione/provider e possibili duplicati; nessun bundle storico completo | Inventario fonti e file grezzi xG/news, copertura minuti per partita e denominatore convocati |
| P1 | Fondazione implementata | `form_features.visible_history`: cutoff, revisioni, timestamp obbligatori e duplicati ambigui rifiutati | Adattatori warehouse, acquisizione con available_at reale e identità temporali; replay rinvii e trasferimenti |
| P2 | Fondazione implementata | `form_snapshot`: 3/5/10/20 eventi/presenze, EWMA, delta5–20, carico 7/14/28; `readiness_snapshot`: evidenza non scaduta e attribuita | Dataset denominatore eleggibili, aggregati squadra/allenatore, stime minuti calibrate e ablation |
| P3 | Fondazione implementata | `research_store`: pubblicazione bundle immutabile, hash e verifica; SHASH save/load già esistente | Collegare registry al loader SHASH; provenienza completa, round-trip in processo nuovo e pesi su dati reali; candidato CatBoost |
| P4 | Da implementare per il nuovo motore | Evaluation storico preesistente e baseline; nessun nuovo risultato predittivo dichiarato | Backtest multiscala con tuning interno, protocolli congelati, bootstrap a blocchi, correzioni multiple e calibrazione |
| P5 | Da implementare | Simulatore e advisory esistenti | Adattatore predizioni condiviso, dipendenze voto/bonus, regole panchina/Switch e test di parità |
| P6 | Registro implementato; raccolta futura da avviare | `record_shadow`: timestamp reale, deadline futura e creazione esclusiva | Collegamento alla pipeline; previsioni reali archiviate prima delle partite, scoring post-voti, almeno 6–8 turni e gate statistici |
| P7 | Opzionale, differito | Shortlist con fonti primarie nel piano | Benchmark isolato e provenienza pesi, solo dopo baseline/P4 |

I test dei nuovi componenti usano entità anonime e verificano proprietà temporali, missing distinti da zero, integrità, scadenza e impossibilità di riscrivere lo shadow. Non costituiscono evidenza di accuratezza statistica. Le API sono componenti di ricerca e non sono ancora collegate automaticamente ai consigli operativi.

### 10.1 Sequenza di implementazione vincolante

1. **D01 — audit esteso.** Arricchire P0 con schema e copertura per stagione/provider di minuti, xG e news. Produrre `data_inventory.json` con hash DB e file analizzati. Non inferire copertura globale da una sola tabella.
2. **D02 — adattatori e raccolta.** Definire record JSONL di evidenza con entity/event ID, club e gestione datati, event_time, observed_at, available_at, fonte/hash, revisione, scadenza e unità. Il tempo di acquisizione odierno non può diventare una falsa pubblicazione storica. Deduplicare per identità fonte-evento-revisione. Import idempotente e nessuna modifica distruttiva del warehouse.
3. **D03 — denominatore.** Costruire giocatore-partita eleggibile da membership e tabellini, con target separati convocato/titolare/minuti/voto. Escludere dal training di una testa le etichette ignote; non trasformarle in zero. Rendere esplicite coppe e nazionali mancanti.
4. **F01 — feature comuni.** Collegare i record validi alle funzioni esistenti; aggregazioni per giocatore, squadra e gestione allenatore. La stessa API può riepilogare metriche squadra/allenatore, ma gruppi, metriche e denominatori devono essere preparati dagli adattatori. Nessuna proprietà personale va sommata come fosse dato squadra. Collegare avversario al kickoff corretto.
5. **F02 — residuali e caratteristiche.** Fit sul solo training di forza calendario, baseline ruolo e regressione minuti; residui out-of-fold cronologici per le feature. Statistiche per90 regolarizzate, media stagionale e stagione precedente, stabilità modulo/XI. Caratteristiche esterne solo se migliorano OOS, altrimenti peso zero.
6. **M01 — bundle SHASH.** Addestrare un candidato esplicito, salvare `.keras` e scaler, pubblicare con registry e verificarne hash e predizioni in processo separato. Il manifest `trained` non abilita l'uso operativo. Un gate distinto registra valutazione e ambito; il loader deve rifiutare path esterni e artefatti corrotti prima del caricamento.
7. **M02 — candidato tabellare.** Testare disponibilità CatBoost in ambiente isolato, fissare versione e licenza; usare encoding/missing e feature identici nel training/inferenza. Se i dati non supportano le teste convocazione/minuti, produrre un report esplicito di testa non addestrabile. Nessuna probabilità sintetica.
8. **E01 — backtest e calibrazione.** Congelare `evaluation_protocol.json` prima dei risultati: split con timestamp/ID, dataset hash, feature, seed, griglia, budget, metrica primaria, baseline, numero confronti, soglie e blocchi bootstrap. Nessun test scelto dopo aver visto il vincitore.
9. **S01 — contratto simulatore.** `PredictionBatch` versionato con cutoff, model ID/source, entità, probabilità calibrate quando disponibili, campioni congiunti voto/fantavoto e stato assente distinto. Validare dimensioni, valori finiti, role IDs e scoring; consentire un fallback dichiarato per ogni entità.
10. **O01 — raccolta e scoring shadow.** Registrare il batch prima della deadline usando `record_shadow`; associare hash input e bundle. Salvare risultati ufficiali e scoring in artefatti separati: la previsione originaria resta immutabile. Eseguire una sola volta per run ID, senza timer o invii automatici.
11. **R01 — rilascio verificato.** Suite core, regression temporali, smoke su dati reali, gate datato, benchmark runtime e report confronto; attivare solo un candidato che supera P4/P6. Se nessuno vince, completamento tecnico con baseline operativa e candidati NON PROMUOVIBILI.

### 10.2 Contratti minimi dei deliverable mancanti

- `data_inventory.json`: input hash, tabelle/provider esaminati, stagioni, target presenti/ignoti, identità non riconciliate e limiti. Conteggi per fonte non sommati senza deduplica.
- `feature_manifest.json`: nomi/dtype/unità, gruppo e finestra, cutoff, campione/copertura, regole missing/prior, versione generatore e origine. `events_lastN` è la finestra di partite eleggibili solo se il denominatore è completo.
- `bundle/manifest.json`: pesi/scaler/feature, hash, schema, cutoff, codice, ambiente e stato iniziale trained. L'attuale registry verifica hash e immutabilità; deve essere esteso con validazione semantica e percorso di approvazione documentato prima dell'uso operativo.
- `evaluation_protocol.json` e `evaluation_report.json`: disegno congelato e risultati distinti, record delle prove fallite, report per coorte e ragione di NON PROMUOVIBILITÀ. I record di test non possono essere riutilizzati nel tuning dello stesso esperimento.
- `shadow/<run_id>.json`: registrazione reale prima di cutoff, batch predittivo, fonti/hash e modello. Lo store implementato impone deadline e unicità; verifica della struttura di PredictionBatch e scoring sono attività S01/O01.

### 10.3 Accettazione finale e dipendenze esterne

Per dichiarare completa l'implementazione occorre chiudere D01–R01 con comando, exit code, conteggi e percorsi degli artefatti nel workspace. Lo stato di ogni fase deve indicare `implemented`, `validated`, `waiting_for_observations` o `not_implemented`; evitare una percentuale aggregata che confonda codice e dati.

Dipendenze che il codice non può creare retroattivamente: pubblicazione storica delle news, minuti mancanti, denominatore convocati, copertura coppe/nazionali e nuove giornate shadow. Per ciascuna registrare fonte mancante, periodo e target coinvolto; usare baseline o limitare l'ambito del candidato. L'attesa prospettica non autorizza a dichiarare passata una validazione non ancora osservata.

Il piano progettuale è ora completo di backlog, contratti, dipendenze e criteri di uscita. Il registro sopra resta la fonte dello stato d'implementazione.

### 10.4 Verifica di questo aggiornamento

Test mirati delle nuove utility e audit passati; suite completa `python -m pytest -q` terminata con exit code 0. `git diff --check` e compilazione dei tre moduli completati. Questi controlli verificano il codice, non chiudono i gate predittivi P4/P6. Nessun nuovo modello addestrato o approvato in questo aggiornamento.

### 10.5 Inventario esteso

`inventory_form_data.py` acquisisce una copia SQLite consistente, incluso WAL, e ne registra SHA-256. I conteggi sono per provider e stagione e includono minuti/xG stagionali, voti, statistiche squadra, note di disponibilità e potenziali duplicati. Sono conteggi di righe, non indicano freschezza, osservabilità storica o qualità dell’abbinamento. Restano da inventariare i file grezzi e le fonti esterne; D01 rimane parziale.

### 10.6 Acquisizione e simulazione con trend

Nuova raccolta privata validata: 26.990 record giocatore-partita e 860 match con voti, ID e date riconciliati. Dati squadra Football-Data, archivi Wyscout/StatsBomb e storico Understat restano separati per provider e competizione. Nessuna sovrascrittura del warehouse; il limite convocati e la disponibilità storica delle notizie restano aperti.

Completato un esperimento privato di simulazione con feature cronologiche di voto/fantavoto/minuti sulle ultime 3/5/10/20 presenze e forma squadra/avversario 5/10/20 partite. Ridge con scaling e imputazione appresi nel training; selezione della penalizzazione su un segmento successivo e valutazione su dieci giornate tenute separate. Successivo refit sui risultati disponibili per lo scenario corrente. La correzione delle medie campionate è limitata a un punto per controllare l'esperimento, non è un peso validato per il rilascio. Il confronto usa 2.000 estrazioni di selezione e 30.000 indipendenti di valutazione, stessi seed fra scenari. Il contesto allenatore del motore empirico è conservato; non si attribuisce efficacia a un nuovo modello allenatore né a una misura clinica della condizione fisica. L'esperimento non chiude P3–P6 o il gate di promozione.

Verifiche dell’esperimento: 14 varianti di formazione valutate; caricamento indipendente dei pesi Ridge numerici con errore massimo nullo sulle predizioni salvate; split storico senza sovrapposizione fra fine training e inizio test. MAE fantavoto 0,8646 contro 0,8970 della baseline ultime 20 presenze su 3.156 osservazioni/100 match/10 giornate. Il confronto non sostituisce i gate completi del masterplan.
