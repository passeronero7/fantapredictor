import json
import http.client
import socket
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib import error, request

import numpy as np
import pandas as pd

from scripts.live_auction_web import AuctionWebServer, main
from src.models.auction_optimizer import AuctionOptimizationConfig, InfeasibleRosterError, ROSTER_SLOTS
from src.models.live_auction import LivePlanner, read_state
from src.utils.state_lock import StateLock


def make_pool(seed: int = 3, per_role: int = 18) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    ref = 1000
    for role in ROSTER_SLOTS:
        for index in range(per_role):
            quality = rng.uniform(0, 1)
            rows.append({
                "player": f"{role} Player{index}",
                "player_normalized": f"{role.lower()} player{index}",
                "source_ref": ref,
                "team": f"Club{index % 6}",
                "role": role,
                "auction_cost": float(max(1, round(1 + 60 * quality ** 2 + rng.normal(0, 3)))),
                "expected_fantavoto": 5.8 + 1.4 * quality,
                "p_plays": float(np.clip(0.5 + 0.5 * quality + rng.normal(0, 0.1), 0, 1)),
                "p_horizon_median_good": float(np.clip(0.4 + 0.5 * quality, 0, 1)),
                "expected_vote": 5.9 + 0.6 * quality,
            })
            ref += 1
    return pd.DataFrame(rows)


def make_planner(seed: int = 3, per_role: int = 18) -> LivePlanner:
    pool = make_pool(seed, per_role)
    return LivePlanner(pool, AuctionOptimizationConfig(budget=500, reserve=10),
                       me="io", managers=4)


class WebServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "stato.csv"
        self.planner = make_planner()
        self.token = "test-token"
        self.server = AuctionWebServer(self.planner, pd.DataFrame(
            columns=["giocatore", "acquirente", "prezzo"]),
            self.state_path, "127.0.0.1", 0, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def call(self, method, path, body=None, token=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        all_headers = {"Content-Type": "application/json"}
        if token is not None:
            all_headers["X-Auction-Token"] = token
        if headers:
            all_headers.update(headers)
        req = request.Request(self.base + path, data=data, headers=all_headers, method=method)
        try:
            with request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode())
        except error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def csv_text(self):
        return self.state_path.read_text() if self.state_path.exists() else ""


class BasicApiTests(WebServerCase):
    def test_idle_browser_connection_does_not_block_other_clients(self):
        with socket.create_connection(self.server.server_address, timeout=2):
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
            try:
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(response.will_close)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                response.read()
                self.assertEqual(self.call("GET", "/api/health")[0], 200)
            finally:
                connection.close()

    def test_planner_calls_remain_serialized(self):
        original = self.planner.plan
        active = 0
        peak = 0
        guard = threading.Lock()

        def tracked(state):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.1)
                return original(state)
            finally:
                with guard:
                    active -= 1

        with patch.object(self.planner, "plan", side_effect=tracked):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(self.call, "GET", "/api/plan") for _ in range(2)]
                self.assertEqual([future.result()[0] for future in futures], [200, 200])
        self.assertEqual(peak, 1)

    def test_search_supports_official_id_and_team(self):
        _, payload = self.call("GET", "/api/search?q=1000")
        self.assertEqual([row["player"] for row in payload["data"]["results"]], ["P Player0"])
        _, payload = self.call("GET", "/api/search?q=Club2")
        self.assertTrue(payload["data"]["results"])
        self.assertTrue(all(row["team"] == "Club2" for row in payload["data"]["results"]))

    def test_health_and_page_work_without_token(self):
        status, payload = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["sales"], 0)
        status, page = self._get_raw("/")
        self.assertIn("text/html", page)

    def _get_raw(self, path):
        with request.urlopen(self.base + path, timeout=60) as resp:
            return resp.status, resp.headers["Content-Type"]

    def test_page_embeds_the_startup_token(self):
        body = request.urlopen(self.base + "/", timeout=60).read().decode()
        self.assertIn(self.token, body)
        self.assertIn("Asta", body)

    def test_plan_and_managers_match_the_console_model(self):
        status, payload = self.call("GET", "/api/plan")
        self.assertEqual(status, 200)
        plan = payload["data"]
        self.assertEqual(len(plan["roster"]), sum(ROSTER_SLOTS.values()))
        self.assertEqual(set(plan["roster"][0]), {"role", "depth", "player", "team",
                                                  "stato", "crediti", "expected_fantavoto",
                                                  "p_plays"})
        self.assertEqual(plan["my_budget_left"], 500)
        self.assertEqual(plan["sales"], 0)
        status, payload = self.call("GET", "/api/managers")
        self.assertEqual(status, 200)
        self.assertIn("io", [m["acquirente"] for m in payload["data"]["managers"]])

    def test_search_no_query_is_empty_and_prefix_matches(self):
        _, payload = self.call("GET", "/api/search")
        self.assertEqual(payload["data"]["results"], [])
        _, payload = self.call("GET", "/api/search?q=a+player1")
        names = [r["player"] for r in payload["data"]["results"]]
        self.assertIn("A Player1", names)
        for row in payload["data"]["results"]:
            self.assertIn("role", row)

    def test_bid_payload_and_conflicts(self):
        status, payload = self.call("GET", "/api/bid?player=A+Player1")
        self.assertEqual(status, 200)
        bid = payload["data"]
        for key in ("player", "team", "role", "riferimento", "nel_piano",
                    "offerta_max", "motivo", "se_lo_perdi", "rivali", "secondi"):
            self.assertIn(key, bid)
        status, _ = self.call("GET", "/api/bid")  # missing parameter
        self.assertEqual(status, 400)
        status, _ = self.call("GET", "/api/bid?player=Sconosciuto")
        self.assertEqual(status, 400)


