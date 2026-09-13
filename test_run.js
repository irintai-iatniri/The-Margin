#!/usr/bin/env node
/* End-to-end test for The Margin.
 *
 * Pulls the real prompt builders and the real parsers out of index.html --
 * not copies of them -- and drives them against the running proxy. Every
 * request is sent at the "quick" tier, so this costs nothing beyond what a
 * Haiku call already costs.
 *
 *   ./run.sh            # in one terminal
 *   node test_run.js    # in another
 *
 * Exit code 0 means every contract held.
 */
const fs = require("fs");
const path = require("path");

const PORT = process.env.MARGIN_PORT || 7878;
const BASE = `http://127.0.0.1:${PORT}`;
const TURNS = Number(process.env.MARGIN_TEST_TURNS || 4);

let pass = 0, fail = 0;
function check(name, ok, detail) {
  (ok ? pass++ : fail++);
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? "\n        " + detail : ""}`);
}

/* ---- lift the real functions out of the page ---- */
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

function slice(from, to) {
  const a = script.indexOf(from);
  const b = script.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`could not lift ${from} .. ${to}`);
  return script.slice(a, b);
}

// DRIVES/TONE_NOTE/STOP + lore + skeletonPrompt + verifySkeleton + registerSecrets
const partA = slice("var DRIVES = {", "function forgeStep(");
// the narrator prompt, node helpers and every parser
const partB = slice("function hasArc(){", "/* ============================ rendering");

const S_stub = `
// rulesTurn reads the scene-length control from the DOM; in node there isn't
// one, so stub it and let scene() fall back to S.scene
var document = { getElementById: function(){ return null; } };
var S = null;
function blankState(who, stake, tone, dr){
  return { who:who, stake:stake, tone:tone, drive:dr, place:"—", resolve:8, items:[],
           turn:0, beats:[], transcript:[], history:[], skeleton:null, node:null,
           visited:[], nodeTurns:0, secrets:{}, edges:[], edgeSeq:0, lore:null,
           snaps:[], lastChoices:[], ended:null };
}
function drive(){ return DRIVES[(S && S.drive) || "lose"] || DRIVES.lose; }
`;

const api = new Function(
  S_stub + partA + partB +
  `; return { DRIVES, skeletonPrompt, verifySkeleton, registerSecrets, chunkLore,
              rulesTurn, contextTurn, buildInput, parseReply, proseOnly, blockJSON,
              currentNode, routesFrom, dueSecrets, enterNode:null,
              setS:function(v){ S = v; }, getS:function(){ return S; } };`
)();

/* ---- the proxy ---- */
async function sample(input, tier) {
  const messages = (typeof input === "string") ? [{role:"user", content:input}] : input;
  const res = await fetch(`${BASE}/api/sample`, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({messages, tier: tier || "quick"})
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${(await res.text()).slice(0,200)}`);
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = "", acc = "", deltas = 0;
  for (;;) {
    const r = await reader.read();
    if (r.done) break;
    buf += dec.decode(r.value, {stream:true});
    const lines = buf.split("\n"); buf = lines.pop();
    for (const l of lines) {
      if (!l.startsWith("data:")) continue;
      const d = l.slice(5).trim();
      if (!d || d === "[DONE]") continue;
      try {
        const ev = JSON.parse(d);
        if (ev.type === "content_block_delta" && ev.delta && typeof ev.delta.text === "string") {
          acc += ev.delta.text; deltas++;
        }
      } catch {}
    }
  }
  return {text: acc, deltas};
}

