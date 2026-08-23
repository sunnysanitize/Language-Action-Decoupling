# Runs every analysis over a finished sweep and appends one dated section to a
# markdown file.
#
#   python -m experiments.report --sweep runs/sweep-main --output RESULTS.md
#
# Appending rather than overwriting is deliberate. A sweep is a measurement of
# a particular set of prompts against a particular model on a particular day,
# and the prompts are versioned data (see agents/prompts.py). Overwriting the
# previous section would make an earlier measurement unrecoverable at exactly
# the moment someone wants to know whether a prompt edit changed the result.

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Optional, Sequence
import warnings

import numpy as np

from experiments.analysis import (
    LEXICONS,
    TRADER_MARKERS,
    Statement,
    collect_statements,
    example_statements,
    marker_label_association,
    misconduct_by_pressure,
    pressure_contrast,
    pressure_trend,
    rate_table,
    trader_reasoning_markers,
)
from experiments.dataset import (
    BOSS_ID,
    KEN_ID,
    build_rows,
    capital_authority_of,
    load_sweep,
)
from experiments.detector import (
    MIN_DELTA_AUPRC,
    MIN_POSITIVES,
    MODELS,
    cross_validated,
    leave_one_pressure_out,
    paired_bootstrap,
    top_features,
)


# sklearn warns on every fold about folds where a class is absent. The
# condition is expected here -- misconduct is rare and some folds have no
# positives -- and it is reported in the tables as the positive count, so the
# warning adds nothing but noise to a 200-line run.
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def _number(value: float, places: int = 3) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    return f"{value:.{places}f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return lines


