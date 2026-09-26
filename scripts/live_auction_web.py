#!/usr/bin/env python3
"""Local web console for the live auction.

Single-user, single-page, mobile-friendly interface on top of the same
forecast, dossier, state CSV and ``LivePlanner`` used by the CLI console.
The server binds to ``127.0.0.1`` by default, serves the page and the JSON
API from the same origin, and accepts mutations only with a per-startup
random token plus the expected origin. The auction state is rewritten
atomically and guarded by the same ``StateLock`` the CLI holds, so console
and web can never write the log at the same time.

Connections run independently so idle browser sockets cannot block the UI.
A shared operation lock serializes planning and mutations: MILP contexts
are mutable and must never be used concurrently.
"""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import sys
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.live_auction import make_planner, write_state
from src.models.auction_optimizer import InfeasibleRosterError
from src.models.live_auction import (
    _key,
    LivePlanner,
    manager_summary,
    read_state,
    record_sale,
    resolve_state,
    undo_last,
)
from src.utils.state_lock import StateLock

MAX_BODY = 64 * 1024
TOKEN_HEADER = "X-Auction-Token"
SERVER_NAME = "FantaPredictorAuctionWeb/1.0"


class AuctionWebServer(ThreadingHTTPServer):
    """HTTPServer carrying the planner, state and per-startup security token."""

    # server_close must finish pending writes before main releases StateLock.
    daemon_threads = False

    def __init__(self, planner: LivePlanner, state: pd.DataFrame, state_path: Path,
                 host: str, port: int, token: str):
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError("Il server accetta solo 127.0.0.1 o localhost")
        self.operation_lock = RLock()
        super().__init__((host, port), _AuctionHandler)
        self.planner = planner
        self.state = state
        self.state_path = Path(state_path)
        self.token = token
        self.lock = StateLock(self.state_path)
        bound_port = self.server_address[1]
        self.allowed_hosts = {f"{h}:{bound_port}" for h in ("127.0.0.1", "localhost")}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}

    @property
    def origin(self) -> str:
        host = self.server_address[0]
        return f"http://{host}:{self.server_address[1]}"


