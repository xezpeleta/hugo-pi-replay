---
title: Minimal replay
---

The smallest replay that still exercises the whole player: one prompt, a
short codemode script streamed into the editor, no nested tool calls, and a
two-block answer. The JSON is 60 lines — open
[`replay.json`](replay.json) and every field should map to something you
see animated here.

{{< pi-replay data="replay.json" caption="A minimal hand-authored replay; about 60 lines of JSON.">}}
> Use codemode to check whether the 10th Fibonacci number is even

I'll compute the sequence up to the 10th term and check its parity.

codemode
const fib = [0, 1];
while (fib.length < 10) {
  fib.push(fib.at(-1) + fib.at(-2));
}
const n = fib.at(-1);
return { n, even: n % 2 === 0 };

{
  "n": 34,
  "even": true
}

The 10th Fibonacci number is 34, and it is even — 34 % 2 === 0.

Fibonacci numbers are even exactly when their index is a multiple of three, so fib[9] was always going to be even.
{{< /pi-replay >}}

What you should see, in order: the terminal header (cwd, model), the prompt
typed out, the intro sentence, the script streaming into the editor with
syntax highlighting, the "tool calls" area staying closed (there are none),
the spinner running to `wallMs`, then the output and the answer blocks
fading in.
