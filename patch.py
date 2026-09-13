#!/usr/bin/env python3
"""Turn the artifact build into a locally-served build.

Replaces the window.claude capability resolution with a fetch shim that
talks to the local proxy. Everything else in the file is untouched.
"""
import sys, pathlib

HERE = pathlib.Path(__file__).parent
SRC = HERE / "the-margin-v2.html"
OUT = HERE / "index.html"

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

def main():
    if not SRC.exists():
        sys.exit("the-margin-v2.html not found next to this script")
    src = SRC.read_text(encoding="utf-8")

    marker = 'if(window.claude && typeof window.claude.use === "function"){'
    if marker not in src:
        sys.exit("capability block not found — is this the artifact build?")
    a = src.index(marker)
    b = src.index("})();", a)

    out = src[:a] + SHIM + src[b:]
    if "window.claude" in out:
        sys.exit("a window.claude reference survived the patch")
    OUT.write_text(out, encoding="utf-8")
    print("index.html written — %d KB" % (len(out) // 1024))

if __name__ == "__main__":
    main()
