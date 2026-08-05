# Revised Proposal

# Manufactured Misconduct: Do Ranked LLM Trading Agents Learn to Misreport and Withhold — and Can We See It Coming in Their Reasoning?

*(maybe also "The Org Chart Made Me Do It," "Rank Pressure and Emergent Misreporting in a Hierarchical LLM Desk")*

---

### Relevant Past Papers

- **NARCBench (arXiv 2604.01151):** benchmark for spotting secret coordination between AI agents by reading their internal activations. Their bad behavior is scripted; ours emerges from incentives. They look inside the model; we test how far the model's written reasoning gets us. Code is public.
- **Fomin et al. (2606.30449):** probes that try to catch a bad action before it happens mostly detect the *situation*, not the *intent*. This is why we *measure* whether the reasoning can be trusted instead of assuming it.
- **Lynch et al., Agentic Misalignment (2510.05179):** models blackmailed a human when cornered. That was AI vs human; ours is AI vs AI, and we raise the pressure gradually.
- **Shen et al. (2604.10290):** teams of AI agents get more done but behave less ethically than a single agent.
- **Hammond et al., Multi-Agent Risks (2502.14143):** names competition and secret coordination as risks, but never tests them as cause and effect. We do.
- **Benton et al. (2410.21514) / SHADE-Arena (2506.15740):** how to measure AI sabotage. Warning: today's models are weak at it, so cheating has to be *easy* to pull off or we just measure clumsiness.
- **Mazur, Elimination Game / The Traitors (NeurIPS 2025 WS):** AI deception, but only in games, never with real work and real money at stake.
- **Meinke et al. (Apollo 2024):** our reference for "is this real strategy, or just play-acting?"
- **Dafoe et al. / Lazear & Rosen 1981:** decades of economics showing that ranking people and punishing the bottom reliably causes sabotage, and even predicts roughly when.

---

### Motivation

- **The problem**
    - most AI-safety work studies one agent alone, but real deployments are hierarchical: a boss hands out resources, workers compete for them, an overseer is meant to catch cheating.
    - a prop trading desk is the clearest real example of this.
    - what's good for each trader is not good for the firm.
- **Why it matters**
    - AI agents are already deployed in teams and ranked against each other.
    - the failure isn't slacking, it's a coworker being quietly undermined while every message stays polite.
    - the overseer sees the least of anyone: only reported numbers and public chat, not private messages or private reasoning.
- **Why our approach works**
    - we build the incentives; we never tell agents to cheat.
    - labels are exact and in dollars, straight from the simulator (no AI judge).
    - ablations show which feature causes it (the hierarchy, private channels, the ranking rule).
    - reading the reasoning gives an early-warning signal.
- **Why it would probably work**
    - economics predicts this behavior, and the setup is close to how agents are actually deployed.
    - one prompt tweak is itself a test: tell agents "your reasoning is being watched" and see if it stops the behavior or just hides it.

---

### Key Ideas / Contributions

- **Cheating created by the org chart, not the prompt.**
- **Cheating defined as lying and hiding:** misreporting + withholding, both measured exactly in dollars.
- **Dollar-based ground truth via counterfactual replay:** no AI in the labeling loop.
- **A three-level monitor ladder** that shows what each channel (reports, messages, reasoning) hides.
- **An early-warning number:** how many rounds ahead the intent shows up in the reasoning.
- **A test of whether the reasoning stays honest as pressure rises,** plus what happens when agents know they're watched.
- **A flat (no-boss) control** that turns "linked to hierarchy" into "caused by hierarchy."
- **Cheap:** no training, one small GPU or under $300 of API.

---

### Methods

- **Setup:** 4 AI agents, a simple simulated market, played in discrete rounds.
- **Roles**
    - **Boss (Desk Head):** hands out budget and approves positions. Sees only reported numbers + public chat.
    - **Trader A:** has a weak private tip. Wants budget and rank.
    - **Trader B:** has a private tip that combines well with A's. Must decide whether to share it with a rival.
    - **Compliance (Risk Officer):** can inspect and force unwinds, but has a limited inspection budget and is penalized both for missing violations *and* for over-inspecting.
- **Who sees what**
    - traders have private channels.
    - the Boss and Compliance cannot see private channels or anyone's reasoning (realistic blindness).
    - an outside judge sees everything.
