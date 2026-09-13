# The Margin

An AI-written gamebook. An outline is plotted once, before a word of prose
exists; play fills it in, turn by turn, against whatever you actually did.

## Run it

```sh
export ANTHROPIC_API_KEY=sk-ant-...
python3 serve.py
```

Then open <http://127.0.0.1:7878>. No build step, standard library only.

The Rust server does the same job and is there when you want it:

```sh
export PATH="$HOME/.cargo/bin:$PATH"
cargo run --release
```

Both serve `index.html` and proxy `/api/sample` to the messages endpoint,
passing the SSE straight through so prose renders as it is written. The key
never reaches the browser.

## The files

| | |
|---|---|
| `index.html` | the whole game — markup, styles, engine |
| `serve.py` | stdlib server and proxy |
| `src/main.rs`, `Cargo.toml` | the same, in Rust |
| `patch.py` | rebuilds `index.html` from `the-margin-v2.html` |
| `the-margin-v2.html` | the artifact build, kept as the source |

When a new artifact build lands on the Desktop, drop it in beside `patch.py`
and re-run `python3 patch.py`. The patch swaps the hosted sampling capability
for a `fetch` against the local proxy and touches nothing else.

## Knobs

| variable | default |
|---|---|
| `MARGIN_PORT` | `7878` |
| `MARGIN_QUICK` | `claude-haiku-4-5-20251001` — the Brisk tier |
| `MARGIN_DEFAULT` | `claude-sonnet-5` — the Considered tier |
| `MARGIN_COMPLEX` | `claude-opus-5` — the outline call |
| `MARGIN_MAX_TOKENS` | `4096` |

The outline is the one call that needs headroom: twelve beats and eight
setups run around 3,000 tokens of JSON, and a truncated outline fails as
unparseable rather than as anything legible. If outlines start coming back
malformed, raise `MARGIN_MAX_TOKENS` before suspecting anything else.

## How it works

**The outline.** One call at the start turns your premise into twelve beats,
three endings, and eight setups — facts about the world you have not been
given yet. A beat says *what must happen*, never who or how or in what room,
which is why the same outline can run twice and produce two unrecognisable
books. It is checked before play: every beat reachable, every ending
reachable, no dead ends.

**Two stores.** What you have been shown — transcript, chronicle, inventory —
and what is true. The second is written at the same moment as the prose, not
extracted from it afterward, which is what lets a silence have an authored
reason behind it. The narrator may withhold anything; it may never assert
what the record denies.

**The leftovers.** A run visits about nine of twelve beats, so setups planted
on the others are never paid off. That is deliberate. If every implied thread
paid off, you would learn within five turns that a mention means significance
and start reading the prose as a menu. The ending tells you how many true
things went unlearned, and does not say what they were.

**Turning back.** A snapshot after every turn, ten kept. Restoring returns
resolve, inventory, what had been revealed, and the choices that were on
screen. The state comes back exactly; the prose is written fresh. The same
situation, answered differently — never the same words twice.

## The lore book

Optional `.txt` or `.md` on the opening screen. The first 24,000 characters
go to the outline as canon, so the beat sheet is plotted out of your own
people and places. During play it is split on blank lines and headings and
two passages are retrieved per turn by keyword, so a hundred-page document
costs the same per turn as a one-page one.

Retrieval is keyword, not semantic: a passage that never names its own
subject will not be found. A section headed **Tarn Holloway** that then says
only "he" throughout matches on the heading and nothing else. Headings are
the strongest signal — a structured document retrieves markedly better than
one block of prose.

## If the outline fails

It is one call standing between a premise and a story, so it is never allowed
to be fatal. The forge screen counts beats as they arrive, **Skip the outline**
is always visible, and any failure offers **Play anyway** — which runs the
narrator without an outline, pacing itself and calling its own ending. The
premise you typed is the thing worth protecting.
