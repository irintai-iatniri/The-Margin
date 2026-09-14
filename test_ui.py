#!/usr/bin/env python3
"""Full-functionality test for The Margin.

Drives the real index.html in headless Chromium with /api/sample intercepted,
so every path is deterministic and no API call is made. Costs nothing per run,
and can force the failure modes live calls will not reliably produce: refusal,
malformed outline, truncated JSON, a terminal ending on cue.

    python3 test_ui.py            # all scenarios
    python3 test_ui.py --headed   # watch it

Exit 0 means every path held.
"""
import json, os, pathlib, subprocess, sys, tempfile, threading, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).parent
PORT = 7899
HEADED = "--headed" in sys.argv

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s  %s" % ("PASS" if ok else "FAIL", name))
    if not ok and detail:
        print("        %s" % str(detail)[:300])


# ----------------------------------------------------------------- outline
def outline():
    """Nine beats, spine n1..n6, endings n8/n9 at depth 5. n7 is optional."""
    mid = lambda i, w, e: {"id": "n%d" % i, "want": w, "exit": e, "sow": [], "due": [], "terminal": None}
    nodes = [
        {"id": "n1", "want": "establish the debt and who holds it",
         "exit": "the collector's name is spoken aloud",
         "sow": [{"id": "s1", "claim": "The collector is the bargeman's half-brother.", "subject": ["collector"]},
                 {"id": "s2", "claim": "The ledger was forged by the harbourmaster.", "subject": ["ledger"]}],
         "due": [], "terminal": None},
        {"id": "n2", "want": "a trust breaks", "exit": "the ledger changes hands",
         "sow": [{"id": "s3", "claim": "The girl has seen the ledger before.", "subject": ["girl"]}],
         "due": [], "terminal": None},
        mid(3, "the cost of the route is shown", "someone is left behind"),
        mid(4, "an old obligation surfaces", "a name is written down"),
        mid(5, "the collector closes in", "the lamp goes out"),
        mid(6, "a last bargain", "the tarp is pulled back"),
        mid(7, "an unasked question, off the main line", "a door is left unopened"),
        {"id": "n8", "want": "the debt is settled", "exit": "the book closes on open water",
         "sow": [], "due": ["s2", "s3"], "terminal": "kept"},
        {"id": "n9", "want": "it is called in", "exit": "the book closes under the ice",
         "sow": [], "due": [], "terminal": "lost"},
    ]
    nodes[2]["due"] = ["s1"]          # s1 pays off on n3
    edges = [
        {"from": "n1", "to": "n2", "gate": "the name is spoken"},
        {"from": "n1", "to": "n7", "gate": "the name is withheld"},
        {"from": "n2", "to": "n3", "gate": "the ledger is surrendered"},
        {"from": "n2", "to": "n7", "gate": "the ledger is kept"},
        {"from": "n7", "to": "n3", "gate": "the question is finally asked"},
        {"from": "n3", "to": "n4", "gate": "the obligation is honoured"},
        {"from": "n3", "to": "n5", "gate": "the obligation is denied"},
        {"from": "n4", "to": "n5", "gate": "the collector is answered"},
        {"from": "n4", "to": "n6", "gate": "the collector is fled"},
        {"from": "n5", "to": "n6", "gate": "the lamp is relit"},
        {"from": "n6", "to": "n8", "gate": "the bargain holds"},
        {"from": "n6", "to": "n9", "gate": "the bargain breaks"},
    ]
    return {"start": "n1", "nodes": nodes, "edges": edges}


def turn(prose, choices, pub, node, priv):
    return (prose + "\n\n@CHOICES\n" + "\n".join("- " + c for c in choices) +
            "\n\n@PUBLIC\n" + json.dumps(pub) +
            "\n\n@NODE\n" + json.dumps(node) +
            "\n\n@PRIVATE\n" + json.dumps(priv))


PROSE = ("The barge pivots under you, wedged where the canal has gone solid from the bed upward. "
         "Ice grips the hull like a hand closing. Under the tarp the girl has not moved, and you "
         "do not look, because looking costs seconds you no longer have. On the towpath a lantern "
         "swings once and stops. Someone is standing very still in the cold, waiting for you to "
         "understand that they can wait longer than you can.")


def sse(text):
    out = []
    for i in range(0, len(text), 180):
        out.append("event: content_block_delta\ndata: " + json.dumps({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text[i:i + 180]}}) + "\n\n")
    out.append("event: message_stop\ndata: " + json.dumps({"type": "message_stop"}) + "\n\n")
    return "".join(out)


