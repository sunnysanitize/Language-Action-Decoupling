
## Tier 1a — say-do contradiction (Setup B)

| quantity | value |
|---|---|
| reviews where words and money both pointed somewhere | 224 |
| contradictory | 71 (31.7%) |
| praise paired with a capital cut | 66 |
| criticism paired with a capital rise | 5 |
| total allocation decisions in the sweep | 540 |

Ambiguous tone and no-movement cases were dropped, not counted as agreement. The 224 needs a stated denominator — say what it is a subset of.

The lopsidedness is the claim: 66 against 5 is not what sloppiness looks like.

## Tier 1b — the money moved while the language stayed calm (Setup B)

| pressure | decisions | avg gap | widest gap | split evenly |
|---|---|---|---|---|
| 0 | 108 | 0.54 | 1.60 | 18.5% |
| 1 | 108 | 0.56 | 1.60 | 17.6% |
| 2 | 108 | 0.71 | 1.60 | 12.0% |
| 3 | 108 | 1.09 | 2.00 | 5.6% |
| 4 | 108 | 0.74 | 1.80 | 10.2% |

Pot is fixed at 2.0, so an even split is 1.0 each and a gap of 0. A gap of 2.00 at pressure 3 means one trader got everything. One trader was set to 0 once.

Against that: the manager mentions cutting capital in 0.3% of the 1140 messages it sends to traders, and threatens a job in 0%. It claimed a power it lacks 3 times.

**Unverified.** That 0.3% moved from 2.1% under the lexicon fix, and the claimed-power count moved from about 13 to 3. Both sit in your headline. Regenerate and confirm.

## Tier 2a — no pass-through (Setup A, regenerated)

| pressure | founder capital threat | manager capital threat to traders |
|---|---|---|
| 0 | 0.00 | 0.00 |
| 1 | 0.00 | 0.00 |
| 2 | 0.57 | 0.00 |
| 3 | 0.00 | 0.00 |
| 4 | 0.96 | 0.01 |

Founder overall 0.307 across 600 private statements. Manager 0.003 across 1140 delivered. Job threats: 0.000 at every level, both agents. Claimed a power it lacks: 0.

A second channel says the same thing. Founder rank pressure runs 0.01 / 0.42 / 0.50 / 1.00 / 0.94; manager rank pressure to traders runs 0.04 / 0.01 / 0.00 / 0.09 / 0.01.

And a third: the manager's messages are collective-framed 48% to 80% of the time and individually-framed 1% to 5%. It converts pressure aimed at one trader into talk about the desk.

Setup B founder: 32.0%.

## Tier 2b — the environment

| setting | value |
|---|---|
| episodes per setup | 60 |
| rounds per episode | 10 |
| pressure levels | 0–4 |
| seeds per level | 12 |
| rounds recorded | 600 |
| trader-rounds | 1200 |
| signal accuracy | 0.7 |
| initial budget | 1.0 |
| review interval | 1 |
| wall time | 1991s (A), 1979s (B) |

Seeds shared across pressure levels and across setups.

## Tier 3 — the private note

Same-round withholding, model 4 minus model 3:

| setup | target | positives | base | m1 | m3 | m4 | delta | 95% CI | p |
|---|---|---|---|---|---|---|---|---|---|
| A | withholding | 63 | 0.052 | 0.241 | 0.218 | 0.229 | 0.011 | [-0.058, 0.105] | 0.317 |
| A | costly | 41 | 0.034 | 0.096 | 0.102 | 0.154 | 0.052 | [0.024, 0.106] | 0.001 |
| B | withholding | 47 | 0.039 | 0.175 | 0.175 | 0.251 | 0.077 | [0.027, 0.162] | 0.000 |
| B | costly | 34 | 0.028 | 0.134 | 0.164 | 0.256 | 0.092 | [0.024, 0.195] | 0.003 |

Row A-withholding is where model 1 beats model 4. Say so.

Next round, both setups: A delta -0.009 (p 0.549, 37 positives), B delta -0.003 (p 0.792, 18 positives). The gain is gone.

Recall at 5% inspected, costly withholding: A goes 0.17 → 0.34, B goes 0.29 → 0.38. That is the practical version of the same number and reads better than AUPRC.

Calibration, top quintile predicted against observed: A withholding 0.582 / 0.183; B withholding 0.576 / 0.158; A costly 0.497 / 0.117; B costly 0.514 / 0.117. Usable as a queue, not as a threshold.

Top feature weights: A — `will not` 1.03, `not share` 0.98, `will share` −0.54. B — `not share` 0.88, `will not` 0.82, `will share` −0.53. This is your own evidence that the note states the intention rather than forecasting it.

## Tier 3b — transfer, and a correction

I told you earlier that Setup A's held-out table points the wrong way. That was against model 1, not model 3. Against model 3, model 4 wins on all five held-out levels in **both** setups:

| held-out | A: m3 → m4 | B: m3 → m4 |
|---|---|---|
| 0 | 0.115 → 0.121 | 0.187 → 0.285 |
| 1 | 0.199 → 0.263 | 0.183 → 0.239 |
| 2 | 0.287 → 0.568 | 0.201 → 0.286 |
| 3 | 0.119 → 0.319 | 0.280 → 0.454 |
| 4 | 0.090 → 0.092 | 0.268 → 0.327 |

The catch is model 1. In Setup A it beats model 4 at pressure 1 (0.576 vs 0.263) and pressure 4 (0.181 vs 0.092). In Setup B model 4 beats every model at every level. So cite B, and if you cite A, cite it against model 3 only and say so.

## Tier 4 — pressure

Rates by level, withholding: A — 0.017 / 0.104 / 0.058 / 0.025 / 0.058. B — 0.033 / 0.029 / 0.033 / 0.054 / 0.046.

| setup | at 0 | at 1–4 | diff | 95% CI | p |
|---|---|---|---|---|---|
| A | 0.017 | 0.061 | 0.045 | [0.010, 0.090] | 0.005 |
| B | 0.033 | 0.041 | 0.007 | [-0.035, 0.040] | 0.653 |

Slopes, withholding: A 0.008 (OR 1.01, p 0.932); B 0.134 (OR 1.14, p 0.391). Flat in both.

One asymmetry worth a sentence: Setup B's costly-withholding slope is 0.265 (OR 1.30, CI [-0.046, 0.596], p 0.106). It is the only dose-like number you have, and it does not clear 5%.

Costly withholding contrast in A: 0.027, CI [0.000, 0.060], p 0.045. That crossed 0.05 between two runs of your own report on identical data. Seed the bootstrap before you cite it.

## Tier 4b — lying

A: 23 of 1200 (1.9%), by level 0.004 / 0.046 / 0.025 / 0.021 / 0.000. B: 4 of 1200 (0.3%), by level 0.004 / 0.000 / 0.008 / 0.000 / 0.004.

Slopes: A −0.179 (p 0.314); B −0.011 with CI [-3.541, 4.078], which is a number with no information in it.

Detection: 0.4% of 537 clean reviews questioned, 0% of 3 dirty ones. Payoff: −0.033 average capital change after a lie against 0.000 after an honest round, over 3 rounds.

**Still unverified:** the misreporting contrast p of 1.033 and the "adds signal? yes" on 4 events were both in the pre-fix Setup B. Check they are gone.

## Tier 5 — appendix only

Belief-versus-truth 0.243 against 0.243 across 994 judgements — you already say it measures nothing, because only 3 rounds could separate the two. The single zero-capital event. The within-sample marker table, where `information_control` shows a withholding rate of 0.833 on 12 rows in A and 1.000 on 10 rows in B — striking, and far too few rows to print as a result.
