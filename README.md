# hugo-pi-replay

A Hugo module that embeds animated **replays of coding-agent sessions** in a
page. A replay is a small JSON document that describes what an agent (like
[Pi](https://earendil.com)) did in a session — the user's prompt, the code it
wrote, the tool calls it made, how long things took, and its final answer —
rendered by this module as a terminal widget that types, streams, and skips
like a screen recording, but needs no video:

- the **prompt** and **intro** are typed out character by character,
- the **codemode script** streams into a syntax-highlighted editor,
- **tool calls** appear and resolve as the script runs,
- a braille **spinner** runs for `wallMs`,
- then the **output** and the **answer** fade in.

A static, readable transcript (the shortcode's inner content) stays in the
page for no-JavaScript visitors, web searches, and copy/paste.

See it live: the widget on
[earendil.com/posts/you-said-no-mcp/](https://earendil.com/posts/you-said-no-mcp/)
is the original this module packages. Or run the bundled demo:

```sh
./demo.sh          # serves exampleSite on http://localhost:1313/
```

## Install

### As a Hugo Module

Requires Go on the machine that builds your site.

```sh
hugo mod init github.com/you/your-site   # once, if you have no go.mod
hugo mod get github.com/xezpeleta/hugo-pi-replay
```

```toml
# hugo.toml / config.toml
[module]
  imports = [
    { path = "github.com/xezpeleta/hugo-pi-replay" }
  ]
```

### As a git submodule (works alongside theme submodules like PaperMod)

```sh
git submodule add https://github.com/xezpeleta/hugo-pi-replay.git themes/hugo-pi-replay
```

```yaml
# config.yaml
theme:
  - PaperMod
  - hugo-pi-replay
```

### Manual copy

Copy `assets/`, `layouts/`, and `hugo.toml` (the `[module]` block is
optional) into your site's directories. You lose update ergonomics, gain
full control.

## Hook it into your head

The module's assets must be linked on pages that use the shortcode. Add to
your base template's `<head>` (for PaperMod: create
`layouts/partials/extend_head.html` in your site — it already exists in
PaperMod's head):

```html
{{ partial "pi-replay-head.html" . }}
```

The partial only emits a fingerprinted, SRI-tagged `<link>` and `<script>`
on pages that actually contain a `pi-replay` shortcode, so other pages stay
clean.

## Use the shortcode

Put a replay JSON next to a page (a [page
bundle](https://gohugo.io/content-management/page-bundles/)), then:

```md
{{< pi-replay data="replay.json" caption="Optional caption." >}}
Your prompt here

What you said you'd do.

codemode
const script = "that was streamed";   // plain-text fallback transcript

...final answer in plain text...
{{< /pi-replay >}}
```

- `data` (or positional `{{< pi-replay "replay.json" >}}`) — a page
  resource in the same bundle, or an absolute URL/path.
- `caption` — optional `<figcaption>`.
- `hideModel`, `hideCwd` — pass `"true"` to hide the model /
  working-directory labels in the terminal footer for this widget.
- The inner content is the **no-JS fallback**: a plain-text transcript,
  HTML-escaped by the shortcode. Keep it a faithful summary of the JSON.

Site-wide defaults can be set in your site config:

```toml
[params.piReplay]
hideModel = true   # hide the model label in every widget's footer
hideCwd = true     # hide the working-directory label in every widget's footer
```

Per-shortcode parameters override the site-wide defaults. Hiding is
presentation-only — the labels remain part of the fetched JSON; omit the
`cwd` / `model` fields from the JSON if you don't want them in the payload
at all (both fields are optional).

## The replay format (short version)

```jsonc
{
  "cwd": "~/Dev/project",             // footer label (optional; hide with hideCwd)
  "model": "provider/model • level",  // footer label (optional; hide with hideModel)
  "prompt": "…",                      // typed out verbatim
  "intro": "…",                       // one sentence before the script runs
  "script": [["k","const"], …],       // codemode script, tokenized (see below)
  "calls": [ {"t": 1200, "d": 300, "name": "bash", "args": "{ cmd: … }"}, … ],
  "wallMs": 81200,                    // spinner duration (>= max t+d)
  "output": "…",                      // final tool result, printed raw
  "answer": [["p","…"], ["ul",["…","…"]]]
}
```

`script` is an array of `[class, text]` token pairs for syntax
highlighting; classes: `k` keyword, `f` function call, `s` string, `n`
number, `c` comment, `p` punctuation, `""` plain. Whitespace lives inside
the following token's text. A formal JSON Schema is at
[`schemas/replay.schema.json`](schemas/replay.schema.json).

For how to **produce** this JSON from a real session — including a
scaffolding converter for Pi session logs — see
[`AGENTS.md`](AGENTS.md). That file is written for coding agents to follow.

## Styling & dark mode

All colors are [CSS custom
properties](https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties)
(`--pi-bg`, `--pi-text`, `--pi-muted`, `--pi-dim`, `--pi-accent`,
`--pi-success`, `--pi-warning`, `--pi-border`, `--pi-user-bg`,
`--pi-tool-pending-bg`, `--pi-tool-success-bg`) scoped to `.pi-replay`, so
you can restyle a widget without touching the module:

```css
.pi-replay { --pi-accent: #b45959; --pi-bg: #fff; }
```

Dark mode is picked up automatically from `.theme-night`, `html.dark`,
`body.dark`, or `html[data-theme="dark"]` (PaperMod's scheme) overriding the
same properties. Fonts: the widget uses the host page's `--mono-font` (with
a generic monospace fallback) and `--prose-hr` (with its own fallback) if
you define them.

## Notes

- `prefers-reduced-motion` is respected: the widget renders fully expanded
  without animation.
- The player initializes itself on DOMContentLoaded; no other script
  dependency. It observes widgets with `IntersectionObserver` (45% visible)
  before starting, so replays below the fold don't burn CPU.
- Tested with Hugo ≥ 0.111. No SCSS, no external JS.

## License

Apache-2.0 — see [`LICENSE`](LICENSE). The player and styles are adapted
from the [Earendil Works website](https://github.com/earendil-works/website)
(Apache-2.0); see [`NOTICE`](NOTICE).