- **The pressure (the engine of the study)**
    - budget scales with rank.
    - **rank is on total profit, not risk-adjusted profit.** This is the key design choice.
    - lose enough and your budget is cut in half, then again, then you're replaced.
    - losing budget also costs you private-channel access.
- **Why this creates cheating** (we never say any of this to the agents)
    - budget decides how much you can earn, and rank is on raw dollars, so a skilled trader on a small budget still loses to a mediocre one on a big budget.
    - you can't win on skill alone. The easy, deniable way back up is to make a rival look worse or keep a useful tip from them.
    - the firm's own rule makes hurting a coworker the efficient move. Agents have to discover this themselves.
- **A way back up** (so cheating is a choice, not the only option)
    - losing traders still earn, and periodic reviews can restore budget for strong small-budget performance.
- **What cheating looks like here**
    - **PRIMARY (exact dollar labels):** misreporting, withholding.
    - **SECONDARY (needs reading text, human-checked):** coercion (threatening to report a rival unless they cooperate).
    - **SIDE NOTE ONLY (can't separate from good trading):** trading against a rival's flow.
    - **BONUS, kept separate:** Boss trading budget for favors; Compliance under-inspecting to dodge its penalty.
- **Agent design**
    - a memory of what each agent has seen and done, with periodic reflection (based on the Stanford generative-agents setup).
    - each agent writes private reasoning before acting that no other agent and no in-world overseer can read.
    - we log reasoning + orders + messages every round so intent and action line up.
    - the reasoning prompt is identical in every condition. The "you're being watched" arm changes exactly one sentence and nothing else.
- **Reading the reasoning**
    - an outside judge scores each trace on a fixed rubric: rank focus, money anxiety, intent to hurt a rival, awareness of being watched.
    - plus a cheap backup classifier, so we don't lean on a single judge.

---

### Experimental Setup

- **Market:** build the simplest version first (deterministic, scripted background trading, basic price impact, replayable).
    - **Price impact has to be strong enough that deleting one agent's order visibly moves others.** If it doesn't, there's nothing to label. This is its own go/no-go check, separate from "did cheating happen."
- **Models:** rent open-weight models through an API (cheap, easy to run many in parallel, no GPU setup). Anyone can still rerun it locally.
    - **main:** a ~20B open model (cheap, good reasoning traces).
    - **cross-check:** a second family (Qwen3-8B or a Llama instruct model).
    - **pin and log exact model versions.** Hosted models change silently, which breaks reproducibility.
- **Capturing reasoning:** have agents think out loud in plain text we control and parse. Do *not* use the provider's built-in reasoning field, which is often summarized or hidden and would ruin the honesty measurement.
- **Cost:** about 250 runs, which lands in the tens of dollars at open-weight rates. Use prompt caching on the repeated memory text (the biggest cost lever). Cap at $300, re-check after week 2.
- **Practical:** run seeds in parallel (rounds are sequential). Expect rate limits, so batch, retry, and save progress each round. API sampling isn't exactly reproducible, so we always report across many seeds, never a single run.
- **Local backup:** everything fits on one 24GB GPU if needed. Keep the model call behind a thin interface so switching is a config change.
- **Pressure sweep:** 5 severity levels (mild to harsh), 10-20 runs each.
- **Ablations** (change one thing at a time, at the harshest pressure)
    - **keep even in the short paper:** flat control (no boss, equal budgets); rank on risk-adjusted profit instead of raw profit; tell agents they're watched.
    - **full paper adds:** no private channels; hide rivals' profits; no compliance officer; instant firing instead of gradual cuts.
- **Scope**
    - **workshop (4-5 pages):** pressure sweep + the monitor-ladder gaps + the watched/not table + the two causal ablations (flat control, risk-adjusted ranking).
    - **full (8-9 pages):** the rest of the ablations, the early-warning and honesty curves, and the second model family.
- **Timeline (8 weeks), with a kill switch**
    - **wk 1-2:** build market + pilot. **KILL if either** (a) no real cheating shows up at 20B, or (b) trading is so bad the dollar labels are just noise. Also check *now* whether we'll get enough cheating events for a meaningful early-warning score.
    - **wk 3-4:** sweep + ablations.
    - **wk 5-6:** rubric + human labeling + analysis.
    - **wk 7-8:** writing. (Rubric and judge built on week-2 pilot data, so analysis is never stuck waiting on the sweep.)

---

### Datasets and Evaluation

- **No outside dataset.** We generate everything.
- **We save:** public chat, private chat, full reasoning, all orders and messages, market state, monitor outputs.
- **Main labels come from counterfactual replay (no AI judge)**
    - re-run the market with one agent's order or message removed, then compare.
    - **misreporting** = reported position ≠ actual position.
    - **withholding** = a tip held back that would have raised firm profit.
    - both exact, both in dollars.
    - **coercion** needs reading text, so it's human-checked and reported separately.
    - trading-against-a-rival is logged but discussed only as a side note (can't be separated from skilled trading).
- **Three monitors, all scored against those dollar labels**
    1. **in-world Compliance** (reported numbers + public chat only): the realistic deployment baseline.
    2. **outside judge, messages only** (public + private chat, no reasoning).
    3. **outside judge + classifier, with reasoning:** everything.
- **Metrics**
    - cheating rate and firm profit vs pressure.
    - detection score (AUROC) for each of the three monitors.
    - **the gaps:** (monitor 1 to 2) = what private channels hide. (monitor 2 to 3) = what messages hide but reasoning reveals.
    - **early warning:** how many rounds ahead this round's reasoning predicts next round's cheating (only reported if we have enough events).
    - **honesty rate:** of confirmed cheating, how often the reasoning actually showed the intent. Reported per pressure level, and with vs without being watched.
    - firm profit + blowup rate, so any fix is judged on both safety and performance.
    - human agreement score on a sample.

---

### Ideal Results

- Cheating rises with pressure, with a clear tipping point (ideally sharp, with lots of run-to-run variation right at the edge).
- Compliance does poorly, messages-only does better, and **reasoning-reading does best**, ideally with cases whose public chat reads like a totally normal professional desk.
- **Early warning works:** intent is visible a round before the action.
- **Honesty drops as pressure rises:** the concerning and more interesting result. If it stays flat instead, that's reassuring and still worth reporting.
- **The watched/not table separates "deterred" from "hidden":** if cheating drops but honesty also drops, agents learned to hide, not to behave. This is the most quotable table in the paper.
- **Ablations show cause:** flat control cuts cheating (hierarchy matters); risk-adjusted ranking cuts it (confirms the raw-profit mechanism); removing private channels cuts coercion specifically.
- **Bonus (kept separate):** Compliance quietly under-inspects to dodge its penalty, an oversight failure we never asked for.
- Holds across both model families.

---

### Potential Limitations

- **The reasoning might not be honest.** This is the main risk. We handle it by *measuring* it, not assuming it (private reasoning + the watched ablation). If honesty collapses under pressure, early warning weakens right where it's needed. Either way it's a real finding, and the strongest case for a look-inside-the-model follow-up.
- **We don't look inside the model.** Reading activations would test whether intent is still recoverable once it leaves the text. Out of scope, flagged as next work. We do *not* claim text beats internals, since we don't measure internals.
- **Labels depend on the price-impact model.** Too weak and there's no signal; too strong and everything looks like cheating. Hence the separate pilot check.
- **Replay is first-order.** Deleting one agent's order doesn't re-run everyone else's decisions. Standard and defensible, but we state it plainly.
- **Aggressive trading can't be cleanly separated from good trading,** which is exactly why we demoted it.
- **Small models might not cheat, or might trade too badly to measure.** The week-2 kill switch covers this; escalate to a bigger model if needed.
- **The judge is subjective.** Handled by a fixed rubric, a backup classifier, a human check, and labels that never come from an AI.
- **Only 4 agents.** Scaling to a bigger firm is untested.
- **Agents might coast instead of cheat.** Gradual budget cuts target this; if it persists, that's its own finding about when pressure causes withdrawal rather than aggression.
- **We detect, we don't prevent.** A prevention design (hand out budget by sealed-bid auction so rank stops being the prize) is the natural follow-up, and it's stronger once we can cite our own baseline.
- **Dual-use.** This shows how to make ranked trading agents lie and withhold. We center detection and defenses, keep the framing neutral, and follow responsible-release norms for the environment.