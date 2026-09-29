#!/usr/bin/env python3
"""Scaffold a hugo-pi-replay JSON from a Pi session log.

Pi (https://earendil-works/pi) writes one JSONL file per session under
~/.pi/agent/sessions/<sanitized-cwd>/<timestamp>_<uuid>.jsonl. This script
does the mechanical half of turning such a log into replay data:

  * pulls the prompt, intro, model and cwd,
  * tokenizes the codemode script into syntax-highlighted tokens,
  * derives call timings from the recorded timestamps,
  * converts the final assistant answer into plain answer blocks.

It does NOT do the editorial half: a good replay is a curated condensation of
the session (short intro, representative calls, tight answer). Run this to
get a scaffold, then curate it following AGENTS.md, then validate:

    pi-session-to-replay.py --validate replay.json

Best effort on purpose: it warns instead of failing whenever the log does not
contain what it expects, so you (or your agent) can fill the gaps by hand.

Usage:
  pi-session-to-replay.py --list [N]        # show recent sessions
  pi-session-to-replay.py --latest          # scaffold from newest session
  pi-session-to-replay.py --session FILE    # scaffold from a given file
  pi-session-to-replay.py --validate FILE   # sanity-check a finished replay

Options:
  --speed S      divide all timings by S (e.g. --speed 4 plays 4x faster)
  --max-calls N  keep at most N calls (default 40)
  --out FILE     write JSON here instead of stdout

Stdlib only; Python 3.9+.
"""

import argparse
import datetime
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SESSIONS_DIR = os.path.expanduser("~/.pi/agent/sessions")

KEYWORDS = {
    "abstract", "async", "await", "break", "case", "catch", "class", "const",
    "continue", "debugger", "default", "delete", "do", "else", "enum",
    "export", "extends", "false", "finally", "for", "from", "function", "get",
    "if", "implements", "import", "in", "instanceof", "interface", "let",
    "new", "null", "of", "private", "protected", "public", "readonly",
    "return", "set", "static", "super", "switch", "this", "throw", "true",
    "try", "typeof", "var", "void", "while", "with", "yield",
}

WARN = lambda msg: print("warning: " + msg, file=sys.stderr)


# --------------------------------------------------------------------------
# Session log parsing
# --------------------------------------------------------------------------

