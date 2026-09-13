#!/usr/bin/env python3
"""Turn the artifact build into a locally-served build.

Replaces the window.claude capability resolution with a fetch shim that talks
to the local proxy. Everything else in the file is untouched.

    python3 patch.py            generate index.html
    python3 patch.py --check     report only; exit 1 if regeneration is needed
    python3 patch.py --force     regenerate over local edits

index.html is BUILD OUTPUT. patch.py records what it generated in
.build-state.json and refuses to overwrite an index.html that no longer matches,
because that means someone edited the output directly and a silent regenerate
would throw the edit away. Edit the-margin-v2.html, or pass --force and accept
the loss.
"""
import hashlib, json, pathlib, sys, time

HERE = pathlib.Path(__file__).parent
SRC = HERE / "the-margin-v2.html"
OUT = HERE / "index.html"
STATE = HERE / ".build-state.json"

MARKER = 'if(window.claude && typeof window.claude.use === "function"){'

SHIM = r'''/* ============ local runtime shim — replaces the artifact sample capability ============ */
function mapErr(status, text){
  if(status === 401 || status === 403) return {code:"not_granted", message:"the server rejected the API key"};
  if(status === 429) return {code:"rate_limited", message:"the API is rate limiting"};
  if(status === 413) return {code:"prompt_too_large", message:"the prompt exceeded the limit"};
  return {code:"upstream_error", message:"HTTP " + status + " " + String(text || "").slice(0, 240)};
}

function localSample(input, opts){
  opts = opts || {};
  var turns = (typeof input === "string") ? [{role:"user", content:input}] : input;
  var acc = "";
  return fetch("/api/sample", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({messages: turns, tier: opts.modelTier || "default"}),
    signal: opts.signal
  }).then(function(res){
    if(!res.ok) return res.text().then(function(t){ throw mapErr(res.status, t); });
    var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
    function pump(){
      return reader.read().then(function(r){
        if(r.done) return {text: acc};
        buf += dec.decode(r.value, {stream: true});
        var lines = buf.split("\n"); buf = lines.pop();
        for(var i=0;i<lines.length;i++){
          var l = lines[i];
          if(l.indexOf("data:") !== 0) continue;
          var d = l.slice(5).trim();
          if(!d || d === "[DONE]") continue;
          try{
            var ev = JSON.parse(d);
            if(ev.type === "content_block_delta" && ev.delta && typeof ev.delta.text === "string"){
              acc += ev.delta.text;
              if(opts.onText) opts.onText({text: acc});
            } else if(ev.type === "error"){
              throw {code:"upstream_error", message:(ev.error && ev.error.message) || "stream error", text: acc};
            }
          }catch(e){ if(e && e.code) throw e; }
        }
        return pump();
      });
    }
    return pump();
  }).catch(function(e){
    if(e && (e.name === "AbortError" || e.code === "cancelled")) throw {code:"cancelled", text: acc};
    if(e && e.code){ e.text = e.text || acc; throw e; }
    throw {code:"upstream_error", message: String((e && e.message) || e), text: acc};
  });
}

sampleFn = localSample;
downloadsNs = {
  save: function(o){
    return new Promise(function(res){
      var b = new Blob([o.data], {type:"text/plain;charset=utf-8"});
      var u = URL.createObjectURL(b);
      var a = document.createElement("a");
      a.href = u; a.download = o.filename || "the-margin.txt";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(u); }, 4000);
      res({saved: true});
    });
  }
};

'''


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build(src):
    if MARKER not in src:
        sys.exit("capability block not found — is the-margin-v2.html the artifact build?")
    a = src.index(MARKER)
    b = src.index("})();", a)
    out = src[:a] + SHIM + src[b:]
    if "window.claude" in out:
        sys.exit("a window.claude reference survived the patch")
    return out


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def main():
    check = "--check" in sys.argv
    force = "--force" in sys.argv

    if not SRC.exists():
        sys.exit("the-margin-v2.html not found next to this script")
    src = SRC.read_text(encoding="utf-8")
    src_sha = sha(src)
    state = load_state()

    # is the existing output ours, or has someone edited it?
    dirty = False
    if OUT.exists() and state.get("output_sha"):
        dirty = sha(OUT.read_text(encoding="utf-8")) != state["output_sha"]

    up_to_date = (state.get("source_sha") == src_sha) and OUT.exists() and not dirty

    if check:
        if dirty:
            print("index.html has local edits that patch.py did not make.")
            print("  Move them into the-margin-v2.html, or accept the loss with --force.")
            sys.exit(1)
        if up_to_date:
            print("index.html is current with the-margin-v2.html (%s)." % src_sha)
            sys.exit(0)
        print("index.html is stale — the-margin-v2.html has changed. Run: python3 patch.py")
        sys.exit(1)

    if dirty and not force:
        print("REFUSING to overwrite index.html.\n")
        print("  It no longer matches what patch.py last generated, which means it was")
        print("  edited directly. index.html is build output — regenerating discards")
        print("  those edits.\n")
        print("  Move the change into the-margin-v2.html and re-run, or:")
        print("      python3 patch.py --force\n")
        sys.exit(1)

    if up_to_date and not force:
        print("index.html already current (%s). Nothing to do." % src_sha)
        return

    out = build(src)
    OUT.write_text(out, encoding="utf-8")
    STATE.write_text(json.dumps({
        "source": SRC.name,
        "source_sha": src_sha,
        "output_sha": sha(out),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, indent=2) + "\n")
    print("index.html written — %d KB, from %s (%s)" % (len(out) // 1024, SRC.name, src_sha))
    if force and dirty:
        print("  (--force: local edits to index.html were discarded)")


if __name__ == "__main__":
    main()