# ----------------------------------------------------------------- server
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def translate_path(self, path):
        return str(HERE / "index.html")


def serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ----------------------------------------------------------------- harness
class Run:
    """One page load with a scripted /api/sample."""

    def __init__(self, browser, script):
        self.script = script            # list of (matcher, responder)
        self.seen = []                  # every request body
        self.turns = 0
        self.page = browser.new_page()
        self.page.route("**/api/sample", self._handle)
        self.page.goto("http://127.0.0.1:%d/" % PORT)
        self.page.wait_for_selector("#begin")

    def _handle(self, route, request):
        body = json.loads(request.post_data or "{}")
        self.seen.append(body)
        blob = "\n".join(m.get("content", "") for m in body.get("messages", []))
        is_outline = "beat sheet" in blob
        if not is_outline:
            self.turns += 1
        res = self.script(self, blob, is_outline, self.turns)
        if isinstance(res, tuple):          # (status, body)
            route.fulfill(status=res[0], content_type="application/json", body=res[1])
        else:
            route.fulfill(status=200, content_type="text/event-stream", body=sse(res))

    def text(self, sel):
        try:
            return self.page.inner_text(sel, timeout=2000)
        except Exception:
            return ""

    def visible(self, sel):
        try:
            return self.page.is_visible(sel)
        except Exception:
            return False

    def begin(self, who="a night bargeman", drive="protect", stake="the girl under the tarp"):
        self.page.fill("#who", who)
        self.page.select_option("#drive", drive)
        self.page.fill("#stake", stake)
        self.page.click("#begin")

    def close(self):
        self.page.close()


def normal_script(run, blob, is_outline, turns):
    if is_outline:
        return json.dumps(outline())
    if turns == 1:
        return turn(PROSE, ["Answer the lantern.", "Cut the tarp free and run.", "Say the collector's name."],
                    {"beat": "the barge wedges in the ice", "place": "the frozen canal",
                     "resolve": 7, "gain": ["a boat hook"], "lose": [],
                     "edges": [["collector", "waits on", "the towpath"]], "invalidate": []},
                    {"satisfied": False, "next": None,
                     "reachable": ["n3", "n4", "n5", "n6"]}, {"spend": []})
    # one advance per turn along the spine, ending at n8 on the sixth
    spine = {2: "n2", 3: "n3", 4: "n4", 5: "n5", 6: "n6", 7: "n8"}
    if turns in spine:
        nxt = spine[turns]
        return turn(PROSE, ["Press on.", "Give ground.", "Look again at the ice."],
                    {"beat": "step toward %s" % nxt, "place": "the towpath",
                     "resolve": max(3, 8 - turns), "gain": [],
                     "lose": (["a boat hook"] if turns == 3 else []),
                     "edges": [], "invalidate": []},
                    {"satisfied": True, "next": nxt,
                     "reachable": ["n3", "n4", "n5", "n6"]},
                    {"spend": (["s1"] if turns == 4 else [])})
    return turn(PROSE, ["Hold the line.", "Give ground.", "Look again at the ice."],
                {"beat": "the cold settles in", "place": "open water", "resolve": 5,
                 "gain": [], "lose": [], "edges": [], "invalidate": []},
                {"satisfied": False, "next": None,
                 "reachable": ["n3", "n4", "n5", "n6"]}, {"spend": []})


# ----------------------------------------------------------------- scenarios
def scenario_premise(browser):
    print("\n[1] the opening screen")
    r = Run(browser, normal_script)
    opts = r.page.eval_on_selector_all("#drive option", "els => els.map(e => e.value)")
    check("seven drives offered", len(opts) == 7, opts)
    seeds = r.page.query_selector_all("#seedList button")
    check("three seeds offered", len(seeds) == 3)
    seeds[2].click()
    check("seed fills who", "cartographer" in r.page.input_value("#who"))
    check("seed sets the drive", r.page.input_value("#drive") == "seek",
          r.page.input_value("#drive"))
    check("seed fills the stake", len(r.page.input_value("#stake")) > 3)
    r.close()