class _AuctionHandler(BaseHTTPRequestHandler):
    server: AuctionWebServer
    server_version = SERVER_NAME
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------------

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def end_headers(self) -> None:
        self.close_connection = True
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _check_host(self) -> bool:
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.server.allowed_hosts:
            self._fail(403, "Host non atteso")
            return False
        return True

    def log_message(self, fmt: str, *args) -> None:
        print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {self.address_string()} "
              f"{fmt % args}", file=sys.stderr)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data) -> None:
        self._json(200, {"ok": True, "timestamp": now_iso(), "data": data})

    def _fail(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _status_for(self, exc: Exception) -> int:
        message = str(exc)
        conflicts = ("Sold twice", "already sold", "more players than slots",
                     "cannot fill", "holds the lock", "niente da annullare")
        if isinstance(exc, InfeasibleRosterError) or any(part in message for part in conflicts):
            return 409
        return 400

    # -- mutation guards -----------------------------------------------------

    def _check_mutation(self) -> bool:
        """Origin and token checks for POST; false means the reply was sent."""
        origin = self.headers.get("Origin", "")
        if origin and origin.rstrip("/") not in self.server.allowed_origins:
            self.close_connection = True  # unread body: never reuse the socket
            self._fail(403, "Origin non atteso")
            return False
        token = self.headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(token.encode("utf-8"), self.server.token.encode("utf-8")):
            self.close_connection = True
            self._fail(403, "Token mancante o errato")
            return False
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            self.close_connection = True
            self._fail(415, "Content-Type deve essere application/json")
            return False
        length = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
            self._fail(400, "Framing del body non valido")
            return False
        if length is None:
            self._fail(411, "Manca Content-Length")
            return False
        try:
            if int(length) < 0:
                raise ValueError
            if int(length) > MAX_BODY:
                self.close_connection = True
                self._fail(413, "Body troppo grande")
                return False
        except ValueError:
            self._fail(400, "Content-Length non valido")
            return False
        return True

    def _read_json(self) -> dict:
        length = int(self.headers["Content-Length"])
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Body non è JSON valido")
        if not isinstance(payload, dict):
            raise ValueError("Body deve essere un oggetto JSON")
        return payload

    # -- shared payload builders --------------------------------------------

    def _plan_payload(self, state=None):
        if state is None:
            state = self.server.state
        plan = self.server.planner.plan(state)
        roster = [
            {"role": row["role"], "depth": int(row["depth"]), "player": row["player"],
             "team": row["team"], "stato": row["stato"], "crediti": int(row["crediti"]),
             "expected_fantavoto": float(row["expected_fantavoto"]),
             "p_plays": float(row["p_plays"])}
            for _, row in plan.roster.iterrows()
        ]
        managers = manager_summary(resolve_state(state, self.server.planner.full),
                                   self.server.planner.me, self.server.planner.managers,
                                   self.server.planner.config.budget)
        return {
            "objective": float(plan.objective),
            "credit_value": float(plan.credit_value),
            "market_factor": float(plan.market_factor),
            "seconds": float(plan.seconds),
            "my_budget_left": int(plan.my_budget_left),
            "my_max_bid": int(plan.my_max_bid),
            "sales": int(len(state)),
            "roster": roster,
            "managers": managers.to_dict(orient="records"),
        }

    # -- routes --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_host():
            return
        path = urlparse(self.path).path
        route = {
            "/": self._serve_page,
            "/api/health": self._handle_health,
            "/api/plan": self._handle_plan,
            "/api/bid": self._handle_bid,
            "/api/managers": self._handle_managers,
            "/api/search": self._handle_search,
        }.get(path.rstrip("/") if path != "/" else path)
        if route is None:
            self._fail(404, "Endpoint sconosciuto")
            return
        try:
            with self.server.operation_lock:
                route()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (KeyError, ValueError) as exc:
            self._fail(self._status_for(exc), str(exc))
        except Exception:  # noqa: BLE001 - reply JSON, never leak the traceback
            traceback.print_exc()
            self._fail(500, "internal error")

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_host():
            return
        path = urlparse(self.path).path.rstrip("/")
        route = {"/api/sale": self._handle_sale, "/api/undo": self._handle_undo}.get(path)
        if route is None:
            self._fail(404, "Endpoint sconosciuto")
            return
        if not self._check_mutation():
            return
        try:
            with self.server.operation_lock:
                route()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (KeyError, ValueError) as exc:
            # Validation runs before any write, so the CSV is untouched.
            self._fail(self._status_for(exc), str(exc))
        except Exception:  # noqa: BLE001 - reply JSON, never leak the traceback
            traceback.print_exc()
            self._fail(500, "internal error")

    def _serve_page(self) -> None:
        body = (PAGE_HTML.replace("__TOKEN__", self.server.token)
                .replace("__ME__", json.dumps(self.server.planner.me).replace("<", "\\u003c"))
                .encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_health(self) -> None:
        self._ok({
            "status": "ok",
            "sales": int(len(self.server.state)),
            "players": int(len(self.server.planner.full)),
            "state": self.server.state_path.name,
            "python": sys.version.split()[0],
            "manager_me": self.server.planner.me,
        })

    def _handle_plan(self) -> None:
        self._ok(self._plan_payload())

    def _handle_bid(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        player = (query.get("player") or [""])[0].strip()
        if not player:
            self._fail(400, "Parametro 'player' mancante")
            return
        bid = self.server.planner.bid(self.server.state, player)
        managers = manager_summary(resolve_state(self.server.state, self.server.planner.full),
                                   self.server.planner.me, self.server.planner.managers,
                                   self.server.planner.config.budget)
        role = bid["role"]
        rivals = []
        for _, r in managers.iterrows():
            if r["acquirente"] != self.server.planner.me and int(r[f"aperti_{role}"]) > 0 \
                    and int(r["offerta_max"]) > 0:
                rivals.append({"acquirente": r["acquirente"], "offerta_max": int(r["offerta_max"])})
        rivals.sort(key=lambda r: -r["offerta_max"])
        self._ok({
            "player": bid["player"], "team": bid["team"], "role": bid["role"],
            "riferimento": int(bid["riferimento"]), "nel_piano": bool(bid["nel_piano"]),
            "offerta_max": int(bid["offerta_max"]), "motivo": bid["motivo"],
            "se_lo_perdi": bid["se_lo_perdi"],
            "valore_vs_alternativa": float(bid["valore_vs_alternativa"]),
            "secondi": float(bid["secondi"]), "rivali": rivals[:3],
        })

    def _handle_managers(self) -> None:
        managers = manager_summary(resolve_state(self.server.state, self.server.planner.full),
                                   self.server.planner.me, self.server.planner.managers,
                                   self.server.planner.config.budget)
        self._ok({"managers": managers.to_dict(orient="records")})

    def _handle_search(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        text = _key((query.get("q") or [""])[0].strip())
        if not text:
            self._ok({"results": []})
            return
        pool = self.server.planner.full
        keys = pool["player"].map(_key)
        tokens = text.split()
        prefix = pool.index[keys.map(lambda name: any(
            len(name.split()[start:]) >= len(tokens) and all(
                part.startswith(token) for part, token in zip(name.split()[start:], tokens))
            for start in range(len(name.split()))))]
        by_id = pd.to_numeric(pool["source_ref"], errors="coerce").eq(int(text)) if text.isdigit() else False
        match = pool.index[keys.str.contains(text, regex=False)
                           | pool["team"].map(_key).str.contains(text, regex=False) | by_id]
        order = prefix.tolist() + [i for i in match if i not in set(prefix)]
        rows = []
        for i in order[:20]:
            rows.append({"player": pool.at[i, "player"], "team": pool.at[i, "team"],
                         "role": pool.at[i, "role"],
                         "id": int(pool.at[i, "source_ref"]) if pd.notna(pool.at[i, "source_ref"]) else None})
        self._ok({"results": rows})

    def _handle_sale(self) -> None:
        payload = self._read_json()
        player = payload.get("player")
        buyer = payload.get("buyer", payload.get("acquirente"))
        price = payload.get("price", payload.get("prezzo"))
        if not isinstance(player, str) or not player.strip():
            raise ValueError("'player' deve essere un nome o un id ufficiale")
        if not isinstance(buyer, str) or not buyer.strip():
            raise ValueError("'buyer' è obbligatorio")
        if isinstance(price, bool) or not isinstance(price, int) or price < 1:
            raise ValueError("'price' deve essere un intero >= 1")
        sale = {"giocatore": player.strip(), "acquirente": buyer.strip(), "prezzo": price}
        new_state, canonical = record_sale(self.server.planner, self.server.state, sale)
        self._commit_state(new_state, "sale", canonical)

    def _handle_undo(self) -> None:
        try:
            self._read_json()
        except ValueError:
            self._fail(400, "Body deve essere un oggetto JSON, anche vuoto ({})")
            return
        new_state, undone = undo_last(self.server.planner, self.server.state)
        self._commit_state(new_state, "undone", undone)

    def _commit_state(self, state: pd.DataFrame, field: str, record: dict) -> None:
        # Solve and serialize the entire candidate response before committing.
        # A solver or disk failure leaves both the CSV and in-memory state intact.
        payload = {field: record, "plan": self._plan_payload(state)}
        json.dumps(payload, allow_nan=False)
        write_state(state, self.server.state_path)
        self.server.state = state
        self._ok(payload)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--dossier-players", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True, help="Auction log CSV (created if missing)")
    parser.add_argument("--me", default="io", help="Your name as buyer in the log")
    parser.add_argument("--managers", type=int, default=8)
    parser.add_argument("--budget", type=int, default=500)
    parser.add_argument("--reserve", type=int, default=0)
    parser.add_argument("--defence-modifier", action="store_true")
    parser.add_argument("--quotation-floor", type=float, default=0.5)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--modifier-season", default="2025/26")
    parser.add_argument("--no-market-scaling", action="store_true")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"),
                        help="Loopback bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Listen port (default 8765)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    planner = make_planner(args)
    state_lock = StateLock(args.state)
    try:
        state_lock.acquire()
    except RuntimeError as exc:
        print(f"errore: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        state = read_state(args.state)
        resolve_state(state, planner.full)  # fail early on a bad log
        manager_summary(resolve_state(state, planner.full), planner.me, planner.managers,
                        planner.config.budget)
        token = secrets.token_urlsafe(32)
        server = AuctionWebServer(planner, state, args.state, args.host, args.port, token)
        print(f"asta web su {server.origin} (token {token[:8]}…)")
        print(f"stato: {len(state)} aggiudicazioni in {args.state}")
        print("Ctrl-C per fermare il server")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\narresto")
        finally:
            server.server_close()
    finally:
        state_lock.release()


PAGE_HTML = r"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Asta — console web</title>
<style>
:root { color-scheme: light; --acc:#0f6b3c; --bg:#f6f7f4; --card:#ffffff; --ink:#1c241f; --mut:#5c6a61; --err:#b3202e; --ok:#0f6b3c; --line:#dde3dc; }
* { box-sizing: border-box; }
body { margin:0; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--ink); }
header { position:sticky; top:0; background:var(--card); border-bottom:1px solid var(--line); padding:10px 14px; display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; }
header h1 { font-size:1.05rem; margin:0; }
header .stats { display:flex; gap:16px; flex-wrap:wrap; font-variant-numeric:tabular-nums; }
.stat b { color:var(--acc); font-size:1.05rem; }
main { max-width:780px; margin:0 auto; padding:12px 14px 48px; display:flex; flex-direction:column; gap:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.card h2 { font-size:.95rem; margin:0 0 8px; color:var(--mut); font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
input, select, button { font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; }
button { background:var(--acc); color:#fff; border:none; cursor:pointer; }
button.sec { background:#eef2ee; color:var(--ink); border:1px solid var(--line); }
button.danger { background:#fff0f1; color:var(--err); border:1px solid #f3c8cd; }
table { width:100%; border-collapse:collapse; font-size:.9rem; }
th, td { text-align:left; padding:5px 6px; border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }
th { color:var(--mut); font-weight:600; }
.preso { color:var(--ok); font-weight:600; }
#results { list-style:none; margin:6px 0 0; padding:0; }
#results li { padding:8px 4px; border-bottom:1px solid var(--line); cursor:pointer; display:flex; justify-content:space-between; gap:8px; }
#results li:hover { background:#f0f6f1; }
#banner { display:none; background:#fff0f1; color:var(--err); border:1px solid #f3c8cd; border-radius:10px; padding:10px 14px; }
.big { font-size:1.15rem; font-weight:700; color:var(--acc); }
.mut { color:var(--mut); }
.tags { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
.tag { background:#eef2ee; border-radius:999px; padding:2px 9px; font-size:.8rem; color:var(--mut); }
.updated { color:var(--mut); font-size:.8rem; }
.hidden { display:none; }
</style>
</head>
<body>
<header>
  <h1>Asta <span class="mut">2026/27</span></h1>
  <div class="stats" id="stats"><span class="mut">caricamento…</span></div>
  <span class="updated hidden" id="updated"></span>
</header>
<main>
  <div id="banner" role="alert"></div>

  <section class="card">
    <h2>Cerca giocatore</h2>
    <input id="search" type="search" placeholder="nome, squadra o id ufficiale…" autocomplete="off">
    <ul id="results"></ul>
  </section>

  <section class="card hidden" id="bidcard">
    <h2>Chiamato</h2>
    <div id="bidinfo"></div>
    <div class="tags" id="bidtags"></div>
    <div id="rivals" class="mut"></div>
  </section>

  <section class="card">
    <h2>Registra aggiudicazione</h2>
    <div class="row">
      <input id="salep" placeholder="giocatore (dal riquadro sopra)" style="flex:2;min-width:200px">
      <input id="saler" type="number" min="1" step="1" placeholder="prezzo" style="width:90px">
      <input id="saleb" list="buyers" placeholder="acquirente (io)" style="flex:1;min-width:120px">
      <datalist id="buyers"></datalist>
      <button id="salebtn" class="sec">Conferma vendita</button>
    </div>
  </section>

  <section class="card">
    <div class="row" style="justify-content:space-between">
      <h2 style="margin:0">Rosa del piano</h2>
      <div class="row">
        <button id="undobtn" class="danger">Annulla ultima riga</button>
        <button id="refresh" class="sec">Aggiorna</button>
      </div>
    </div>
    <div id="plansum" class="mut" style="margin:6px 0"></div>
    <table id="roster"><thead><tr><th>R</th><th>Prof.</th><th>Giocatore</th><th>Squadra</th><th>Stato</th><th>Cred.</th><th>FV att.</th><th>Gioca</th></tr></thead><tbody></tbody></table>
  </section>

  <section class="card">
    <h2>Partecipanti</h2>
    <table id="managers"><thead><tr><th>Manager</th><th>Spesi</th><th>Rimasti</th><th>Slot</th><th>P</th><th>D</th><th>C</th><th>A</th><th>Offerta max</th></tr></thead><tbody></tbody></table>
  </section>
</main>
<script>
const TOKEN = "__TOKEN__";
const ME = __ME__;
let selected = null;
let buyers = new Set([ME]);
let bidVersion = 0;
let busy = false;
function invalidateBid() {
  ++bidVersion; selected = null;
  document.getElementById("bidcard").classList.add("hidden");
  for (const id of ["bidinfo", "bidtags", "rivals"]) document.getElementById(id).textContent = "";
}
function setBusy(value) {
  busy = value;
  for (const id of ["salebtn", "undobtn", "refresh"]) document.getElementById(id).disabled = value;
}
function es(s){return String(s).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");}

function err(msg) {
  const b = document.getElementById("banner");
  b.textContent = msg; b.style.display = "block";
}
function okMsg() { document.getElementById("banner").style.display = "none"; }
function stamp() {
  const u = document.getElementById("updated");
  u.textContent = "aggiornato " + new Date().toLocaleTimeString("it-IT");
  u.classList.remove("hidden");
}
async function get(path) {
  const r = await fetch(path);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  if (!j.ok) throw new Error(j.error || "risposta non valida");
  return j.data;
}
async function post(path, body) {
  const r = await fetch(path, {method:"POST",
    headers: {"Content-Type":"application/json", "X-Auction-Token":TOKEN},
    body: JSON.stringify(body || {})});
  const j = await r.json();
  if (!r.ok || !j.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j.data;
}

function renderStats(p) {
  document.getElementById("stats").innerHTML =
    `<span class="stat">crediti <b>${p.my_budget_left}</b></span>` +
    `<span class="stat">tetto offerta <b>${p.my_max_bid}</b></span>` +
    `<span class="stat">mercato <b>${p.market_factor.toFixed(2)}</b></span>` +
    `<span class="stat">1 cred. <b>${p.credit_value.toFixed(4)}</b> pt</span>` +
    `<span class="stat">vendite <b>${p.sales}</b></span>`;
  document.getElementById("plansum").textContent =
    `obiettivo ${p.objective.toFixed(3)} · risolto in ${p.seconds.toFixed(1)} s`;
}

function renderRoster(roster) {
  const tb = document.querySelector("#roster tbody");
  tb.innerHTML = roster.map(x => `<tr>
    <td>${es(x.role)}</td><td>${es(x.depth)}</td><td><b>${es(x.player)}</b></td><td>${es(x.team)}</td>
    <td class="${x.stato === "preso" ? "preso" : "mut"}">${es(x.stato)}</td>
    <td>${es(x.crediti)}</td><td>${es(x.expected_fantavoto.toFixed(2))}</td><td>${es(x.p_plays.toFixed(2))}</td>
  </tr>`).join("");
}

function renderManagers(rows) {
  buyers = new Set(rows.map(r => r.acquirente).filter(name => !/^altri \(\d+, nessun acquisto\)$/.test(name)));
  const tb = document.querySelector("#managers tbody");
  tb.innerHTML = rows.map(r => `<tr>
    <td>${es(r.acquirente)}</td><td>${es(r.spesi)}</td><td>${es(r.rimasti)}</td><td>${es(r.slot_aperti)}</td>
    <td>${es(r.aperti_P)}</td><td>${es(r.aperti_D)}</td><td>${es(r.aperti_C)}</td><td>${es(r.aperti_A)}</td>
    <td>${es(r.offerta_max)}</td></tr>`).join("");
  const dl = document.getElementById("buyers");
  dl.innerHTML = [...buyers].map(b => `<option value="${es(b)}"></option>`).join("");
}

async function loadPlan() {
  invalidateBid();
  const p = await get("/api/plan");
  renderStats(p); renderRoster(p.roster); renderManagers(p.managers);
  stamp();
}
async function loadBid(player) {
  invalidateBid();
  const version = bidVersion;
  const b = await get("/api/bid?player=" + encodeURIComponent(player));
  if (version !== bidVersion) return;
  selected = {player: b.player, team: b.team, role: b.role};
  document.getElementById("salep").value = b.player;
  document.getElementById("bidcard").classList.remove("hidden");
  document.getElementById("bidinfo").innerHTML =
    `<span class="big">${es(b.player)}</span> <span class="mut">${es(b.team)} · ${es(b.role)}</span>` +
    `<div>riferimento <b>${b.riferimento}</b> · offerta massima <b>${b.offerta_max}</b>` +
    (b.motivo ? ` <span class="mut">(${es(b.motivo)})</span>` : "") + `</div>` +
    (b.se_lo_perdi ? `<div class="mut">se lo perdi entrano: ${es(b.se_lo_perdi)}</div>` : "");
  document.getElementById("bidtags").innerHTML =
    `<span class="tag">${b.nel_piano ? "nel piano" : "fuori piano"}</span>` +
    `<span class="tag">vs alternativa ${b.valore_vs_alternativa.toFixed(4)}</span>`;
  document.getElementById("rivals").textContent = b.rivali.length
    ? "rivali con slot " + es(b.role) + ": " + b.rivali.map(r => `${es(r.acquirente)} (fino a ${es(r.offerta_max)})`).join(", ")
    : "nessun rivale con slot libero per questo ruolo";
  stamp();
}

let timer = null;
let searchVersion = 0;
document.getElementById("search").addEventListener("input", ev => {
  clearTimeout(timer);
  const version = ++searchVersion;
  const q = ev.target.value.trim();
  timer = setTimeout(async () => {
    try {
    const r = await get("/api/search?q=" + encodeURIComponent(q));
    if (version !== searchVersion) return;
    const ul = document.getElementById("results");
    ul.innerHTML = r.results.map(x =>
      `<li data-p="${es(x.player)}">
        <span><b>${es(x.player)}</b> <span class="mut">${es(x.team)} · ${es(x.role)}</span></span>
        <span class="mut">id ${es(x.id ?? "—")}</span></li>`).join("");
    if (!r.results.length) ul.innerHTML = `<li class="mut">nessun risultato</li>`;
    } catch (e) { if (version === searchVersion) err("ricerca: " + e.message); }
  }, 200);
});
document.getElementById("results").addEventListener("click", async ev => {
  const li = ev.target.closest("li[data-p]");
  if (!li) return;
  try { okMsg(); await loadBid(li.dataset.p); } catch (e) { err("offerta: " + e.message); }
});

document.getElementById("salebtn").addEventListener("click", async () => {
  if (busy) return;
  const player = document.getElementById("salep").value.trim();
  const price = Number(document.getElementById("saler").value);
  const buyer = document.getElementById("saleb").value.trim() || ME;
  if (!player || !Number.isSafeInteger(price) || price < 1) { err("inserisci giocatore e prezzo intero"); return; }
  if (!confirm(`Registrare ${player} → ${buyer} per ${price} crediti?`)) return;
  setBusy(true); invalidateBid();
  try {
    okMsg();
    const d = await post("/api/sale", {player, price, buyer});
    invalidateBid();
    renderStats(d.plan); renderRoster(d.plan.roster); renderManagers(d.plan.managers);
    document.getElementById("saler").value = "";
    document.getElementById("salep").value = "";
    stamp();
  } catch (e) { err("vendita: " + e.message); await loadPlan().catch(() => {}); }
  finally { setBusy(false); }
});

document.getElementById("undobtn").addEventListener("click", async () => {
  if (busy) return;
  if (!confirm("Annullare l'ultima aggiudicazione registrata?")) return;
  setBusy(true); invalidateBid();
  try {
    okMsg();
    const d = await post("/api/undo", {});
    invalidateBid();
    renderStats(d.plan); renderRoster(d.plan.roster); renderManagers(d.plan.managers);
    stamp();
  } catch (e) { err("annulla: " + e.message); await loadPlan().catch(() => {}); }
  finally { setBusy(false); }
});

document.getElementById("refresh").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true);
  try { okMsg(); await loadPlan(); } catch (e) { err(e.message); }
  finally { setBusy(false); }
});

document.getElementById("salep").addEventListener("input", invalidateBid);
document.getElementById("saleb").placeholder = `acquirente (${ME})`;
loadPlan().catch(e => err("avvio: " + e.message));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
