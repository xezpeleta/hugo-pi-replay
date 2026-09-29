# AGENTS.md — writing a replay of your own session

This file is for **coding agents** (Pi, Claude Code, Cursor, Aider, …). It
tells you how to produce a `replay.json` that the `pi-replay` shortcode can
embed, summarizing a session — usually **your own** — as an animated,
condensed screen-recording-style widget. Humans maintaining a site that
embeds replays can hand this file to an agent verbatim.

## What a replay is

A replay is an **authored condensation, not a raw dump**. The reader gives
it ~10 seconds; your job is to make those seconds faithful. Concretely:

- The JSON describes *one task*, not the whole session: one user prompt,
  one codemode script (condensed), the few tool calls that mattered, one
  output, one answer.
- The animation implies causality and duration. Timings must be plausible
  for the work shown; totals must come from the real session.
- Everything shown must have actually happened. You may shorten code and
  collapse calls; you may not invent results.

## Ground rules

1. **Fidelity.** Numbers, command lines, file names, exit statuses,
   outputs: copy them from the session log. If you don't know, don't guess
   — leave the detail out.
2. **Condense, don't fabricate.** A 200-line script becomes the ~10–30
   lines that carry the idea. Collapsed regions should be visibly coherent
   (working JS), not `...` soup.
3. **Plausible timings.** `wallMs` ≥ every `t + d`; keep the relative
   rhythm of the real session (a 4-minute MCP poll shouldn't animate as
   300 ms). A quick pre-run sanity figure: with default playback, typing
   runs at ~55 chars/s, script streaming at ~0.9 chars/ms.
4. **No secrets.** Strip tokens, absolute home paths you'd rather not
   publish, and customer names unless public.
5. **The fallback is the contract.** The plain-text transcript inside the
   shortcode must tell the same story as the JSON. Write it last, from the
   finished JSON.

## Format reference

Full JSON Schema: [`schemas/replay.schema.json`](schemas/replay.schema.json).
Validate against it before embedding.