def scenario_lore(browser):
    print("\n[2] the lore book")
    r = Run(browser, normal_script)
    doc = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
    doc.write("# The Verge\n\nA shelf of black rock above the Callow Sea.\n\n"
              "## Tarn Holloway\n\nTarn keeps the tide-ledger.\n\n"
              "## The Quiet Year\n\nEleven months in which no bell rang.\n")
    doc.close()
    r.page.set_input_files("#loreFile", doc.name)
    r.page.wait_for_function("document.getElementById('loreStat').textContent.includes('passages')",
                             timeout=5000)
    stat = r.text("#loreStat")
    check("lore parsed into passages", "passages" in stat, stat)
    check("remove button appears", r.visible("#loreClear"))

    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    first = r.seen[0]
    blob = "\n".join(m["content"] for m in first["messages"])
    check("lore reaches the outline as canon", "Tarn Holloway" in blob and "CANON" in blob.upper())
    play = "\n".join(m["content"] for m in r.seen[1]["messages"])
    check("lore retrieved into the turn", "[WORLD" in play, play[:160])
    os.unlink(doc.name)
    r.close()


def scenario_play(browser):
    print("\n[3] a normal run")
    r = Run(browser, normal_script)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)

    check("forge screen cleared", not r.visible("#forging"))
    check("three choices rendered", len(r.page.query_selector_all("#choices .choice")) == 3)
    check("prose rendered", len(r.text("#prose")) > 200)
    check("place tracked", "frozen canal" in r.text("#place"), r.text("#place"))
    check("inventory tracked", "boat hook" in r.text("#carrying"), r.text("#carrying"))
    check("chronicle written", "wedges in the ice" in r.text("#beats"), r.text("#beats"))
    check("arc meter shown", r.visible("#arc") and r.visible("#arcHead"))
    check("no drift on an on-rails run", "off the path" not in r.text("#arc"), r.text("#arc"))
    marks = r.text("#marks")
    check("resolve meter drawn", marks.count("\u25a0") == 7, marks)

    r.page.click("#choices .choice >> nth=2")
    r.page.wait_for_function("document.querySelectorAll('#choices .choice').length===3 && "
                             "document.getElementById('beats').children.length===2", timeout=15000)
    check("second turn committed", r.page.eval_on_selector("#beats", "e => e.children.length") == 2)
    check("echo shows the choice taken", "chose" in r.text("#echo").lower(), r.text("#echo"))
    check("turn back becomes available", r.visible("#turnbackBtn"))

    # free text
    r.page.fill("#freeInput", "Cut the rope and let the barge drift.")
    r.page.click("#freeGo")
    r.page.wait_for_function("document.getElementById('beats').children.length===3", timeout=15000)
    sent = "\n".join(m["content"] for m in r.seen[-1]["messages"])
    check("free text reaches the narrator", "Cut the rope" in sent)
    check("inventory loss applied", "boat hook" not in r.text("#carrying"), r.text("#carrying"))
    return r


def scenario_turnback(browser):
    print("\n[4] turning back")
    r = scenario_play(browser)
    before = r.page.eval_on_selector("#beats", "e => e.children.length")
    r.page.click("#turnbackBtn")
    r.page.wait_for_selector("#turnback .tb", timeout=4000)
    pts = r.page.query_selector_all("#turnback .tb")
    check("turning points offered (%d)" % len(pts), len(pts) >= 1)
    check("points are labelled by beat", len(r.text("#turnback")) > 20)
    check("panel shows the count before choosing", "rewind" in r.text("#turnback").lower(),
          r.text("#turnback"))
    check("the last turn is marked free", "undo, free" in r.text("#turnback"),
          r.text("#turnback"))
    check("earlier points cost a rewind", "1 rewind" in r.text("#turnback"),
          r.text("#turnback"))
    pts[-1].click()
    r.page.wait_for_function("!document.getElementById('turnback').classList.contains('hidden')===false",
                             timeout=4000)
    after = r.page.eval_on_selector("#beats", "e => e.children.length")
    check("chronicle rewound (%d -> %d)" % (before, after), after < before)
    check("choices restored", len(r.page.query_selector_all("#choices .choice")) == 3)
    check("notice explains the rewind", "turned back" in r.text("#playNotice").lower(),
          r.text("#playNotice"))
    r.close()