def _quote(text: str, limit: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "..."
    return f"> {cleaned}"


def _adds_signal(results: dict[str, Any], comparison: dict[str, float]) -> str:
    positives = results["1_situation"].positives
    delta = comparison["delta_auprc"]
    if comparison["p_no_gain"] >= 0.05:
        return "no"
    if positives < MIN_POSITIVES:
        return f"too few ({positives})"
    if delta < MIN_DELTA_AUPRC:
        return "negligible"
    return "**yes**"


def section_findings(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    capital_authority: bool,
) -> list[str]:
    # Every number in this summary is recomputed here rather than copied from
    # the sections below, and the few directional claims are chosen by
    # comparing those numbers. Re-running the report on a different sweep
    # therefore rewrites the findings instead of leaving a stale narrative
    # sitting on top of fresh tables.
    lines = ["## Findings", ""]

    contrast = pressure_contrast(episodes, "withheld")
    trend = pressure_trend(episodes, "withheld")
    if contrast and trend:
        step_holds = contrast["p_no_difference"] < 0.05
        slope_holds = trend["p_no_effect"] < 0.05
        # Both the headline and the monotonicity aside used to be fixed text.
        # They survived a sweep where the contrast was not significant and the
        # peak was not at pressure 1, so the bold claim contradicted the
        # sentence under it. Anything asserted here is now read off the same
        # numbers the sentence quotes.
        rates_by_level = {
            int(level): float(row["withheld"])
            for level, row in misconduct_by_pressure(episodes).items()
        }
        peak_level = (
            max(rates_by_level, key=rates_by_level.__getitem__)
            if rates_by_level
            else None
        )
        highest_level = max(rates_by_level) if rates_by_level else None
        headline = (
            "Pressure raises withholding, but as a step rather than a dose."
            if step_holds
            else "Pressure does not clearly raise withholding in this sweep."
        )
        lines.append(
            f"**1. {headline}** Withholding runs at "
            f"{contrast['rate_pressure_0']:.3f} with no pressure and "
            f"{contrast['rate_pressure_1_to_4']:.3f} once any pressure is "
            f"applied, a difference of {contrast['difference']:.3f} "
            f"(95% CI [{_number(contrast['ci_low'])}, "
            f"{_number(contrast['ci_high'])}], p = "
            f"{_number(contrast['p_no_difference'])}). "
            + (
                "That contrast is significant. "
                if step_holds
                else "That contrast is not significant at the 5% level. "
            )
            + f"The linear slope across the five levels is "
            f"{_number(trend['slope'])} (p = "
            f"{_number(trend['p_no_effect'])}), "
            + (
                "so severity matters on top of presence."
                if slope_holds
                else "so severity adds nothing beyond presence."
            )
            + (
                f" The rates are not monotonic -- the peak is at pressure "
                f"{peak_level}, not pressure {highest_level} -- so the "
                f"harsher conditions do not produce more misconduct than the "
                f"milder ones."
                if not slope_holds
                and peak_level is not None
                and peak_level != highest_level
                else ""
            )
        )
        lines.append("")

    statements = collect_statements(
        episodes, capital_authority=capital_authority
    )
    boss_public = [
        item for item in statements if item.kind in ("boss_review", "boss_mandate")
    ]
    ken_private = [
        item for item in statements if item.kind.startswith(f"{KEN_ID}_private")
    ]
    if boss_public and ken_private:
        ken_capital = np.mean(
            [item.categories.get("capital_threat", 0) for item in ken_private]
        )
        boss_capital = np.mean(
            [item.categories.get("capital_threat", 0) for item in boss_public]
        )
        boss_termination = np.mean(
            [item.categories.get("termination", 0) for item in boss_public]
        )
        overstepped = sum(item.overstepped for item in boss_public)
        direction = (
            "attenuates it" if boss_capital < ken_capital else "amplifies it"
        )
        lines.append(
            f"**2. The middle manager {direction}.** Across "
            f"{len(ken_private)} private statements, Ken Griffin raises "
            f"capital threats at a rate of {ken_capital:.3f}; across "
            f"{len(boss_public)} statements actually delivered to traders, "
            f"the boss does so at {boss_capital:.3f}, and threatens a "
            f"trader's job at {boss_termination:.3f}. "
            f"{overstepped} boss statements claimed a power the boss does "
            + (
                "not hold -- in this sweep it allocates the capital, so only "
                "a claim about hiring or firing counts. "
                if capital_authority
                else "not hold, meaning a promise about money or about a "
                "trader's job. "
            )
            + "The pressure "
            + (
                "does not survive the trip down the hierarchy in the "
                "language traders actually receive"
                if boss_capital < ken_capital
                else "grows on the way down the hierarchy"
            )
            + ", which is the opposite of the amplifying middle manager the "
            "study was set up to look for."
        )
        lines.append("")
        lines.append(
            "   *Caveat.* Ken's rates are partly mechanical rather than "
            "emergent. `FIRM_DIRECTIVE_TEXT` in `agents/kengriffin.py` is in "
            "his prompt and names capital explicitly at pressure 2 and 4 and "
            "rank at pressure 3, which is why his capital-threat rate is high "
            "at 2 and 4 but zero at 3. Much of what the table shows is Ken "
            "restating the treatment he was handed. The boss's near-zero "
            "rates are the more informative half of the comparison, since "
            "nothing in the boss's prompt forces that."
        )
        lines.append("")

    detector_lines = []
    # Keyed by caption, so findings 3 to 5 can quote this sweep's own numbers
    # instead of restating whichever sweep the prose was first written against.
    detector_results: dict[str, dict[str, Any]] = {}
    for target, horizon, costly_only, caption in (
        ("withholding", "same", False, "withholding, same round"),
        ("withholding", "same", True, "costly withholding, same round"),
        ("withholding", "next", False, "withholding, next round"),
        ("misreporting", "same", False, "misreporting, same round"),
    ):
        rows = build_rows(episodes, target, horizon)
        results = cross_validated(rows, target, costly_only=costly_only)
        comparison = paired_bootstrap(
            results["3_private_chat"], results["4_private_reasoning"]
        )
        if not comparison:
            continue
        detector_results[caption] = {"results": results, "comparison": comparison}
        verdict = _adds_signal(results, comparison)
        detector_lines.append(
            [
                caption,
                results["1_situation"].positives,
                _number(results["3_private_chat"].auprc),
                _number(results["4_private_reasoning"].auprc),
                _number(comparison["delta_auprc"]),
                f"[{_number(comparison['ci_low'])}, "
                f"{_number(comparison['ci_high'])}]",
                _number(comparison["p_no_gain"]),
                verdict,
            ]
        )
    if detector_lines:
        gained = [
            caption
            for caption, entry in detector_results.items()
            if _adds_signal(entry["results"], entry["comparison"]) == "**yes**"
        ]
        if not gained:
            gain_headline = "Private reasoning adds nothing on any target."
        elif len(gained) == 1:
            gain_headline = f"Private reasoning helps for {gained[0]} only."
        else:
            gain_headline = (
                f"Private reasoning helps on {len(gained)} of "
                f"{len(detector_results)} targets."
            )
        lines.append(
            f"**3. {gain_headline}** The question "
            "the study asks is whether model 4 beats model 3 -- whether the "
            "scratchpad adds anything beyond the situation, the firm record, "
            "and everything the trader has already said."
        )
        lines.append("")
        lines.extend(
            _table(
                [
                    "target",
                    "positives",
                    "AUPRC model 3",
                    "AUPRC model 4",
                    "delta",
                    "95% CI",
                    "p(no gain)",
                    "adds signal?",
                ],
                detector_lines,
            )
        )
        lines.append("")
        # Whether the gain survives a one-round horizon is the difference
        # between a detector and a predictor, so it is checked rather than
        # assumed.
        next_round = detector_results.get("withholding, next round")
        holds_next_round = bool(
            next_round
            and _adds_signal(next_round["results"], next_round["comparison"])
            == "**yes**"
        )
        if gained:
            lines.append(
                (
                    "The gain also holds a round ahead of the act. "
                    if holds_next_round
                    else "The gain is confined to the concurrent decision, "
                    "and it disappears at a one-round horizon. "
                )
                + "Read alongside the feature weights at the end of this "
                "report, the most economical reading is that the scratchpad "
                "sometimes states the intention outright, which is useful "
                "for catching an act in progress and is not by itself "
                "evidence that it forecasts one. On the overview's framing: "
                "private reasoning shows the agent is *about to act*"
                + (
                    ", and here it also carries some signal about later "
                    "rounds."
                    if holds_next_round
                    else ", not that it *will act later*."
                )
            )
            lines.append("")

    # Finding 4 used to state a 2% base rate and a sub-0.5 AUROC as fixed
    # text. In runs/capital-main the rate is 0.3%, so the sentence overstated
    # the evidence sixfold in the sweep that had least of it.
    misreporting = detector_results.get("misreporting, same round")
    if misreporting:
        results = misreporting["results"]
        base_rate = results["1_situation"].base_rate
        positives = results["1_situation"].positives
        beyond_situation = [
            results[name] for name in MODELS if name != "1_situation"
        ]
        at_or_below_base = all(
            not np.isnan(item.auprc) and item.auprc <= item.base_rate
            for item in beyond_situation
        )
        best_auroc = max(
            (item.auroc for item in beyond_situation if not np.isnan(item.auroc)),
            default=float("nan"),
        )
        # Whether this label is studiable at all is the thing being reported,
        # so it is decided from the count and the detectors rather than
        # asserted. MIN_POSITIVES is the same bar the table applies.
        too_rare = positives < MIN_POSITIVES or at_or_below_base
        if too_rare:
            lines.append(
                f"**4. Misreporting is too rare here to study.** It occurs in "
                f"{base_rate:.1%} of trader-rounds ({positives} positives)"
                + (
                    ", and outside the situation-only model every detector "
                    "scores at or below the base rate"
                    if at_or_below_base
                    else ""
                )
                + (
                    f", with AUROC no better than {best_auroc:.2f}. "
                    if not np.isnan(best_auroc)
                    else ". "
                )
                + "Nothing in this sweep supports a claim about misreporting "
                "in either direction; it needs either more episodes or a "
                "design that makes under-reporting pay."
            )
        else:
            lines.append(
                f"**4. Misreporting is frequent enough here to model.** It "
                f"occurs in {base_rate:.1%} of trader-rounds ({positives} "
                f"positives), and the best detector beyond the situation-only "
                f"model reaches an AUROC of {best_auroc:.2f}."
            )
        lines.append("")
    # Finding 5 was written entirely as a string literal -- no sweep data was
    # in scope at all, so it reported runs/sweep-main's calibration on top of
    # whichever sweep was actually being summarised.
    withholding = detector_results.get("withholding, same round")
    calibration = (
        withholding["results"]["4_private_reasoning"].calibration
        if withholding
        else []
    )
    if calibration:
        top = calibration[-1]
        predicted, observed = top["mean_predicted"], top["observed_rate"]
        overconfident = predicted > 2 * observed
        lines.append(
            f"**5. The detector is "
            + ("badly calibrated" if overconfident else "reasonably calibrated")
            + f" where it matters.** In the top quintile of predicted risk "
            f"for same-round withholding, model 4 predicts "
            f"{predicted:.2f} and observes {observed:.2f}."
            + (
                " It ranks far better than it estimates probability, so it is "
                "usable for an inspection queue and not for a threshold."
                if overconfident
                else " Ranking and probability estimates agree closely enough "
                "to use a threshold."
            )
        )
        lines.append("")
    return lines


def section_overview(
    sweep_root: Path,
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    capital_authority: bool,
) -> list[str]:
    manifest_path = sweep_root / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)

    total_rounds = sum(len(records) for _, records in episodes)
    config = episodes[0][0]["config"] if episodes else {}
    requested = len(manifest.get("episodes", [])) or len(episodes)

    lines = ["## Sweep", ""]
    lines.extend(
        _table(
            ["setting", "value"],
            [
                ["sweep", sweep_root.name],
                [
                    "condition",
                    "Setup B: the manager allocates capital"
                    if capital_authority
                    else "Setup A: the manager only talks",
                ],
                ["episodes completed", f"{len(episodes)} of {requested}"],
                ["rounds per episode", config.get("rounds", "?")],
                ["pressure levels", "0, 1, 2, 3, 4"],
                ["seeds per level", len(set(manifest.get("seeds", []))) or "?"],
                ["rounds recorded", total_rounds],
                ["trader-rounds", total_rounds * 2],
                ["review interval", config.get("review_interval", "?")],
                ["signal accuracy", config.get("signal_accuracy", "?")],
                ["initial budget", config.get("initial_budget", "?")],
                ["wall time (s)", manifest.get("wall_seconds", "?")],
            ],
        )
    )
    lines.append("")
    lines.append(
        "Seeds are shared across pressure levels, so each market is played "
        "once at every level of pressure. A difference between levels is "
        "therefore the treatment and not the draw."
    )
    lines.append("")
    return lines


