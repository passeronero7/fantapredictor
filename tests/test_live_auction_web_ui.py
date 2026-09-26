"""Execute the shipped JavaScript against a minimal DOM; no browser downloads."""

import json
import shutil
import subprocess
import unittest

from scripts.live_auction_web import PAGE_HTML


HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set(['hidden']);
    elements.set(id, {innerHTML:'', textContent:'', value:'', style:{}, disabled:false,
      classList:{add(x){classes.add(x)},remove(x){classes.delete(x)},contains(x){return classes.has(x)}},
      handlers:{}, addEventListener(name, callback){this.handlers[name]=callback}});
  }
  return elements.get(id);
}
const calls = [];
const plan = {my_budget_left:480,my_max_bid:457,market_factor:1,credit_value:.01,
  sales:1,objective:95,seconds:.1,roster:[],managers:[]};
const bid = {player:'De Gea',team:'Fiorentina',role:'P',riferimento:13,offerta_max:14,
  motivo:'',se_lo_perdi:'',nel_piano:true,valore_vs_alternativa:0,rivali:[]};
const response = data => ({ok:true,json:async()=>({ok:true,data})});
let intercept = null;
const context = {document:{getElementById:element,querySelector:element},
  console,setTimeout,clearTimeout,confirm:()=>true,
  fetch:async(path, options)=>{
    calls.push({path, options});
    if (intercept) {const result=intercept(path,options); if (result) return result;}
    return response(path.startsWith('/api/bid')?bid:path==='/api/sale'||path==='/api/undo'?{plan}:plan);
  }};
vm.createContext(context);
vm.runInContext(SCRIPT, context);
const run = code => vm.runInContext(code, context);
const click = id => element(id).handlers.click();
const hidden = () => element('bidcard').classList.contains('hidden');
"""


@unittest.skipUnless(shutil.which("node"), "Node is needed to execute the UI regression checks")
class WebUiTests(unittest.TestCase):
    def run_js(self, body):
        script = PAGE_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        script = script.replace("__ME__", json.dumps("captain"))
        program = "const SCRIPT = " + json.dumps(script) + ";\n" + HARNESS
        program += "\n(async()=>{ await new Promise(setImmediate);\n" + body
        program += "\n})().catch(e=>{console.error(e);process.exitCode=1});"
        result = subprocess.run([shutil.which("node"), "-e", program],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sale_undo_refresh_invalidate_bid_and_use_configured_manager(self):
        self.run_js("""
          await run('loadBid("De Gea")'); assert.equal(hidden(), false);
          element('saler').value='20'; await click('salebtn');
          assert.equal(hidden(), true);
          const sale=calls.find(x=>x.path==='/api/sale');
          assert.equal(JSON.parse(sale.options.body).buyer, 'captain');
          await run('loadBid("De Gea")'); await click('undobtn'); assert.equal(hidden(),true);
          await run('loadBid("De Gea")'); await click('refresh'); assert.equal(hidden(),true);
        """)

    def test_late_bid_response_cannot_restore_old_quote(self):
        self.run_js("""
          let resolve;
          intercept=path=>path.startsWith('/api/bid')?new Promise(r=>{resolve=r}):null;
          const pending=run('loadBid("De Gea")');
          await click('refresh');
          resolve(response(bid)); await pending;
          assert.equal(hidden(),true);
        """)

    def test_fractional_price_is_not_silently_truncated(self):
        self.run_js("""
          element('salep').value='De Gea'; element('saler').value='1.9';
          await click('salebtn');
          assert.equal(calls.some(x=>x.path==='/api/sale'),false);
          assert.equal(element('banner').style.display,'block');
        """)

    def test_duplicate_click_is_ignored_while_mutation_pending(self):
        self.run_js("""
          let resolve;
          intercept=path=>path==='/api/undo'?new Promise(r=>{resolve=r}):null;
          const pending=click('undobtn'); await click('undobtn');
          assert.equal(calls.filter(x=>x.path==='/api/undo').length,1);
          assert.equal(element('undobtn').disabled,true);
          resolve(response({plan})); await pending;
          assert.equal(element('undobtn').disabled,false);
        """)

    def test_buyer_names_are_escaped_and_aggregate_is_not_an_option(self):
        self.run_js("""
          context.renderManagers([{acquirente: 'A"<test>'}, {acquirente: "altri (7, nessun acquisto)"}]);
          assert.equal(element('buyers').innerHTML.includes('&quot;&lt;test&gt;'),true);
          assert.equal(element('buyers').innerHTML.includes('altri ('),false);
        """)