def scenario_ending(browser):
    print("\n[5] the ending, and walking it again")
    r = Run(browser, normal_script)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    for _ in range(6):
        r.page.click("#choices .choice >> nth=0")
        r.page.wait_for_timeout(1200)
    r.page.wait_for_selector("#ending", state="visible", timeout=15000)

    check("ending screen shown", r.visible("#ending"))
    check("ending titled by drive", "survived" in r.text("#endTitle").lower(), r.text("#endTitle"))
    check("beats visited reported", "of 9" in r.text("#endSub"), r.text("#endSub"))
    unl = r.text("#unlearned")
    check("unlearned setups counted", "unlearned" in unl.lower(), unl)
    check("count excludes what was spent", unl.startswith("2 "), unl)
    check("walk it again offered", r.visible("#replay"))
    check("turn back offered at the end", r.visible("#endTurnback"))
    check("save cleared on ending",
          r.page.evaluate("() => localStorage.getItem('margin:run:v2') === null"))

    calls = len(r.seen)
    r.page.click("#replay")
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    check("replay reuses the outline (no new outline call)",
          not any("beat sheet" in "\n".join(m["content"] for m in b["messages"])
                  for b in r.seen[calls:]))
    check("replay resets the chronicle",
          r.page.eval_on_selector("#beats", "e => e.children.length") == 1)
    r.close()


def scenario_failures(browser):
    print("\n[6] failure paths")

    # refusal on the outline
    def refuse(run, blob, is_outline, turns):
        if is_outline:
            return (403, json.dumps({"type": "error", "error": {"type": "permission_error",
                                                                "message": "refused"}}))
        return normal_script(run, blob, is_outline, turns)

    r = Run(browser, refuse)
    r.begin()
    r.page.wait_for_selector("#goOn", timeout=20000)
    check("refusal offers Play anyway", r.visible("#goOn"))
    check("refusal is not a dead end", r.visible("#backBtn"))
    r.page.click("#goOn")
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    check("arcless play starts", len(r.page.query_selector_all("#choices .choice")) == 3)
    check("arc meter hidden without an outline", not r.visible("#arc") and not r.visible("#arcHead"))
    arcless = "\n".join(m["content"] for m in r.seen[-1]["messages"])
    check("arcless prompt drops the beat block", "[BEAT]" not in arcless)
    check("arcless prompt asks for its own ending", '"ending"' in arcless)
    r.close()

    # malformed outline -> one retry -> fallback
    state = {"n": 0}

    def malformed(run, blob, is_outline, turns):
        if is_outline:
            state["n"] += 1
            return "here is your outline: {\"nodes\": [ truncated"
        return normal_script(run, blob, is_outline, turns)

    r = Run(browser, malformed)
    r.begin()
    r.page.wait_for_selector("#goOn", timeout=30000)
    check("malformed outline retried exactly once (%d attempts)" % state["n"], state["n"] == 2)
    check("malformed outline falls back, not hangs", r.visible("#goOn"))
    r.close()

    # unreachable ending -> verification rejects, retries
    bad = outline()
    bad["edges"] = [e for e in bad["edges"] if e["to"] != "n8"]
    vstate = {"n": 0}

    def unverifiable(run, blob, is_outline, turns):
        if is_outline:
            vstate["n"] += 1
            return json.dumps(bad if vstate["n"] == 1 else outline())
        return normal_script(run, blob, is_outline, turns)

    r = Run(browser, unverifiable)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=30000)
    check("unreachable ending rejected then regenerated (%d attempts)" % vstate["n"],
          vstate["n"] == 2)
    check("recovered outline plays", len(r.page.query_selector_all("#choices .choice")) == 3)
    r.close()

    # rate limit mid-play is recoverable
    def limited(run, blob, is_outline, turns):
        if not is_outline and turns == 2:
            return (429, json.dumps({"type": "error", "error": {"type": "rate_limit_error",
                                                                "message": "Error"}}))
        return normal_script(run, blob, is_outline, turns)

    r = Run(browser, limited)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    r.page.click("#choices .choice >> nth=0")
    r.page.wait_for_function("document.getElementById('playNotice').textContent.length > 10",
                             timeout=15000)
    check("rate limit surfaces a notice", "rate" in r.text("#playNotice").lower() or
          "many turns" in r.text("#playNotice").lower(), r.text("#playNotice"))
    check("free text still offered after an error", r.visible("#freeform"))
    check("run survives the error",
          r.page.evaluate("() => localStorage.getItem('margin:run:v2') !== null"))
    r.close()