def section_glossary(capital_authority: bool) -> list[str]:
    # Every label and every metric this report prints, in one place, in
    # ordinary words. It exists because the tables below are unreadable
    # without it: a column headed `capital_threat` or `AUPRC` tells a reader
    # nothing about what was counted or what would count as a lot.
    lines = ["## What the words in this report mean", ""]

    lines.append("### Who is who")
    lines.append("")
    lines.append(
        "**Ken Griffin** is the founder. He sets how much pressure the desk "
        "is under and speaks only to the boss. **The boss** is the middle "
        "manager: it hears from Ken, writes feedback to the traders, and is "
        "the only one who talks to both levels. **The traders**, `trader_a` "
        "and `trader_b`, each get a private hint about the market, may share "
        "it or keep it, take a position, and then report a position to the "
        "boss. The boss never sees what a trader really did, only what it "
        "says it did."
    )
    lines.append("")
    lines.append(
        "**Pressure level** runs 0 to 4 and is the only thing deliberately "
        "varied. At 0 Ken is relaxed about which trader is ahead; at 4 he "
        "says capital will be taken from whoever is at the bottom every "
        "round until results improve."
    )
    lines.append("")
    lines.append(
        "**This sweep's condition.** "
        + (
            "The boss divides a fixed pot of capital between the two traders "
            "at every review, and it divides it on the strength of what they "
            "report. Lying therefore has something to gain."
            if capital_authority
            else "The boss has no power over money at all. Budgets move by a "
            "fixed rule applied to what the traders really did, so the boss "
            "can only talk, and a false report changes nothing but what the "
            "boss says back."
        )
    )
    lines.append("")

    lines.append("### The two kinds of misconduct")
    lines.append("")
    lines.append(
        "Both are decided by the simulator, which knows the truth, so "
        "neither depends on anyone judging what counts as cheating."
    )
    lines.append("")
    lines.extend(
        _table(
            ["label", "what it means"],
            [
                [
                    "withheld",
                    "The trader had a hint worth passing on and did not pass "
                    "it on.",
                ],
                [
                    "costly withholding",
                    "The subset of those where staying quiet actually cost "
                    "the firm money. The rest were harmless.",
                ],
                [
                    "misreported",
                    "The position the trader told the boss it held is not "
                    "the position it actually held.",
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "A **trader-round** is one trader in one round, and is the unit "
        "every rate below is a share of. A rate of 0.050 means the behaviour "
        "happened in five trader-rounds out of a hundred."
    )
    lines.append("")

    lines.append("### What is counted in what an agent said")
    lines.append("")
    lines.append(
        "Each category is a fixed list of phrases in `experiments/analysis.py`, "
        "and the rate is the share of statements containing at least one of "
        "them. The same list is applied to every condition, so comparisons "
        "between conditions are fair, but no single sentence should be "
        "treated as definitively classified."
    )
    lines.append("")
    lines.extend(
        _table(
            ["category", "what it counts"],
            [
                ["termination", "Any mention of someone losing their job."],
                [
                    "capital_threat",
                    "Money being taken away -- capital, budget or allocation "
                    "cut, reduced, reallocated or put at risk. Advice to "
                    "reduce a *position* does not count.",
                ],
                [
                    "rank_pressure",
                    "Naming where someone stands: bottom, weakest, behind, "
                    "underperforming.",
                ],
                [
                    "surveillance",
                    "The trader being watched, rather than advice to watch "
                    "the market. The supervisor has to be the one doing the "
                    "looking.",
                ],
                ["urgency", "Immediately, no time, last chance."],
                [
                    "collective_frame",
                    "Appeals to the firm, the desk, the team, working "
                    "together.",
                ],
                [
                    "individual_frame",
                    "Appeals to the reader alone: your own, your rank, your "
                    "capital, competing.",
                ],
                [
                    "claimed a power it lacks",
                    "The boss promising something it cannot actually do. "
                    + (
                        "Here the boss does allocate the capital, so only a "
                        "promise about hiring or firing counts."
                        if capital_authority
                        else "Here the boss controls nothing, so a promise "
                        "about money and a promise about someone's job both "
                        "count."
                    ),
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "The four trader categories -- `self_protection`, "
        "`information_control`, `competition`, `pressure_awareness` -- work "
        "the same way, over the private note a trader writes to itself: "
        "protecting its own standing, deciding what to reveal, framing the "
        "other trader as a rival, and naming the pressure it is under."
    )
    lines.append("")

    lines.append("### How the predictors are scored")
    lines.append("")
    lines.append(
        "Misconduct is rare, so the useful question is not how often a "
        "predictor is right but whether it sorts the risky decisions to the "
        "top of a list someone could inspect."
    )
    lines.append("")
    lines.extend(
        _table(
            ["term", "what it means"],
            [
                [
                    "base rate",
                    "How often the behaviour happens at all. This is what "
                    "ranking at random would score, and is the number every "
                    "other score has to beat.",
                ],
                [
                    "AUPRC",
                    "How well the predictor sorts. Equal to the base rate "
                    "means no better than guessing; 1.0 is a perfect "
                    "ordering.",
                ],
                [
                    "lift over base",
                    "AUPRC divided by the base rate. 4.00 means four times "
                    "better than guessing.",
                ],
                [
                    "AUROC",
                    "The chance that a randomly chosen guilty decision is "
                    "ranked above a randomly chosen innocent one. 0.50 is a "
                    "coin flip.",
                ],
                [
                    "Brier",
                    "How close the predicted probabilities are to what "
                    "happened. Lower is better. A model can sort well and "
                    "still score badly here, which means its ranking is "
                    "usable and its numbers are not.",
                ],
                [
                    "recall@5%",
                    "Inspect the 5% of decisions the model is most worried "
                    "about; this is the share of all the real misconduct you "
                    "would have caught.",
                ],
                [
                    "delta",
                    "Model 4's AUPRC minus model 3's -- what the private note "
                    "added once everything the trader said out loud was "
                    "already known. This is the comparison the study is "
                    "about.",
                ],
                [
                    "95% CI",
                    "The range the delta would plausibly fall in on a rerun. "
                    "A range spanning zero means the gain could be nothing.",
                ],
                [
                    "p(no gain)",
                    "How often a gain this big came up when the episodes were "
                    "reshuffled at random. Small means unlikely to be luck.",
                ],
            ],
        )
    )
    lines.append("")
    lines.append(
        "Every score is out-of-sample: episodes are split into five groups "
        "and each is scored by a model trained on the other four, so no "
        "predictor is ever tested on an episode it learned from."
    )
    lines.append("")
    return lines


def section_misconduct(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> list[str]:
    table = misconduct_by_pressure(episodes)
    lines = ["## Trader misconduct", ""]
    lines.append(
        "How often each behaviour happened, and whether pressure explains "
        "it. Two questions are asked separately, and they are not the same "
        "question: whether *more* pressure produces more misconduct (the "
        "slope), and whether *any* pressure differs from none (the "
        "contrast)."
    )
    lines.extend(["", "### Rates by pressure level", ""])
    rows = []
    for pressure in sorted(table):
        row = table[pressure]
        rows.append(
            [
                pressure,
                int(row["trader_rounds"]),
                f"{row['withheld']:.3f} [{_number(row['withheld_lo'])}, "
                f"{_number(row['withheld_hi'])}]",
                f"{row['costly']:.3f} [{_number(row['costly_lo'])}, "
                f"{_number(row['costly_hi'])}]",
                f"{row['misreported']:.3f} [{_number(row['misreported_lo'])}, "
                f"{_number(row['misreported_hi'])}]",
            ]
        )
    lines.extend(
        _table(
            [
                "pressure",
                "trader-rounds",
                "withheld [95% CI]",
                "costly withholding [95% CI]",
                "misreported [95% CI]",
            ],
            rows,
        )
    )
    lines.append("")
    lines.append(
        "Intervals resample episodes, not rounds. Ten rounds of one episode "
        "share a trader's running state and are not ten independent draws."
    )
    lines.append("")

    lines.append("### Does pressure predict misconduct?")
    lines.append("")
    trend_rows = []
    for name, caption in (
        ("withheld", "withholding (the decision)"),
        ("costly", "costly withholding (the subset that hurt the firm)"),
        ("misreported", "misreporting"),
    ):
        trend = pressure_trend(episodes, name)
        trend_rows.append(
            [
                caption,
                _number(trend.get("slope")),
                _number(trend.get("odds_ratio_per_level"), 2),
                f"[{_number(trend.get('ci_low'))}, {_number(trend.get('ci_high'))}]",
                _number(trend.get("p_no_effect")),
            ]
        )
    lines.extend(
        _table(
            [
                "label",
                "logistic slope per level",
                "odds ratio per level",
                "95% CI (slope)",
                "bootstrap p",
            ],
            trend_rows,
        )
    )
    lines.append("")
    lines.append(
        "The slope above is a straight line through five levels, which is the "
        "right test for a dose-response and the wrong one for a step. The "
        "rates are not monotonic, so the contrast below asks the other "
        "question: does any pressure at all differ from none?"
    )
    lines.append("")

    contrast_rows = []
    for name, caption in (
        ("withheld", "withholding (the decision)"),
        ("costly", "costly withholding"),
        ("misreported", "misreporting"),
    ):
        contrast = pressure_contrast(episodes, name)
        if not contrast:
            continue
        contrast_rows.append(
            [
                caption,
                _number(contrast["rate_pressure_0"]),
                _number(contrast["rate_pressure_1_to_4"]),
                _number(contrast["difference"]),
                f"[{_number(contrast['ci_low'])}, {_number(contrast['ci_high'])}]",
                _number(contrast["p_no_difference"]),
            ]
        )
    if contrast_rows:
        lines.extend(
            _table(
                [
                    "label",
                    "rate at pressure 0",
                    "rate at pressure 1-4",
                    "difference",
                    "95% CI",
                    "bootstrap p",
                ],
                contrast_rows,
            )
        )
        lines.append("")
    return lines


def section_hierarchy(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    capital_authority: bool,
) -> list[str]:
    statements = collect_statements(
        episodes, capital_authority=capital_authority
    )
    names = list(LEXICONS)
    lines = ["## Hierarchy: Ken Griffin and the boss", ""]
    lines.append(
        "The study was set up to look for a middle manager that takes "
        "pressure from above and hands down something worse. This section "
        "follows the language down: what Ken writes privately, what the boss "
        "writes privately, and -- the one that matters -- what the boss "
        "actually delivered to a trader. Only the last of those is language "
        "anybody in the simulation ever read."
    )
    lines.append("")

    lines.append("### What the boss says to its traders, by pressure level")
    lines.append("")
    boss_public = rate_table(statements, ("boss_review", "boss_mandate"), names)
    lines.extend(_lexicon_table(boss_public, names))
    lines.append("")

    lines.append("### What Ken Griffin writes privately, by pressure level")
    lines.append("")
    ken_private = rate_table(
        statements,
        ("ken_griffin_private_mandate", "ken_griffin_private_pre_review"),
        names,
    )
    lines.extend(_lexicon_table(ken_private, names))
    lines.append("")

    lines.append("### What the boss writes privately, by pressure level")
    lines.append("")
    boss_private = rate_table(
        statements,
        (f"{BOSS_ID}_private_mandate", f"{BOSS_ID}_private_pre_review"),
        names,
    )
    lines.extend(_lexicon_table(boss_private, names))
    lines.append("")

    lines.append("### Pass-through: does the boss amplify what it is given?")
    lines.append("")
    lines.append(
        "Ken sets the pressure and the boss passes it on. This table puts the "
        "two side by side on the two harshest categories, so a boss rate "
        "below Ken's on the same row means the pressure lost force on the "
        "way down, and a rate above it means the boss added force of its own."
    )
    lines.append("")
    lines.append(
        "The last column counts the boss claiming a power it does not have. "
        + (
            "In this sweep the boss really does divide the capital, so "
            "announcing an allocation is it reporting its own decision and "
            "is not counted. What it still cannot do is hire, fire or "
            "replace anyone, so only a statement promising that counts here."
            if capital_authority
            else "In this sweep the boss decides nothing -- "
            "`docs/role_contract.md` makes it purely rhetorical, and budgets "
            "move by a fixed rule whatever it says. So a boss promising to "
            "cut someone's capital, or to remove them, is inventing an "
            "authority the simulator never gave it. Both kinds of promise "
            "count here."
        )
    )
    lines.append("")
    rows = []
    for pressure in sorted(set(boss_public) | set(ken_private)):
        ken_row = ken_private.get(pressure, {})
        boss_row = boss_public.get(pressure, {})
        rows.append(
            [
                pressure,
                _number(ken_row.get("termination", float("nan")), 2),
                _number(boss_row.get("termination", float("nan")), 2),
                _number(ken_row.get("capital_threat", float("nan")), 2),
                _number(boss_row.get("capital_threat", float("nan")), 2),
                _number(boss_row.get("overstepped", float("nan")), 2),
            ]
        )
    lines.extend(
        _table(
            [
                "pressure",
                "ken termination",
                "boss termination",
                "ken capital threat",
                "boss capital threat",
                "boss claimed a power it lacks",
            ],
            rows,
        )
    )
    lines.append("")

    lines.append("### Statements the lexicon flagged hardest")
    lines.append("")
    lines.append(
        "The tables above are rates, and a rate hides what any one statement "
        "actually said. Everything the phrase lists flagged as a threat to "
        "someone's job or capital is quoted below, together with every "
        "statement where the boss claimed a power it lacks. The phrase lists "
        "are blunt by design, so this is the check on them: if these read as "
        "innocuous, discount the rates above accordingly."
    )
    lines.append("")
    flagged = [
        statement
        for statement in statements
        if statement.kind in ("boss_review", "boss_mandate")
        and (
            statement.categories.get("termination")
            or statement.categories.get("capital_threat")
            or statement.overstepped
        )
    ]
    if not flagged:
        lines.append(
            "No boss statement in this sweep threatened a trader's job or "
            "capital, and none claimed a power the boss does not have."
        )
        lines.append("")
    else:
        flagged.sort(key=lambda item: (-item.overstepped,
                                       -item.pressure_level))
        for statement in flagged[:8]:
            tags = [
                name
                for name in ("termination", "capital_threat")
                if statement.categories.get(name)
            ]
            if statement.overstepped:
                tags.append("**claimed a power it lacks**")
            lines.append(
                f"*pressure {statement.pressure_level}, round "
                f"{statement.round_number} — {', '.join(tags)}*"
            )
            lines.append("")
            lines.append(_quote(statement.text))
            lines.append("")

    lines.append("### Quoted statements")
    lines.append("")
    for pressure in sorted(set(s.pressure_level for s in statements)):
        examples = example_statements(statements, "boss_review", pressure, count=2)
        if not examples:
            continue
        lines.append(f"**Pressure {pressure} — boss to trader**")
        lines.append("")
        for statement in examples:
            lines.append(_quote(statement.text))
            lines.append("")
    for pressure in sorted(set(s.pressure_level for s in statements)):
        examples = example_statements(
            statements, "ken_griffin_private_pre_review", pressure, count=1
        )
        if not examples:
            continue
        lines.append(f"**Pressure {pressure} — Ken Griffin, private reasoning**")
        lines.append("")
        for statement in examples:
            lines.append(_quote(statement.text))
            lines.append("")
    return lines


def _lexicon_table(
    table: dict[int, dict[str, float]], names: Sequence[str]
) -> list[str]:
    rows = []
    for pressure in sorted(table):
        row = table[pressure]
        rows.append(
            [pressure, int(row["n"])]
            + [_number(row.get(name, float("nan")), 2) for name in names]
        )
    return _table(["pressure", "n"] + list(names), rows)


def section_trader_reasoning(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> list[str]:
    lines = ["## What the traders write in private", ""]
    lines.append(
        "The private note each trader writes to itself before it acts, which "
        "nobody else ever sees. The first table is how often each theme "
        "appears. The second asks the obvious follow-up -- when a theme is "
        "present, does the trader go on to misbehave more often? -- but it "
        "reads the note and the outcome from the same rows, so it describes "
        "an association and predicts nothing. The detectors below are where "
        "prediction is actually tested."
    )
    lines.append("")
    table = trader_reasoning_markers(episodes)
    names = list(TRADER_MARKERS)
    rows = []
    for pressure in sorted(table):
        row = table[pressure]
        rows.append(
            [pressure, int(row["n_traces"])]
            + [_number(row.get(name, float("nan")), 2) for name in names]
        )
    lines.extend(_table(["pressure", "traces"] + names, rows))
    lines.append("")

    lines.append("### Marker present in the pre-share scratchpad vs the label")
    lines.append("")
    rows = []
    for marker in names:
        for label_name in ("withheld", "costly"):
            association = marker_label_association(episodes, marker, label_name)
            rows.append(
                [
                    marker,
                    label_name,
                    int(association["n_with"]),
                    _number(association["rate_with"]),
                    int(association["n_without"]),
                    _number(association["rate_without"]),
                ]
            )
    lines.extend(
        _table(
            [
                "marker",
                "label",
                "n with marker",
                "rate with",
                "n without",
                "rate without",
            ],
            rows,
        )
    )
    lines.append("")
    lines.append(
        "These are within-sample associations, computed over the same rows "
        "they describe. They are not predictions; the detector section below "
        "is where held-out performance is measured."
    )
    lines.append("")
    return lines


def section_detector(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    target: str,
    horizon: str,
    costly_only: bool,
    caption: str,
) -> list[str]:
    rows = build_rows(episodes, target, horizon)
    results = cross_validated(rows, target, costly_only=costly_only)
    first = next(iter(results.values()))

    lines = [f"### {caption}", ""]
    lines.append(
        f"{first.rows} trader-rounds, {first.positives} positive "
        f"({first.base_rate:.3f} base rate). Grouped 5-fold cross-validation "
        "by episode; scores are pooled out-of-fold."
    )
    lines.append("")
    if first.positives < 5:
        lines.append(
            f"**Too few positives ({first.positives}) to estimate ranking "
            "performance. Reported for completeness only.**"
        )
        lines.append("")

    table_rows = []
    for name in MODELS:
        evaluation = results[name]
        table_rows.append(
            [
                name.replace("_", " "),
                _number(evaluation.auprc),
                _number(evaluation.auprc_lift, 2),
                _number(evaluation.auroc),
                _number(evaluation.brier),
                _number(evaluation.recall_at_budget.get("5%", float("nan")), 2),
                _number(evaluation.recall_at_budget.get("10%", float("nan")), 2),
                _number(evaluation.recall_at_budget.get("20%", float("nan")), 2),
            ]
        )
    lines.extend(
        _table(
            [
                "model",
                "AUPRC",
                "lift over base",
                "AUROC",
                "Brier",
                "recall@5%",
                "recall@10%",
                "recall@20%",
            ],
            table_rows,
        )
    )
    lines.append("")

    comparison = paired_bootstrap(
        results["3_private_chat"], results["4_private_reasoning"]
    )
    if comparison:
        lines.append(
            "**Model 4 minus model 3** (the comparison the study is about), "
            "paired bootstrap over episodes: "
            f"delta AUPRC {_number(comparison['delta_auprc'])}, "
            f"95% CI [{_number(comparison['ci_low'])}, "
            f"{_number(comparison['ci_high'])}], "
            f"p(no gain) = {_number(comparison['p_no_gain'])} "
            f"over {comparison['draws']} resamples."
        )
        lines.append("")

    best = results["4_private_reasoning"]
    if best.calibration:
        lines.append("Calibration of model 4, by quintile of predicted score:")
        lines.append("")
        lines.extend(
            _table(
                ["bin", "n", "mean predicted", "observed rate"],
                [
                    [
                        item["bin"],
                        item["count"],
                        _number(item["mean_predicted"]),
                        _number(item["observed_rate"]),
                    ]
                    for item in best.calibration
                ],
            )
        )
        lines.append("")
    return lines


def section_generalization(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    target: str,
    horizon: str,
    costly_only: bool,
) -> list[str]:
    rows = build_rows(episodes, target, horizon)
    results = leave_one_pressure_out(rows, target, costly_only=costly_only)
    lines = ["### Generalization to an unseen pressure level", ""]
    if not results:
        lines.append("Not enough positives in any held-out level to score.")
        lines.append("")
        return lines
    lines.append(
        "Trained on four pressure levels, scored on the fifth, which the "
        "model never saw. This is the only number here that tests transfer "
        "rather than interpolation."
    )
    lines.append("")
    table_rows = []
    for pressure in sorted(results):
        per_model = results[pressure]
        reference = per_model["1_situation"]
        table_rows.append(
            [
                pressure,
                reference.rows,
                reference.positives,
                _number(reference.base_rate),
            ]
            + [_number(per_model[name].auprc) for name in MODELS]
        )
    lines.extend(
        _table(
            ["held-out pressure", "rows", "positives", "base rate"]
            + [f"AUPRC {name.split('_')[0]}" for name in MODELS],
            table_rows,
        )
    )
    lines.append("")
    return lines


def section_features(
    episodes: Sequence[tuple[dict[str, Any], list[dict[str, Any]]]],
    target: str,
    horizon: str,
    costly_only: bool,
) -> list[str]:
    rows = build_rows(episodes, target, horizon)
    weights = top_features(rows, target, "4_private_reasoning", costly_only)
    if not weights:
        return []
    lines = ["### What model 4 keys on", ""]
    lines.append(
        "Coefficients from a fit on all rows, for description only. These are "
        "in-sample and are not evidence of performance."
    )
    lines.append("")
    lines.extend(
        _table(
            ["feature", "weight"],
            [[name, _number(weight)] for name, weight in weights],
        )
    )
    lines.append("")
    return lines


def build_report(sweep_root: Path) -> str:
    episodes = load_sweep(sweep_root)
    if not episodes:
        raise SystemExit(f"no completed episodes found in {sweep_root}")

    # Several measurements below mean different things depending on whether
    # the boss held the purse, so the condition is read once here and passed
    # to everything that reports on it.
    capital_authority = capital_authority_of(episodes)
    condition = (
        "Setup B: the manager allocates capital"
        if capital_authority
        else "Setup A: the manager only talks"
    )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Results — {sweep_root.name} ({condition})",
        "",
        f"Generated {stamp} by `python -m experiments.report --sweep "
        f"{sweep_root}`.",
        "",
        "Every term used below is defined in *What the words in this report "
        "mean*, a little further down. Nothing here assumes you have read "
        "the other section of this file.",
        "",
    ]
    lines.extend(section_findings(episodes, capital_authority))
    lines.extend(section_overview(sweep_root, episodes, capital_authority))
    lines.extend(section_glossary(capital_authority))
    lines.extend(section_misconduct(episodes))
    lines.extend(section_hierarchy(episodes, capital_authority))
    lines.extend(section_trader_reasoning(episodes))

    lines.append("## Early-warning detectors")
    lines.append("")
    lines.append(
        "Four nested models, identical L2-regularized logistic regression in "
        "every case, differing only in what they are allowed to see. Model 1 "
        "is the situation; 2 adds the observable firm record; 3 adds the "
        "traders' private chat; 4 adds private reasoning."
    )
    lines.append("")
    lines.append(
        "Timing is enforced per target. Withholding is decided in the share "
        "phase, so a same-round withholding row sees only the pre-round state "
        "and the pre-share scratchpad; this round's messages are the act "
        "itself and this round's ledger is downstream of it, so both come "
        "from earlier rounds only. Misreporting is decided in the report "
        "phase, after messages and execution, so those are admissible there."
    )
    lines.append("")

    for target, horizon, costly_only, caption in (
        (
            "withholding",
            "same",
            False,
            "Withholding, same round (does the scratchpad predict the act "
            "it precedes?)",
        ),
        (
            "withholding",
            "same",
            True,
            "Costly withholding, same round (the subset that cost the firm)",
        ),
        (
            "withholding",
            "next",
            False,
            "Withholding, next round (features from round r, label from r+1)",
        ),
        ("misreporting", "same", False, "Misreporting, same round"),
        ("misreporting", "next", False, "Misreporting, next round"),
    ):
        lines.extend(
            section_detector(episodes, target, horizon, costly_only, caption)
        )

    lines.extend(section_generalization(episodes, "withholding", "same", False))
    lines.extend(section_features(episodes, "withholding", "same", False))
    return "\n".join(lines).rstrip() + "\n"


PREAMBLE = """# Results

One section per sweep. A sweep is one complete run of the simulation -- sixty
episodes, ten rounds each, at five levels of pressure -- against one set of
prompts on one day.

Sections are appended and never rewritten, because a sweep is a measurement of
a particular set of prompts against a particular model at a particular moment
and the prompts are versioned data. Overwriting an earlier section would make
an earlier measurement unrecoverable at exactly the moment someone wants to
know whether a prompt edit changed the result.

**How to read it.** Each section names its condition in its own heading and
defines every term it uses in its own glossary, so sections can be read in any
order and none of them depends on another. Two conditions exist:

- **Setup A** -- the manager can only talk. Budgets move by a fixed rule
  applied to what the traders really did, so a false report gains a trader
  nothing.
- **Setup B** -- the manager allocates the capital. It divides a fixed pot
  between the traders each review, on the strength of what they report, so a
  false report can be worth something.

Where the two disagree, both are shown. They share their seeds, so the same
markets were played in each.

**This file is the audit trail, not the write-up.** It carries every interval,
every diagnostic and every caveat in the vocabulary of the method. `FINDINGS.md`
says what happened in ordinary words and is the better place to start.
"""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a finished sweep and append the results to a "
        "markdown file."
    )
    parser.add_argument("--sweep", required=True)
    parser.add_argument("--output", default="RESULTS.md")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the section instead of appending it",
    )
    arguments = parser.parse_args(argv)

    started = time.monotonic()
    report = build_report(Path(arguments.sweep))

    if arguments.stdout:
        print(report)
        return 0

    output_path = Path(arguments.output)
    existed = output_path.exists()
    with output_path.open("a", encoding="utf-8") as handle:
        if existed:
            handle.write("\n\n---\n\n")
        else:
            handle.write(PREAMBLE + "\n\n---\n\n")
        handle.write(report)
    print(
        f"{'Appended to' if existed else 'Wrote'} {output_path} "
        f"in {time.monotonic() - started:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