def parse_iso(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def load_session(path):
    """Return (header, events): header is the `session` line, events are all
    parsed lines in order, each with an `ms` timestamp when derivable."""
    header, events = None, []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate partial trailing lines
            if entry.get("type") == "session":
                header = entry
                continue
            ms = entry.get("timestamp")
            if isinstance(ms, str):
                ms = parse_iso(ms)
            msg = entry.get("message") or {}
            if not ms and isinstance(msg.get("timestamp"), (int, float)):
                ms = msg["timestamp"]
            entry["ms"] = ms
            events.append(entry)
    if header is None:
        WARN("no `session` header line found; cwd will be empty")
    return header, events


def message_blocks(entry):
    msg = entry.get("message") or {}
    return msg.get("role"), msg.get("content") or []


def first_text(blocks):
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
            return b["text"]
    return ""


def collect(session, events):
    """Extract the interesting pieces of a session."""
    out = {
        "cwd": (session or {}).get("cwd", ""),
        "model": "",
        "prompt": "",
        "intro": "",
        "script_src": "",
        "calls": [],
        "output": "",
        "answer_md": "",
    }
    for e in events:
        if e.get("type") == "model_change":
            out["model"] = "%s/%s" % (e.get("provider", ""), e.get("modelId", ""))
    for e in events:
        if e.get("type") == "thinking_level_change":
            level = e.get("thinkingLevel", "")
            if level:
                out["model"] = (out["model"] + " • " + level).strip(" •")

    saw_tool = False
    intro_done = False
    pending_calls = {}  # toolCall id -> dict
    tool_results = []   # (name, text, is_error)

    for e in events:
        if e.get("type") != "message":
            continue
        role, blocks = message_blocks(e)
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text"):
                if role == "user" and not out["prompt"]:
                    out["prompt"] = b["text"]
                elif role == "assistant" and not saw_tool and not intro_done:
                    out["intro"] = b["text"]
                    intro_done = True
                elif role == "assistant":
                    out["answer_md"] = b["text"]
            elif b.get("type") == "thinking":
                continue
            elif b.get("type") == "toolCall":
                saw_tool = True
                name = b.get("name", "")
                args = b.get("arguments") or {}
                if "codemode" in name and not out["script_src"]:
                    out["script_src"] = (
                        args.get("script") or args.get("code") or args.get("source") or ""
                    )
                    if not out["script_src"]:
                        WARN("codemode call found but no script argument; "
                             "script will be empty")
                else:
                    pending_calls[b.get("id")] = {
                        "name": name,
                        "args": args,
                        "call_ms": e.get("ms"),
                        "result_ms": None,
                        "error": False,
                    }
        if role == "toolResult":
            msg = e.get("message") or {}
            call = pending_calls.get(msg.get("toolCallId"))
            text = first_text(msg.get("content") or [])
            if call:
                call["result_ms"] = msg.get("timestamp")
                call["error"] = bool(msg.get("isError"))
            tool_results.append((msg.get("toolName"), text, bool(msg.get("isError"))))

    out["pending_calls"] = pending_calls
    out["tool_results"] = tool_results

    # output: the codemode result if there was one, else the last result
    for name, text, _err in reversed(tool_results):
        if name and "codemode" in name and text:
            out["output"] = text
            break
    if not out["output"] and tool_results:
        out["output"] = tool_results[-1][1]
    return out


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

def call_timings(pending_calls, speed):
    """Convert recorded calls to replay entries. `t` is rebased so the
    first call starts at 0; missing timestamps get plausible dummies."""
    calls, cursor = [], 0.0
    for call in pending_calls.values():
        c_ms, r_ms = call["call_ms"], call["result_ms"]
        if c_ms is None or r_ms is None or r_ms < c_ms:
            d, t = 1500.0, cursor
        else:
            d, t = max(1.0, r_ms - c_ms), float(c_ms)
        calls.append({
            "t": t / speed,
            "d": d / speed,
            "name": call["name"],
            "args": render_args(call["args"]),
        })
        cursor = t + d
    if calls:
        base = min(c["t"] for c in calls)
        for c in calls:
            c["t"] = round(c["t"] - base, 1)
            c["d"] = round(c["d"], 1)
        calls.sort(key=lambda c: c["t"])
    return calls


def render_args(args):
    if not isinstance(args, dict):
        args = {}
    parts = []
    for k, v in args.items():
        try:
            v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            v = str(v)
        parts.append("%s: %s" % (k, v))
    text = "{ " + ", ".join(parts) + " }" if parts else "{}"
    return text if len(text) <= 72 else text[:69] + "\u2026"


# --------------------------------------------------------------------------
# JS tokenizer for the script
# --------------------------------------------------------------------------

RE_WS = re.compile(r"\s+")
RE_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
RE_STRING = re.compile(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`", re.S)
RE_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
RE_IDENT = re.compile(r"[$_\w]+")
RE_PUNCT = re.compile(r"[^\s$_\w'\"`]+")  # quotes excluded: they may open a string


def tokenize_js(src):
    """Split JS source into [class, text] tokens for the replay player.
    Classes: k keyword, f function, s string, n number, c comment, p punct."""
    tokens = []
    pending_ws = ""
    i, n = 0, len(src)
    while i < n:
        m = RE_WS.match(src, i)
        if m:
            pending_ws += m.group(0)
            i = m.end()
            continue
        cls = ""
        for rx, c in ((RE_COMMENT, "c"), (RE_STRING, "s"), (RE_NUMBER, "n")):
            m = rx.match(src, i)
            if m:
                cls, text = c, m.group(0)
                i = m.end()
                break
        else:
            m = RE_IDENT.match(src, i)
            if m:
                text = m.group(0)
                i = m.end()
                if text in KEYWORDS:
                    cls = "k"
                else:
                    j = i + len(RE_WS.match(src, i).group(0)) if RE_WS.match(src, i) else i
                    cls = "f" if j < n and src[j] == "(" else ""
            else:
                m = RE_PUNCT.match(src, i)
                if not m:
                    i += 1  # defensive: skip a byte we cannot classify
                    continue
                cls, text = "p", m.group(0)
                i = m.end()
        tokens.append([cls, pending_ws + text])
        pending_ws = ""
    if pending_ws:
        tokens.append(["", pending_ws])
    return tokens


# --------------------------------------------------------------------------
# Minimal markdown -> answer blocks
# --------------------------------------------------------------------------

def inline_md(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)`([^`]+)`(?!\w)", r"<code>\1</code>", text)
    return text


def answer_blocks(markdown, max_blocks=4):
    """Very small converter: paragraphs and `- ` bullets. Curate by hand."""
    blocks, bullets, para = [], [], []

    def flush_para():
        if para:
            blocks.append(["p", inline_md(" ".join(para).strip())])
        para.clear()

    def flush_bullets():
        if bullets:
            blocks.append(["ul", [inline_md(b) for b in bullets]])
        bullets.clear()

    for line in markdown.strip().splitlines():
        s = line.strip()
        if not s:
            flush_para()
            flush_bullets()
        elif s.startswith("- "):
            flush_para()
            bullets.append(s[2:].strip())
        else:
            flush_bullets()
            para.append(s)
    flush_para()
    flush_bullets()
    if len(blocks) > max_blocks:
        WARN("answer had %d blocks; kept the first %d. Curate this by hand."
             % (len(blocks), max_blocks))
        blocks = blocks[:max_blocks]
    return blocks


# --------------------------------------------------------------------------
# Scaffold
# --------------------------------------------------------------------------

def prettify_cwd(cwd):
    if not cwd:
        return ""
    if cwd.startswith(os.path.expanduser("~")):
        return "~" + cwd[len(os.path.expanduser("~")):]
    return cwd


def build_replay(header, events, speed, max_calls):
    info = collect(header, events)
    if not info["prompt"]:
        WARN("no user prompt found; `prompt` left empty")
    if not info["script_src"]:
        WARN("no codemode script found; `script` left empty. If the session "
             "made plain tool calls they are listed in `calls` instead.")
    if not info["intro"]:
        info["intro"] = ""
        WARN("no assistant intro found")

    calls = call_timings(info["pending_calls"], speed)
    if len(calls) > max_calls:
        WARN("kept the first %d of %d calls; sample the rest by hand if the "
             "session had interesting later calls." % (max_calls, len(calls)))
        calls = calls[:max_calls]

    script = tokenize_js(info["script_src"]) if info["script_src"] else []
    wall = max((c["t"] + c["d"] for c in calls), default=0)
    replay = {
        "cwd": prettify_cwd(info["cwd"]),
        "model": info["model"],
        "prompt": info["prompt"].strip(),
        "intro": info["intro"].strip(),
        "script": script,
        "calls": [{k: c[k] for k in ("t", "d", "name", "args")} for c in calls],
        "wallMs": round(max(wall, 200), 1),
        "output": info["output"].strip(),
        "answer": answer_blocks(info["answer_md"]),
    }
    return replay


def find_latest():
    files = glob.glob(os.path.join(SESSIONS_DIR, "*", "*.jsonl"))
    if not files:
        sys.exit("no session files under %s" % SESSIONS_DIR)
    return max(files, key=os.path.getmtime)


def list_sessions(count):
    files = glob.glob(os.path.join(SESSIONS_DIR, "*", "*.jsonl"))
    files.sort(key=os.path.getmtime, reverse=True)
    for f in files[:count]:
        try:
            with open(f, encoding="utf-8") as fh:
                first = json.loads(fh.readline())
            cwd = first.get("cwd", "?")
            print("%s  %s" % (f, cwd))
        except (OSError, json.JSONDecodeError):
            print("%s  (unreadable)" % f)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(path):
    problems = []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    required = ["prompt", "intro", "script", "calls", "wallMs", "output", "answer"]
    for key in required:
        if key not in data:
            problems.append("missing key: %s" % key)

    if "prompt" not in data or not data.get("prompt"):
        problems.append("`prompt` is empty")

    script = data.get("script")
    if not isinstance(script, list):
        problems.append("`script` is not an array")
        script = []
    for i, tok in enumerate(script):
        if (not isinstance(tok, list) or len(tok) != 2
                or not isinstance(tok[1], str)
                or tok[0] not in ("", "k", "f", "s", "n", "c", "p")):
            problems.append("script token %d is malformed: %r" % (i, tok))
            break

    calls = data.get("calls")
    if not isinstance(calls, list):
        problems.append("`calls` is not an array")
        calls = []
    last_t = None
    for i, call in enumerate(calls):
        for key in ("t", "d", "name", "args"):
            if key not in call:
                problems.append("call %d misses %s" % (i, key))
        if last_t is not None and call.get("t", 0) < last_t:
            problems.append("calls not sorted by t at index %d" % i)
        last_t = call.get("t", 0)

    wall = data.get("wallMs", 0)
    peak = max((c.get("t", 0) + c.get("d", 0) for c in calls), default=0)
    if wall < peak:
        problems.append("wallMs (%s) < last call end (%s)" % (wall, peak))

    answer = data.get("answer")
    if not isinstance(answer, list):
        problems.append("`answer` is not an array")
        answer = []
    for i, block in enumerate(answer):
        if not (isinstance(block, list) and len(block) == 2
                and block[0] in ("p", "ul")):
            problems.append("answer block %d malformed: %r" % (i, block))
        elif block[0] == "p" and not isinstance(block[1], str):
            problems.append("answer block %d: paragraph is not a string" % i)
        elif block[0] == "ul" and not (
                isinstance(block[1], list)
                and all(isinstance(x, str) for x in block[1])):
            problems.append("answer block %d: list items are not strings" % i)

    if script and shutil.which("node"):
        js = "".join(tok[1] for tok in script if isinstance(tok, list) and len(tok) == 2)
        # codemode scripts are evaluated as an async function body: top-level
        # await and return are both legal there, so wrap before checking.
        js = "(async () => {\n" + js + "\n})"
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as tmp:
            tmp.write(js)
            tmpname = tmp.name
        try:
            r = subprocess.run(["node", "--check", tmpname],
                               capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("concatenated script is not valid JS:\n"
                                + r.stderr.strip()[:400])
        finally:
            os.unlink(tmpname)

    if problems:
        print("%s: %d problem(s)" % (path, len(problems)))
        for p in problems:
            print("  - " + p)
        return 1
    stats = {
        "script tokens": len(script),
        "script chars": sum(len(t[1]) for t in script),
        "calls": len(calls),
        "wallMs": wall,
        "answer blocks": len(answer),
    }
    print("OK  " + path + "  " + "  ".join("%s: %s" % kv for kv in stats.items()))
    return 0


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--session", help="path to a pi session .jsonl file")
    g.add_argument("--latest", action="store_true", help="use the newest session")
    g.add_argument("--list", nargs="?", type=int, const=10, metavar="N",
                   help="list recent sessions (default 10)")
    g.add_argument("--validate", metavar="FILE",
                   help="sanity-check a finished replay JSON")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="divide all timings by this (default 1)")
    ap.add_argument("--max-calls", type=int, default=40,
                    help="keep at most this many calls (default 40)")
    ap.add_argument("--out", help="write the replay JSON here")
    args = ap.parse_args()

    if args.validate:
        sys.exit(validate(args.validate))
    if args.list is not None:
        list_sessions(args.list)
        return
    if not (args.session or args.latest):
        ap.error("give --session FILE, --latest, --list or --validate FILE")
    path = args.session or find_latest()
    if not os.path.exists(path):
        sys.exit("file not found: " + path)

    header, events = load_session(path)
    replay = build_replay(header, events, max(args.speed, 0.001), args.max_calls)
    text = json.dumps(replay, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote " + args.out, file=sys.stderr)
    else:
        sys.stdout.write(text)

    print("\nThis is a SCAFFOLD. Before shipping, curate it (see AGENTS.md):",
          file=sys.stderr)
    print("  * shorten the intro to 1-2 sentences", file=sys.stderr)
    print("  * trim the script to the final logic that mattered", file=sys.stderr)
    print("  * pick representative calls; keep timings plausible", file=sys.stderr)
    print("  * rewrite the answer as 1-4 tight blocks", file=sys.stderr)
    print("  * validate: %s --validate <file>" % sys.argv[0], file=sys.stderr)


if __name__ == "__main__":
    main()