def scenario_drift(browser):
    print("\n[8] drift — the outline's lightcone")

    def wanders(run, blob, is_outline, turns):
        if is_outline:
            return json.dumps(outline())
        if turns == 1:
            return turn(PROSE, ["Answer the lantern.", "Run for the treeline.", "Say the name."],
                        {"beat": "the barge wedges in the ice", "place": "the frozen canal",
                         "resolve": 7, "gain": [], "lose": [], "edges": [], "invalidate": []},
                        {"satisfied": False, "next": None,
                         "reachable": ["n3", "n4", "n5", "n6"]}, {"spend": []})
        # nothing left reachable: +3 a turn, so the third turn crosses the budget
        return turn(PROSE, ["Keep walking.", "Turn back.", "Sleep where you stand."],
                    {"beat": "further from the canal", "place": "somewhere unmapped",
                     "resolve": 6, "gain": [], "lose": [], "edges": [], "invalidate": []},
                    {"satisfied": False, "next": None, "reachable": []}, {"spend": []})

    r = Run(browser, wanders)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    check("starts on the outline", r.visible("#arc"))
    check("no drift while beats remain reachable", "off the path" not in r.text("#arc"),
          r.text("#arc"))

    r.page.click("#choices .choice >> nth=1")
    r.page.wait_for_function("document.getElementById('beats').children.length===2", timeout=15000)
    check("drift starts when nothing is reachable", "off the path" in r.text("#arc"),
          r.text("#arc"))
    check("the margin says how much is still in reach", "in reach" in r.text("#arc"),
          r.text("#arc"))
    check("still on the outline below the budget", r.visible("#arcHead"))

    r.page.click("#choices .choice >> nth=0")
    r.page.wait_for_function("document.getElementById('beats').children.length===3", timeout=15000)
    r.page.click("#choices .choice >> nth=0")
    r.page.wait_for_function("document.getElementById('beats').children.length===4", timeout=15000)

    check("detaches past the budget", "no longer reaches you" in r.text("#playNotice"),
          r.text("#playNotice"))
    check("arc meter retires on detach", not r.visible("#arc"))
    # the last request is the one that CAUSED the detach; take one more turn so
    # the assertion looks at assembly built after the outline let go
    r.page.click("#choices .choice >> nth=0")
    r.page.wait_for_function("document.getElementById('beats').children.length===5", timeout=15000)
    # only the newly built context turn matters -- earlier history legitimately
    # still contains [BEAT] blocks from when the outline was still governing
    ctx = r.seen[-1]["messages"][-1]["content"]
    rules = r.seen[-1]["messages"][0]["content"]
    check("assembly drops the beat block after detaching", "[BEAT]" not in ctx, ctx[:160])
    check("history is not rewritten", any("[BEAT]" in m["content"] for m in r.seen[-1]["messages"]))
    check("narrator now paces its own ending", '"ending"' in rules and "THE BEAT." not in rules)
    check("play continues, not punished",
          len(r.page.query_selector_all("#choices .choice")) == 3)
    r.close()