function looseJSON(raw) {
  const t = String(raw).replace(/```(?:json)?/gi, "");
  const a = t.indexOf("{"), b = t.lastIndexOf("}");
  if (a < 0 || b <= a) return null;
  try { return JSON.parse(t.slice(a, b + 1)); } catch { return null; }
}

/* ---- the run ---- */
(async function main() {
  const WHO = "a night bargeman on a canal that freezes from the bottom up";
  const STAKE = "the girl asleep under the tarp";
  const DRIVE = "protect";
  const TONE = "grim";

  console.log(`\nThe Margin — end-to-end test against ${BASE}`);
  console.log(`  premise: ${WHO}, who ${api.DRIVES[DRIVE].verb} ${STAKE}\n`);

  console.log("[0] reachability");
  try {
    const r = await fetch(BASE + "/");
    check("page serves", r.ok && (await r.text()).includes("localSample"));
  } catch (e) {
    console.log(`  FAIL  page serves\n        ${e.message}\n\n  Is ./run.sh running?\n`);
    process.exit(1);
  }

  console.log("\n[1] the outline");
  const t0 = Date.now();
  let out;
  try {
    out = await sample(api.skeletonPrompt(WHO, STAKE, TONE, DRIVE), "quick");
  } catch (e) {
    console.log(`  FAIL  outline call\n        ${e.message}\n`);
    process.exit(1);
  }
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  check(`outline streamed (${out.deltas} deltas, ${secs}s)`, out.deltas > 1);

  let sk = looseJSON(out.text);
  check("outline is parseable JSON", !!sk && Array.isArray(sk.nodes),
        out.text.slice(-200));
  if (!sk || !Array.isArray(sk.nodes)) { console.log("\n  cannot continue without an outline\n"); process.exit(1); }

  check(`beats generated (${sk.nodes.length})`, sk.nodes.length >= 8);

  // The page retries once when verification rejects an outline, so the suite
  // does too -- a model that occasionally emits a bad graph is expected, and
  // what matters is that a retry recovers rather than that attempt one is clean.
  let problems = api.verifySkeleton(sk);
  let attempts = 1;
  if (problems.length) {
    console.log(`  note  attempt 1 rejected: ${problems.slice(0,2).join("; ")}`);
    const retry = await sample(api.skeletonPrompt(WHO, STAKE, TONE, DRIVE), "quick");
    const sk2 = looseJSON(retry.text);
    if (sk2 && Array.isArray(sk2.nodes)) {
      const p2 = api.verifySkeleton(sk2);
      attempts = 2;
      if (p2.length < problems.length) { sk = sk2; problems = p2; }
    }
  }
  check(`verification clean (attempt ${attempts})`, problems.length === 0, problems.join("; "));
  const terms = sk.nodes.filter(n => n.terminal);
  check(`endings present (${terms.map(n=>n.terminal).join(", ")})`,
        terms.some(n=>n.terminal==="kept") && terms.some(n=>n.terminal==="lost"));
  const secrets = api.registerSecrets(sk);
  check(`setups planted (${Object.keys(secrets).length})`, Object.keys(secrets).length >= 4);
  const abstractExits = sk.nodes.filter(n =>
    /understand|realis|realiz|accept|feel|know that|come to terms/i.test(n.exit || ""));
  check(`exits are observable (${sk.nodes.length - abstractExits.length}/${sk.nodes.length})`,
        abstractExits.length <= 2,
        abstractExits.map(n=>`${n.id}: ${n.exit}`).join(" | "));

  /* ---- play ---- */
  const S = { who:WHO, stake:STAKE, tone:TONE, drive:DRIVE, scene:"standard",
              place:"—", resolve:8, items:[],
              turn:0, beats:[], transcript:[], history:[], skeleton:sk, node:sk.start,
              visited:[sk.start], nodeTurns:0, secrets, edges:[], edgeSeq:0, lore:null,
              snaps:[], lastChoices:[], ended:null };
  api.setS(S);
  for (const s of (sk.nodes.find(n=>n.id===sk.start)?.sow || []))
    if (secrets[s.id]) secrets[s.id].status = "sown";

  console.log(`\n[2] ${TURNS} turns`);
  let action = "Open the story. Put me in motion, already in trouble.";
  let advanced = 0, edgesSeen = 0;

  for (let i = 1; i <= TURNS; i++) {
    let res;
    try { res = await sample(api.buildInput(action), "quick"); }
    catch (e) { check(`turn ${i}`, false, e.message); break; }

    const r = api.parseReply(res.text);
    const words = r.prose.split(/\s+/).filter(Boolean).length;

    check(`turn ${i}: prose (${words}w)`, words >= 40);
    check(`turn ${i}: three choices`, r.choices.length === 3,
          JSON.stringify(r.choices));
    check(`turn ${i}: @PUBLIC valid`, !!r.pub && typeof r.pub.beat === "string");
    check(`turn ${i}: @NODE valid`, !!r.node && typeof r.node.satisfied === "boolean");
    check(`turn ${i}: @PRIVATE valid`, !!r.priv && Array.isArray(r.priv.spend));

    if (r.pub) {
      if (typeof r.pub.place === "string" && r.pub.place.trim()) S.place = r.pub.place.trim();
      if (typeof r.pub.resolve === "number") S.resolve = Math.max(0, Math.min(10, Math.round(r.pub.resolve)));
      (r.pub.gain||[]).forEach(g => { if (g && !S.items.includes(g)) S.items.push(g); });
      (r.pub.edges||[]).forEach(() => edgesSeen++);
      if (r.pub.beat) S.beats.push(String(r.pub.beat).trim());
    }
    S.history.push({role:"user", content: api.contextTurn(action)});
    S.history.push({role:"assistant", content: res.text});
    S.transcript.push({action, prose: r.prose});
    S.turn++; S.nodeTurns++;
    S.lastChoices = r.choices.slice();

    if (r.node && r.node.satisfied === true) {
      const legal = api.routesFrom(S.node).map(e => e.to);
      const next = r.node.next ? String(r.node.next) : null;
      const ok = next && legal.includes(next);
      check(`turn ${i}: advance is gate-legal`, ok || legal.length === 1,
            `wanted ${next}, legal: ${legal.join(",")}`);
      if (ok) { S.node = next; S.nodeTurns = 0; advanced++;
                if (!S.visited.includes(next)) S.visited.push(next);
                for (const s of (api.currentNode().sow||[]))
                  if (secrets[s.id] && secrets[s.id].status==="latent") secrets[s.id].status="sown"; }
    }

    action = r.choices[0] || "Wait, and watch.";
  }

  console.log("\n[3] state after play");
  check(`chronicle accumulated (${S.beats.length})`, S.beats.length >= TURNS - 1);
  check(`edges recorded (${edgesSeen})`, edgesSeen >= 1);
  check(`resolve is sane (${S.resolve})`, S.resolve >= 0 && S.resolve <= 10);
  check(`place tracked (${S.place})`, S.place !== "—");
  console.log(`  note  advanced ${advanced} beat(s) in ${TURNS} turns, visited ${S.visited.length}`);
  const unspent = Object.values(secrets).filter(s => s.status !== "spent").length;
  console.log(`  note  ${unspent}/${Object.keys(secrets).length} setups still unspent`);

  console.log("\n[4] prompt budget");
  const ctx = api.contextTurn("a representative action");
  const full = api.buildInput("a representative action")
                  .reduce((n,t) => n + t.content.length, 0);
  check(`assembled prompt fits (${Math.round(full/1024)}KB of 64KB)`, full < 64*1024);
  check(`context block reasonable (${Math.round(ctx.length/1024)}KB)`, ctx.length < 20*1024);

  console.log(`\n${fail === 0 ? "ALL CONTRACTS HELD" : fail + " FAILED"}  —  ${pass} passed, ${fail} failed\n`);
  process.exit(fail === 0 ? 0 : 1);
})();