| Field    | Type                     | Meaning |
|----------|--------------------------|---------|
| `cwd`    | string                   | Working dir, shown in the terminal header (tilde-ize freely). |
| `model`  | string                   | `provider/model • thinkingLevel`, shown next to cwd. |
| `prompt` | string                   | The user's task, typed verbatim. One or two sentences. |
| `intro`  | string                   | One sentence of intent before the script streams ("I'll pull X and do Y"). |
| `script` | array of `[class, text]` | The codemode script, tokenized for highlighting. See below. |
| `calls`  | array of objects         | Top-level tool calls, `{"t": startMs, "d": durationMs, "name", "args"}` sorted by `t`, `t` of the first = 0. |
| `wallMs` | number                   | Wall-clock ms of the run; drives the spinner. ≥ max `t + d`. |
| `output` | string                   | The final tool result (codemode's return), printed verbatim at the end. |
| `answer` | array of blocks          | Final message: `["p", html]` paragraphs and `["ul", [html, …]]` lists, max ~4 blocks. |

In `answer` HTML: only `<b>`, `<i>`, `<code>` are safe and styled;
escape `<`, `>`, `&` in text.

`script` tokens: `k` keyword, `f` call, `s` string, `n` number, `c`
comment, `p` punctuation, `""` plain. **Whitespace belongs to the following
token** (`["p", " ="]`, not `["p", "= "]`); concatenating all `text`s must
reproduce the script exactly. The script must be syntactically valid
JavaScript (evaluated as an async function body: top-level `await` and
`return` are fine).

`calls.args` is a display string, not structured data: `{ cmd: "ls -la", timeout: 5000 }`,
values truncated at ~72 chars with `…`.

## Workflow

### 1. Locate the session log

Pi writes sessions as JSONL under `~/.pi/agent/sessions/<sanitized-cwd>/`.
Each line is an event: `prompt` (user text), `message` (assistant text),
`toolCall` / `toolResult` (with timestamps), etc. If you're not Pi, use
whatever equivalent log you have — the format above is agent-agnostic.

### 2. Scaffold with the converter

The module ships a best-effort scaffold generator for Pi sessions
(stdlib-only Python 3.9+):

```sh
python3 scripts/pi-session-to-replay.py --latest --out replay.json   # most recent session
python3 scripts/pi-session-to-replay.py --list                       # pick explicitly
python3 scripts/pi-session-to-replay.py --session ~/.pi/agent/sessions/.../xxx.jsonl \
    --speed 4 --max-calls 25 --out replay.json
```

It extracts prompt/intro/script/output/answer candidates, tokenizes the
script (classes match the reference player), rebases call timings, and
prints warnings for anything it couldn't find. It warns instead of failing.
**Scaffolding is not publishing** — the checklist below is your job.

### 3. Curate (the actual work)

Work through this checklist on the scaffold:

- [ ] `prompt` — the user's *task*, not the chat message verbatim if that
      rambles. Keep it short.
- [ ] `intro` — one sentence, present tense, no hedging. Delete if the
      session had none and write one.
- [ ] `script` — condensed but valid. Remove boilerplate, retries, dead
      ends. Keep the shape of the real work (the loops, the awaits).
- [ ] `calls` — keep the calls that carry the story (usually ≤ 10;
      collapse the rest into the script's shape). Re-time the survivors to
      match the condensed script.
- [ ] `wallMs` — real total (from session timestamps), possibly scaled.
- [ ] `output` — the interesting part of the final result, trimmed.
- [ ] `answer` — your real final message, cut to ≤ 4 blocks.
- [ ] `cwd`, `model` — as they really were; tilde-ize `cwd`.

### 4. Validate

```sh
python3 scripts/pi-session-to-replay.py --validate replay.json
```

Checks required keys, token shape and sortedness, `wallMs` consistency,
answer block shape, and (if `node` is installed) that the concatenated
script parses as JavaScript. Fix everything it reports.

### 5. Embed

Page bundle the JSON next to the post, then embed with a plain-text
fallback (written from the JSON, see rule 5 above):

```md
{{< pi-replay data="replay.json" caption="One-liner of what happened." >}}
…plain-text transcript…
{{< /pi-replay >}}
```

Build the site and watch it once at 1× speed before publishing.

## Minimal example

A complete, valid replay (`exampleSite/content/posts/fib-replay/replay.json`,
animated in the bundled demo):

```json
{
  "cwd": "~/scratch",
  "model": "demo-model • medium",
  "prompt": "Use codemode to check whether the 10th Fibonacci number is even",
  "intro": "I'll compute the sequence up to the 10th term and check its parity.",
  "script": [
    ["k", "const"], ["", " fib"], ["p", " ="],
    ["p", " ["], ["n", "0"], ["p", ","],
    ["n", " 1"], ["p", "];"], ["k", "\nwhile"],
    ["p", " ("], ["", "fib"], ["p", "."],
    ["", "length"], ["p", " <"], ["n", " 10"],
    ["p", ")"], ["p", " {"], ["", "\n  fib"],
    ["p", "."], ["f", "push"], ["p", "("],
    ["", "fib"], ["p", "."], ["f", "at"],
    ["p", "(-"], ["n", "1"], ["p", ")"],
    ["p", " +"], ["", " fib"], ["p", "."],
    ["f", "at"], ["p", "(-"], ["n", "2"],
    ["p", "));"], ["p", "\n}"], ["k", "\nconst"],
    ["", " n"], ["p", " ="], ["", " fib"],
    ["p", "."], ["f", "at"], ["p", "(-"],
    ["n", "1"], ["p", ");"], ["k", "\nreturn"],
    ["p", " {"], ["", " n"], ["p", ","],
    ["", " even"], ["p", ":"], ["", " n"],
    ["p", " %"], ["n", " 2"], ["p", " ==="],
    ["n", " 0"], ["p", " };"], ["", "\n"]
  ],
  "calls": [],
  "wallMs": 1800,
  "output": "{\n  \"n\": 34,\n  \"even\": true\n}",
  "answer": [
    [
      "p",
      "The 10th Fibonacci number is <b>34</b>, and it is <b>even</b> — <code>34 % 2 === 0</code>."
    ],
    [
      "p",
      "Fibonacci numbers are even exactly when their index is a multiple of three, so <code>fib[9]</code> was always going to be even."
    ]
  ]
}
```

For the full-size version, see
`exampleSite/content/posts/codemode-replay/codemode-replay.json` — a real
condensed Pi codemode session with 335 collapsed tool calls.