def scenario_rewinds(browser):
    print("\n[9] rewinds — three per run, undo is free")
    r = Run(browser, normal_script)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    for n in range(2, 6):
        r.page.click("#choices .choice >> nth=0")
        r.page.wait_for_function(
            "document.getElementById('beats').children.length===%d" % n, timeout=15000)

    def left():
        return r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2')).rewinds")

    check("starts with three", left() == 3, left())

    # undoing the turn just taken is free
    r.page.click("#turnbackBtn")
    r.page.wait_for_selector("#turnback .tb", timeout=4000)
    r.page.click("#turnback .tb >> nth=0")
    r.page.wait_for_timeout(400)
    check("undo of the last turn is free", left() == 3, left())
    check("undo says so", "undone" in r.text("#playNotice").lower(), r.text("#playNotice"))

    # jumping to a beat boundary costs one
    for n in range(len(r.page.query_selector_all("#beats > li")) + 1, 6):
        r.page.click("#choices .choice >> nth=0")
        r.page.wait_for_function(
            "document.getElementById('beats').children.length===%d" % n, timeout=15000)
    r.page.click("#turnbackBtn")
    r.page.wait_for_selector("#turnback .tb", timeout=4000)
    pts = r.page.query_selector_all("#turnback .tb")
    if len(pts) > 1:
        pts[-1].click()
        r.page.wait_for_timeout(400)
        check("a beat rewind costs one", left() == 2, left())
        check("the notice reports what is left", "rewind" in r.text("#playNotice").lower(),
              r.text("#playNotice"))
    else:
        check("a beat rewind costs one", False, "no beat-boundary point offered")

    # drain the count and confirm the floor holds. Writing localStorage alone is
    # not enough -- the page runs off its in-memory state, so reload and resume.
    r.page.evaluate("""() => {
      const k='margin:run:v2', o=JSON.parse(localStorage.getItem(k));
      o.rewinds=0; localStorage.setItem(k, JSON.stringify(o));
    }""")
    r.page.reload()
    r.page.wait_for_selector("#resume", timeout=5000)
    r.page.click("#resume")
    r.page.wait_for_selector("#play", state="visible", timeout=5000)
    # the earlier rewind truncated the snapshots, so there may be nothing to turn
    # back to yet -- correct behaviour, but take a turn so the panel has entries
    r.page.wait_for_selector("#choices .choice", timeout=5000)
    n0 = r.page.eval_on_selector("#beats", "e => e.children.length")
    r.page.click("#choices .choice >> nth=0")
    r.page.wait_for_function(
        "document.getElementById('beats').children.length===%d" % (n0 + 1), timeout=15000)
    r.page.wait_for_selector("#turnbackBtn", state="visible", timeout=5000)
    r.page.click("#turnbackBtn")
    r.page.wait_for_selector("#turnback", timeout=4000)
    panel = r.text("#turnback")
    check("exhausted count is shown", "no rewinds left" in panel.lower(), panel)
    # the invariant is that NO paid entry is clickable, not that one exists --
    # with a short snapshot list the only point on offer may be the free undo
    state = r.page.eval_on_selector_all("#turnback .tb", """els => els.map(e => ({
      free: e.textContent.indexOf('undo, free') >= 0, disabled: e.disabled }))""")
    paid = [e for e in state if not e["free"]]
    check("no paid rewind is clickable when exhausted",
          all(e["disabled"] for e in paid),
          "%d paid, %d of them disabled" % (len(paid), sum(1 for e in paid if e["disabled"])))
    check("the free undo stays available",
          all(not e["disabled"] for e in state if e["free"]), str(state))
    r.close()


def scenario_wander(browser):
    print("\n[10] wandering with routes open is not drift")

    def roams(run, blob, is_outline, turns):
        if is_outline:
            return json.dumps(outline())
        # far from the current beat every turn, but the outline can still resolve
        return turn(PROSE, ["Go further.", "Go back.", "Stop and look."],
                    {"beat": "somewhere else entirely", "place": "off the canal",
                     "resolve": 6, "gain": [], "lose": [], "edges": [], "invalidate": []},
                    {"satisfied": False, "next": None,
                     "reachable": ["n3", "n4", "n5", "n6", "n7"]}, {"spend": []})

    r = Run(browser, roams)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    for n in range(2, 7):
        r.page.click("#choices .choice >> nth=0")
        r.page.wait_for_function(
            "document.getElementById('beats').children.length===%d" % n, timeout=15000)

    drift = r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2')).drift")
    check("six turns off-beat, drift still zero", drift == 0, drift)
    check("still attached to the outline", r.visible("#arc"))
    check("no detach notice", "no longer reaches you" not in r.text("#playNotice"),
          r.text("#playNotice"))
    r.close()


def scenario_reachcost(browser):
    print("\n[11] losing reach costs condition")

    # turn 2 loses two beats and the narrator refuses to pay, so the floor fires.
    # turn 3 onward reports the docked value and loses nothing more.
    def closing(run, blob, is_outline, turns):
        if is_outline:
            return json.dumps(outline())
        reach = ["n3", "n4", "n5", "n6"] if turns == 1 else ["n5", "n6"]
        res = 7 if turns <= 2 else 5
        return turn(PROSE, ["A.", "B.", "C."],
                    {"beat": "turn %d" % turns, "place": "the canal", "resolve": res,
                     "gain": [], "lose": [], "edges": [], "invalidate": []},
                    {"satisfied": False, "next": None, "reachable": reach}, {"spend": []})

    r = Run(browser, closing)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)

    def cond():
        return r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2')).resolve")

    def step(n):
        r.page.click("#choices .choice >> nth=0")
        r.page.wait_for_function(
            "document.getElementById('beats').children.length===%d" % n, timeout=15000)

    check("condition starts where the narrator put it", cond() == 7, cond())

    step(2)
    check("losing two beats costs condition even when the narrator won't",
          cond() == 5, cond())

    # the request for the NEXT turn is the first one built after the loss
    step(3)
    sent = r.seen[-1]["messages"][-1]["content"]
    check("the closing is announced to the narrator", "[THE WORLD CLOSED]" in sent,
          sent[:200])
    check("it names how many", "2 beats" in sent, sent[:200])
    check("no further cost when nothing is lost", cond() == 5, cond())

    step(4)
    nxt = r.seen[-1]["messages"][-1]["content"]
    check("and the notice clears once paid", "[THE WORLD CLOSED]" not in nxt, nxt[:200])
    check("condition holds steady", cond() == 5, cond())
    r.close()