class SaleApiTests(WebServerCase):
    def test_failed_sale_plan_preserves_csv_and_memory(self):
        for error, expected in [(InfeasibleRosterError("No legal roster"), 409),
                                (RuntimeError("private solver details"), 500)]:
            with self.subTest(error=type(error).__name__):
                before = self.csv_text()
                with patch.object(self.planner, "plan", side_effect=error):
                    status, payload = self.call("POST", "/api/sale",
                        {"player": "P Player0", "buyer": "io", "price": 5}, token=self.token)
                self.assertEqual(status, expected)
                self.assertEqual(self.csv_text(), before)
                self.assertTrue(self.server.state.empty)
                if expected == 500:
                    self.assertEqual(payload["error"], "internal error")

    def test_failed_undo_plan_preserves_existing_sale(self):
        self.assertEqual(self.call("POST", "/api/sale",
            {"player": "P Player0", "buyer": "io", "price": 5}, token=self.token)[0], 200)
        before = self.csv_text()
        with patch.object(self.planner, "plan", side_effect=InfeasibleRosterError("No legal roster")):
            self.assertEqual(self.call("POST", "/api/undo", {}, token=self.token)[0], 409)
        self.assertEqual(self.csv_text(), before)
        self.assertEqual(len(self.server.state), 1)

    def test_disk_error_does_not_change_in_memory_state(self):
        before = self.csv_text()
        with patch("scripts.live_auction_web.write_state", side_effect=OSError("disk full")):
            status, _ = self.call("POST", "/api/sale",
                {"player": "P Player0", "buyer": "io", "price": 5}, token=self.token)
        self.assertEqual(status, 500)
        self.assertEqual(self.csv_text(), before)
        self.assertTrue(self.server.state.empty)

    def test_mine_sale_updates_csv_and_plan(self):
        ref = int(self.planner.full.iloc[0]["source_ref"])
        status, payload = self.call("POST", "/api/sale",
                                    {"player": str(ref), "price": 22, "buyer": "io"},
                                    token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["sale"]["acquirente"], "io")
        self.assertEqual(payload["data"]["plan"]["sales"], 1)
        self.assertIn("P Player0", self.csv_text())
        row = [line for line in self.csv_text().splitlines() if "P Player0" in line][0]
        self.assertIn("io", row)

    def test_rejected_sales_leave_the_csv_unchanged(self):
        before = self.csv_text()
        cases = [
            ({"player": "A Player1", "price": 0, "buyer": "io"}, 400),
            ({"player": "A Player1", "price": "12", "buyer": "io"}, 400),
            ({"player": "A Player1", "price": 12}, 400),
            ({"player": "Sconosciuto", "price": 12, "buyer": "io"}, 400),
            ({"player": "A Player1", "price": 500, "buyer": "Marco"}, 409),
        ]
        for body, expected in cases:
            status, _ = self.call("POST", "/api/sale", body, token=self.token)
            self.assertEqual(status, expected, body)
            self.assertEqual(self.csv_text(), before)

    def test_double_sale_and_slot_overflow_are_conflicts(self):
        for goalie in ("P Player1", "P Player2", "P Player3"):
            status, _ = self.call("POST", "/api/sale",
                                  {"player": goalie, "price": 3, "buyer": "Marco"},
                                  token=self.token)
            self.assertEqual(status, 200)
        status, _ = self.call("POST", "/api/sale",
                              {"player": "P Player4", "price": 3, "buyer": "Marco"},
                              token=self.token)
        self.assertEqual(status, 409)  # fourth goalkeeper: no slot left
        status, _ = self.call("POST", "/api/sale",
                              {"player": "P Player1", "price": 3, "buyer": "io"},
                              token=self.token)
        self.assertEqual(status, 409)  # already sold

    def test_undo_pops_the_last_row_and_is_rejected_when_empty(self):
        self.call("POST", "/api/sale", {"player": "A Player1", "price": 5, "buyer": "io"},
                  token=self.token)
        status, payload = self.call("POST", "/api/undo", {}, token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["undone"]["giocatore"], "A Player1")
        self.assertEqual(payload["data"]["plan"]["sales"], 0)
        self.assertNotIn("A Player1", self.csv_text())
        status, _ = self.call("POST", "/api/undo", {}, token=self.token)
        self.assertEqual(status, 409)

    def test_restart_reads_the_persisted_log(self):
        self.call("POST", "/api/sale", {"player": "C Player2", "price": 8, "buyer": "io"},
                  token=self.token)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        server = AuctionWebServer(make_planner(), pd.DataFrame(
            columns=["giocatore", "acquirente", "prezzo"]),
            self.state_path, "127.0.0.1", 0, self.token)
        server.lock.acquire()
        try:
            state = read_state(server.state_path)
            self.assertEqual(len(state), 1)
            self.assertIn("C Player2", state["giocatore"].iloc[0])
        finally:
            server.lock.release()
            server.server_close()


