---
title: Full codemode replay
---

The real thing: a condensed Pi codemode session that pulls issues from
Linear and has a classifier rate how frustrated the people writing them
sound. This replay data ships with the module (originally published with
[You Said No MCP!](https://earendil.com/posts/you-said-no-mcp/) on
earendil.com, Apache-2.0).

{{< pi-replay data="codemode-replay.json" caption="A condensed replay of a real Pi session.">}}
> Use typesafe/jev via codemode to find the most frustrated people on our issue tracker

I'll pull the open issues from Linear and let Jev rate the tone of each thread, four at a time.

codemode
const { issues } = await tools.mcp__linear__list_issues({
  team: "Pi", state: "open", limit: 250,
});
const jev = await models.getModelOfType(
  "classifier", "cloudflare-workers-ai", "typesafe/jev",
);
const questions = {
  frustration: {
    type: "choice",
    instructions: "Judge ONLY the emotional tone of the people writing. " +
      "Ignore how severe the bug is.",
    criteria: {
      none: "Neutral, factual, or friendly, even about a serious bug",
      mild: "Explicit annoyance, impatience, or disappointment",
      high: "Clearly angry, exasperated, sarcastic, or fed up",
    },
  },
};

const results = [];
let next = 0;
async function worker() {
  while (next < issues.length) {
    const issue = issues[next++];
    const { comments } = await tools.mcp__linear__list_comments({
      issueId: issue.identifier,
    });
    const c = await models.classify(jev, { state: { ...issue, comments }, questions });
    results.push({ id: issue.identifier, title: issue.title, ...c.answers.frustration });
  }
}
await Promise.all([worker(), worker(), worker(), worker()]);
store("frustration", results);

const score = (r) => r.probabilities.mild * 0.5 + r.probabilities.high;
const counts = {};
for (const r of results) counts[r.choice] = (counts[r.choice] ?? 0) + 1;
const flagged = results.filter((r) => r.choice !== "none");
flagged.sort((a, b) => score(b) - score(a));
return {
  total: results.length,
  counts,
  flagged: flagged.map((r) => `${r.id} ${r.title}`),
};

... (331 earlier calls)
✓ mcp__linear__list_comments {"issueId":"PI-4714"} 255ms
✓ mcp__linear__list_comments {"issueId":"PI-3200"} 354ms
✓ models.classify cloudflare-workers-ai/typesafe/jev 756ms
✓ models.classify cloudflare-workers-ai/typesafe/jev 750ms

{
  "total": 167,
  "counts": {
    "none": 156,
    "mild": 11
  },
  "flagged": [
    "PI-7740 TUI after /reload does not follows custom tool's re…",
    "PI-9566 context size defaults to 128k despite the real size…",
    "PI-10031 Pi sporadically stuck in \"Working...\" when thinking…",
    "PI-4714 [feature] /update TUI command instead of pi update",
    "PI-5916 Support provider extensions with model aliases and…",
    "PI-7547 [Windows] [sink-thread] How do you use Pi on window…",
    "PI-6907 Add an Installation section to the README",
    "PI-6212 Proposal: Bedrock path should honor `compat.forceAd…",
    "PI-9932 before_agent_start: forced system prompt keeps tool…",
    "PI-7730 High CPU usage on Mac OS with long session",
    "PI-6600 pi update --extensions and npm scripts: npm 11.16.0…"
  ]
}

Most of the tracker is calm. Jev rated 156 of the 167 open issues as neutral, 11
as mildly frustrated and none as highly frustrated.

The clearest cases:

- PI-6907 no installation section in the README (“It's frustrating”) - PI-10031
Pi gets stuck on “Working...” after pressing Esc during thinking - PI-4714 a
/update command request (“a pain in the butt”) - PI-7730 high CPU usage on macOS
in long sessions

The per-issue verdicts are stored in codemode under frustration, so I can dig
into any of them without fetching the issues again.
{{< /pi-replay >}}