def scenario_identity(browser):
    print("\n[12] who you are — optional")

    r = Run(browser, normal_script)
    check("panel is present", r.visible(".whopanel"))
    check("and collapsed by default",
          not r.page.eval_on_selector(".whopanel", "e => e.open"))

    # a run with nothing filled in must carry no identity block at all
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    blank_outline = "\n".join(m["content"] for m in r.seen[0]["messages"])
    check("absent when unused", "[WHO THEY ARE" not in blank_outline)
    r.close()

    r = Run(browser, normal_script)
    r.page.eval_on_selector(".whopanel", "e => e.open = true")
    r.page.fill("#idName", "Adaeze Okonkwo")
    r.page.fill("#idPron", "she/her")
    r.page.fill("#idKind", "Igbo, third generation off-world")
    r.page.fill("#idBody", "fifty-one, broad-shouldered, a burn scar along one forearm")
    r.page.fill("#idBear", "speaks slowly, never repeats herself")
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)

    outline = "\n".join(m["content"] for m in r.seen[0]["messages"])
    check("reaches the outline", "[WHO THEY ARE" in outline)
    check("carries the name", "Adaeze Okonkwo" in outline)
    check("carries kind and pronouns", "Igbo" in outline and "she/her" in outline)

    rules = r.seen[1]["messages"][0]["content"]
    check("reaches the narrator", "[WHO THEY ARE" in rules)
    check("carries body and bearing", "burn scar" in rules and "never repeats herself" in rules)
    check("tells the narrator not to make it the subject",
          "not a theme" in rules and "Write a person, not a category" in rules)

    saved = r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2')).ident")
    check("persisted with the run", bool(saved) and saved.get("pronouns") == "she/her",
          str(saved))
    r.close()


def scenario_leak(browser):
    print("\n[13] choices must not leak into the prose")

    leaked = ('The line hisses. Somewhere behind her a door closes.\n\n'
              '- Tell her you are ready and ask her to work on it with you anyway.\n'
              '- Ask her what she saw three years ago, before she stopped.\n'
              '- Hang up and compute 48 alone, as she suggests.')

    def sloppy(run, blob, is_outline, turns):
        if is_outline:
            return json.dumps(outline())
        return turn(leaked, ["Ask her to work on it with you anyway, ready or not.",
                             "What did you see three years ago?",
                             "Hang up and compute 48 alone."],
                    {"beat": "she asks if you are ready", "place": "the phone",
                     "resolve": 6, "gain": [], "lose": [], "edges": [], "invalidate": []},
                    {"satisfied": False, "next": None,
                     "reachable": ["n3", "n4", "n5", "n6"]}, {"spend": []})

    r = Run(browser, sloppy)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    prose = r.text("#prose")
    check("the scene itself survives", "door closes" in prose, prose[:160])
    check("the leaked list is stripped", "Tell her you are ready" not in prose, prose[-200:])
    check("three choices still render",
          len(r.page.query_selector_all("#choices .choice")) == 3)
    check("the buttons keep their own wording",
          "ready or not" in r.text("#choices"), r.text("#choices"))
    r.close()