class GuardTests(WebServerCase):
    def test_host_checked_on_page_reads_and_mutations(self):
        for path in ("/", "/api/health"):
            status, payload = self.call("GET", path, headers={"Host": "foreign.example"})
            self.assertEqual(status, 403)
            self.assertNotIn(self.token, json.dumps(payload))
        status, _ = self.call("POST", "/api/sale",
            {"player": "P Player0", "buyer": "io", "price": 5}, token=self.token,
            headers={"Host": "foreign.example"})
        self.assertEqual(status, 403)
        self.assertTrue(self.server.state.empty)

    def test_body_framing_and_content_type_errors_do_not_hang(self):
        for headers, expected in [({"Content-Length": "-1"}, 400),
                                   ({"Content-Length": "invalid"}, 400),
                                   ({"Transfer-Encoding": "chunked"}, 400),
                                   ({"Content-Type": "text/application/json"}, 415)]:
            with self.subTest(headers=headers):
                connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
                try:
                    connection.request("POST", "/api/undo", b"{}", {
                        "Content-Type": "application/json", "X-Auction-Token": self.token, **headers})
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertTrue(response.will_close)
                    response.read()
                finally:
                    connection.close()
        self.assertTrue(self.server.state.empty)

    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "solo 127.0.0.1"):
            AuctionWebServer(self.planner, self.server.state, self.state_path, "0.0.0.0", 0, self.token)

    def test_mutations_need_token_origin_and_content_type(self):
        body = {"player": "A Player1", "price": 5, "buyer": "io"}
        status, _ = self.call("POST", "/api/sale", body, token=None)
        self.assertEqual(status, 403)
        status, _ = self.call("POST", "/api/sale", body, token="wrong")
        self.assertEqual(status, 403)
        status, _ = self.call("POST", "/api/sale", body, token=self.token,
                              headers={"Origin": "http://evil.example:1234"})
        self.assertEqual(status, 403)
        status, _ = self.call("POST", "/api/sale", body, token=self.token,
                              headers={"Origin": f"http://127.0.0.1:{self.server.server_address[1]}"})
        self.assertEqual(status, 200)
        self.assertEqual(self.csv_text().count("A Player1"), 1)

    def test_oversized_body_is_rejected(self):
        big = {"player": "A Player1", "price": 5, "buyer": "x" * (64 * 1024)}
        status, _ = self.call("POST", "/api/sale", big, token=self.token)
        self.assertEqual(status, 413)
        self.assertNotIn("A Player1", self.csv_text())

    def test_unknown_endpoints_and_methods(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        self.assertEqual(self.call("POST", "/api/nope", {}, token=self.token)[0], 404)
        self.assertEqual(self.call("POST", "/api/plan", {}, token=self.token)[0], 404)

    def test_unexpected_exceptions_return_500_without_leaking_details(self):
        def broken(state, query):
            raise Exception("secret internal detail")
        self.planner.bid = broken
        status, payload = self.call("GET", "/api/bid?player=A+Player1")
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "internal error")
        self.assertNotIn("secret", json.dumps(payload))


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "stato.csv"
        self.forecast = self.tmp / "forecast.csv"
        self.dossier = self.tmp / "dossier.csv"
        pool = make_pool(5, per_role=12)
        pool.rename(columns={"source_ref": "id"}, inplace=True)
        forecast_cols = ["player_normalized", "player", "team", "role",
                         "expected_fantavoto", "p_plays", "p_horizon_median_good",
                         "expected_vote"]
        pool[forecast_cols].to_csv(self.forecast, index=False)
        dossier = pd.DataFrame({
            "player_normalized": pool["player_normalized"],
            "source_ref": pool["id"],
            "riferimento_senza_modificatore": pool["auction_cost"],
        })
        dossier.to_csv(self.dossier, index=False)

    def _argv(self, port=0):
        return ["--forecast", str(self.forecast), "--dossier-players", str(self.dossier),
                "--state", str(self.state_path), "--me", "io", "--managers", "8",
                "--budget", "500", "--reserve", "10", "--host", "127.0.0.1",
                "--port", str(port)]

    def test_lock_fails_when_another_process_holds_it(self):
        holder = StateLock(self.state_path)
        holder.acquire()
        try:
            contestant = StateLock(self.state_path)
            with self.assertRaisesRegex(RuntimeError, "holds the lock"):
                contestant.acquire()
        finally:
            holder.release()
        again = StateLock(self.state_path)
        again.acquire()  # released: acquisition succeeds again
        again.release()

    def test_two_web_servers_on_the_same_state_exit_cleanly(self):
        argv = self._argv()
        first = StateLock(self.state_path)
        first.acquire()
        try:
            with self.assertRaises(SystemExit):
                main(argv)
            with open(self.state_path, "w") as handle:
                handle.write("")  # untouched by the failing start
            self.assertEqual(self.state_path.stat().st_size, 0)
        finally:
            first.release()

    def test_valid_csv_is_required_before_serving(self):
        self.state_path.write_text("giocatore,acquirente\nA,io\n")
        with self.assertRaises(ValueError):
            main(self._argv())


if __name__ == "__main__":
    unittest.main()