def scenario_continue(browser):
    print("\n[14] keeping going past the ending")

    # close the book by attrition, which is the case that would re-close itself
    def dying(run, blob, is_outline, turns):
        if is_outline:
            return json.dumps(outline())
        return turn(PROSE, ["A.", "B.", "C."],
                    {"beat": "turn %d" % turns, "place": "the canal",
                     "resolve": max(0, 4 - turns * 2),
                     "gain": [], "lose": [], "edges": [], "invalidate": []},
                    {"satisfied": False, "next": None,
                     "reachable": ["n3", "n4", "n5", "n6"], "ending": None}, {"spend": []})

    r = Run(browser, dying)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    for n in range(2, 6):
        if r.visible("#ending"):
            break
        r.page.click("#choices .choice >> nth=0")
        r.page.wait_for_timeout(1400)

    r.page.wait_for_selector("#ending", state="visible", timeout=20000)
    check("the book closed", r.visible("#ending"))
    check("keep going is offered", r.visible("#continueOn"))
    check("it reads as a first continuation", r.text("#continueOn") == "Keep going",
          r.text("#continueOn"))

    before = r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2') || 'null')")
    check("the save was cleared by the ending", before is None)

    r.page.click("#continueOn")
    r.page.wait_for_selector("#choices .choice", timeout=20000)

    check("play resumed", not r.visible("#ending"))
    check("the notice explains it", "past the ending" in r.text("#playNotice").lower(),
          r.text("#playNotice"))
    cond = r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2')).resolve")
    check("zero condition was lifted off the floor", cond >= 1, cond)
    check("the run is saved again",
          r.page.evaluate("() => localStorage.getItem('margin:run:v2') !== null"))

    rules = r.seen[-1]["messages"][0]["content"]
    check("the narrator is told the book already closed", "PAST THE ENDING" in rules)
    check("and told not to undo it", "do not undo the ending" in rules.lower(), "")
    check("the outline is dropped", "[BEAT]" not in r.seen[-1]["messages"][-1]["content"])
    check("arc meter retired", not r.visible("#arc"))
    r.close()


def scenario_persistence(browser):
    print("\n[7] saving and resuming")
    r = Run(browser, normal_script)
    r.begin()
    r.page.wait_for_selector("#choices .choice", timeout=15000)
    r.page.click("#choices .choice >> nth=0")
    r.page.wait_for_function("document.getElementById('beats').children.length===2", timeout=15000)
    saved = r.page.evaluate("() => JSON.parse(localStorage.getItem('margin:run:v2'))")
    check("run persisted", bool(saved) and saved.get("turn") == 2, str(saved)[:120] if saved else "none")
    check("outline persisted with it", bool(saved.get("skeleton")))
    check("snapshots persisted", len(saved.get("snaps", [])) >= 1)
    check("transcript persisted", len(saved.get("transcript", [])) == 2)

    r.page.reload()
    r.page.wait_for_selector("#begin", timeout=5000)
    check("resume offered after reload", r.visible("#resume"))
    r.page.click("#resume")
    r.page.wait_for_selector("#play", state="visible", timeout=5000)
    check("resumed into play", r.visible("#prose") and len(r.text("#prose")) > 100)
    check("resumed chronicle intact",
          r.page.eval_on_selector("#beats", "e => e.children.length") == 2)
    r.close()


# ----------------------------------------------------------------- main
def main():
    if not (HERE / "index.html").exists():
        sys.exit("index.html missing — run patch.py first")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not importable — pip install --user playwright")

    httpd = serve()
    print("\nThe Margin — full functionality test (network stubbed, no API calls)")
    t0 = time.time()
    with sync_playwright() as p:
        # The bundled build can lag the installed playwright version, so prefer a
        # real Chrome/Chromium on the box and only fall back to the download.
        args = ["--no-sandbox", "--disable-dev-shm-usage"]
        browser = None
        for kw in ({"channel": "chrome"}, {"channel": "chromium"}, {}):
            try:
                browser = p.chromium.launch(headless=not HEADED, args=args, **kw)
                print("  browser: %s" % (kw.get("channel") or "bundled"))
                break
            except Exception:
                continue
        if browser is None:
            httpd.shutdown()
            sys.exit("no usable browser — run: python3 -m playwright install chromium")
        for fn in (scenario_premise, scenario_lore, scenario_play,
                   scenario_turnback, scenario_ending, scenario_failures,
                   scenario_drift, scenario_wander, scenario_rewinds,
                   scenario_reachcost, scenario_identity, scenario_leak,
                   scenario_continue, scenario_persistence):
            try:
                out = fn(browser)
                if hasattr(out, "close"):
                    out.close()
            except Exception as e:
                check("%s did not crash" % fn.__name__, False, repr(e))
        browser.close()
    httpd.shutdown()

    print("\n%s  —  %d passed, %d failed  (%.1fs)\n" %
          ("ALL PATHS HELD" if not FAIL else "%d FAILED" % len(FAIL),
           len(PASS), len(FAIL), time.time() - t0))
    if FAIL:
        for f in FAIL:
            print("  failed: %s" % f)
        print()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
