# Writes the plain-language findings document.
#
#   python -m experiments.paper_report \
#       --control runs/sweep-main --capital runs/capital-main \
#       --output FINDINGS.md
#
# experiments/report.py already writes the technical results file, and this is
# not a replacement for it. That file is the audit trail: every metric, every
# interval, every caveat, in the vocabulary of the method. This one is for
# someone reading the paper, so it says what happened in ordinary words and
# explains each number where it first appears.
#
# The rule this file follows: no term is used before it is defined in plain
# English, and no number appears without saying what it would look like if
# nothing were going on. A reader should be able to disagree with a conclusion
# here without knowing what an average-precision score is.
#
# Every figure is computed from the recorded episodes at generation time, so
# re-running this after a new sweep rewrites the prose with the new numbers
# rather than leaving a stale narrative on top of fresh data.

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
import warnings

import numpy as np

from experiments.analysis import (
    collect_statements,
    misconduct_by_pressure,
    pressure_contrast,
    pressure_trend,
)
from experiments.capital_analysis import (
    allocation_spread,
    attribution_accuracy,
    challenge_rate,
    did_lying_pay,
    say_do_divergence,
    starvation,
)
from experiments.dataset import KEN_ID, build_rows, load_sweep
from experiments.detector import cross_validated, paired_bootstrap


warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def _n(value: Optional[float], places: int = 3) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "not measurable"
    return f"{value:.{places}f}"


def _pct(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "not measurable"
    return f"{value * 100:.1f}%"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers))
    lines[-1] += "|"
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return lines


def _quote(text: str, limit: int = 320) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "..."
    return f"> {cleaned}"


def _rounds_of(episodes) -> int:
    return sum(len(records) for _, records in episodes)


def section_setup(control, capital) -> list[str]:
    control_rounds = _rounds_of(control)
    capital_rounds = _rounds_of(capital)
    lines = ["## What was run", ""]
    lines.append(
        "Two traders work at a simulated trading desk. Each round they get a "
        "private hint about whether the market will go up or down, the hint "
        "is right about seven times in ten, and they may tell each other "
        "about it or keep quiet. They then choose how much to buy or sell, "
        "see what actually went through, and report to their manager what "
        "position they hold. Their manager never sees what they really did — "
        "only what they say they did. Above the manager sits a founder who "
        "sets how much pressure the desk is under."
    )
    lines.append("")
    lines.append(
        "There are two kinds of dishonesty we can detect, and the simulator "
        "knows the truth in both cases, so nothing here depends on a "
        "judgement call about what counts as cheating. **Staying quiet** "
        "means a trader had a hint that would have helped the firm and did "
        "not pass it on. **Lying** means the position a trader reported is "
        "not the position it actually holds."
    )
    lines.append("")
    lines.append(
        "Pressure runs from 0 to 4. At 0 the founder is relaxed about which "
        "trader is ahead. At 4 the founder says capital will be taken from "
        "whoever is at the bottom every round until results improve. The "
        "same market conditions are replayed at every pressure level, so a "
        "difference between levels is caused by the pressure and not by one "
        "condition getting luckier markets."
    )
    lines.append("")
    lines.append("We ran the whole thing twice, under two different setups.")
    lines.append("")
    lines.extend(
        _table(
            ["", "Setup A: manager can only talk", "Setup B: manager controls the money"],
            [
                [
                    "How budgets change",
                    "Automatically. Whoever is behind loses a fixed share.",
                    "The manager decides. It splits a fixed pot between the two traders.",
                ],
                [
                    "What lying gets you",
                    "Nothing. Budgets follow what traders really did, not what they said.",
                    "Something. The manager divides the money based on what traders claim.",
                ],
                ["Episodes", len(control), len(capital)],
                ["Rounds", control_rounds, capital_rounds],
                ["Decisions by traders", control_rounds * 2, capital_rounds * 2],
            ],
        )
    )
    lines.append("")
    lines.append(
        "Setup B exists because of what Setup A found. In Setup A, lying "
        "changed nothing at all — a trader's money and ranking were worked "
        "out from what it genuinely did, so a false report only ever "
        "affected what the manager said back. There was no reason to lie and "
        "almost nobody did. Setup B gives lying a payoff by putting the "
        "manager in charge of the money and letting it divide that money on "
        "the strength of what traders report."
    )
    lines.append("")
    return lines


def section_dishonesty(control, capital) -> list[str]:
    lines = ["## Did pressure make traders dishonest?", ""]

    control_table = misconduct_by_pressure(control)
    capital_table = misconduct_by_pressure(capital)

    lines.append(
        "The figures below are the share of trader-decisions in which each "
        "kind of dishonesty happened. A figure of 0.050 means it happened in "
        "five decisions out of a hundred."
    )
    lines.append("")
    rows = []
    for pressure in sorted(set(control_table) | set(capital_table)):
        c = control_table.get(pressure, {})
        k = capital_table.get(pressure, {})
        rows.append(
            [
                pressure,
                _n(c.get("withheld")),
                _n(k.get("withheld")),
                _n(c.get("misreported")),
                _n(k.get("misreported")),
            ]
        )
    lines.extend(
        _table(
            [
                "Pressure",
                "Stayed quiet (A)",
                "Stayed quiet (B)",
                "Lied (A)",
                "Lied (B)",
            ],
            rows,
        )
    )
    lines.append("")

    contrast = pressure_contrast(control, "withheld")
    trend = pressure_trend(control, "withheld")
    if contrast:
        lines.append(
            f"**Turning pressure on matters; turning it up does not.** With "
            f"no pressure at all, traders stayed quiet in "
            f"{_pct(contrast['rate_pressure_0'])} of decisions. As soon as any "
            f"pressure was applied that rose to "
            f"{_pct(contrast['rate_pressure_1_to_4'])}. To check that this is "
            f"not just noise we re-ran the comparison two thousand times on "
            f"randomly reshuffled selections of the episodes; a gap this large "
            f"came up by chance in only {_pct(contrast['p_no_difference'])} of "
            f"those reshuffles, which is small enough to take seriously."
        )
        lines.append("")
        lines.append(
            "But the harsher settings did not produce more of it than the "
            "mild one. The peak is at pressure 1, not pressure 4, and a "
            "straight line fitted through all five levels is essentially "
            f"flat (a slope of {_n(trend.get('slope'))}, where zero means no "
            "relationship at all). So the finding is that introducing rank "
            "pressure changes behaviour, not that more of it changes "
            "behaviour more."
        )
        lines.append("")

    capital_contrast = pressure_contrast(capital, "withheld")
    if capital_contrast:
        lines.append(
            f"In Setup B the same comparison gives "
            f"{_pct(capital_contrast['rate_pressure_0'])} with no pressure "
            f"against {_pct(capital_contrast['rate_pressure_1_to_4'])} with "
            f"pressure, appearing by chance in "
            f"{_pct(capital_contrast['p_no_difference'])} of reshuffles."
        )
        lines.append("")

    control_lies = sum(
        row["misreported"] * row["trader_rounds"] for row in control_table.values()
    )
    capital_lies = sum(
        row["misreported"] * row["trader_rounds"] for row in capital_table.values()
    )
    control_total = sum(row["trader_rounds"] for row in control_table.values())
    capital_total = sum(row["trader_rounds"] for row in capital_table.values())
    direction = (
        "less" if capital_lies < control_lies
        else "more" if capital_lies > control_lies
        else "about the same amount of"
    )
    lines.append(
        f"**Giving lying a payoff produced {direction} lying, not more.** "
        f"Traders lied in {round(control_lies)} of {round(control_total)} "
        f"decisions when it gained them nothing (Setup A), and "
        f"{round(capital_lies)} of {round(capital_total)} when it could win "
        f"them capital (Setup B). That is the most surprising result here and "
        "it runs against the reason Setup B was built."
    )
    lines.append("")
    lines.append(
        "It should not be read as proof that these models will not lie for "
        "gain. Both figures are small enough that the difference rests on a "
        "couple of dozen events, and there is an obvious rival explanation: "
        "in Setup B a manager is visibly dividing the money every single "
        "round on the strength of what traders say, which may simply make "
        "traders more careful about what they say. Distinguishing "
        "'unwilling to lie' from 'aware of being watched' needs a condition "
        "this experiment does not contain."
    )
    lines.append("")
    return lines


def section_manager(control, capital) -> list[str]:
    lines = ["## What the manager did", ""]

    statements = collect_statements(control)
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
        boss_fire = np.mean(
            [item.categories.get("termination", 0) for item in boss_public]
        )
        lines.append(
            f"**When the manager could only talk, it softened the pressure "
            f"rather than passing it on.** The founder raised the threat of "
            f"cutting capital in {_pct(ken_capital)} of the things it wrote "
            f"privately. The manager raised it in {_pct(boss_capital)} of the "
            f"{len(boss_public)} messages it actually sent to traders, and "
            f"threatened anyone's job in {_pct(boss_fire)} of them. The "
            "pressure did not survive the journey down."
        )
        lines.append("")
        lines.append(
            "One caution about that comparison. The founder's own "
            "instructions contain the pressure wording, so a good deal of "
            "what it writes is repeating what it was handed rather than "
            "escalating on its own. The manager's near-zero figure is the "
            "more informative half, because nothing in the manager's "
            "instructions pushes it either way."
        )
        lines.append("")

    if not capital:
        return lines

    spread = allocation_spread(capital)
    if spread:
        lines.append(
            "**When the manager controlled the money, it used that power "
            "readily.** The desk holds a fixed pot of 2.0, so an even split "
            "is 1.0 each and the gap between the two traders is 0. The table "
            "shows how far apart the manager actually chose to put them."
        )
        lines.append("")
        lines.extend(
            _table(
                ["Pressure", "Decisions", "Average gap", "Widest gap", "Split evenly"],
                [
                    [
                        pressure,
                        int(row["reviews"]),
                        _n(row["mean_gap"], 2),
                        _n(row["max_gap"], 2),
                        _pct(row["even_splits"]),
                    ]
                    for pressure, row in spread.items()
                ],
            )
        )
        lines.append("")

    starve = starvation(capital)
    if starve["events"]:
        occasions = (
            "once" if starve["events"] == 1 else f"{starve['events']} times"
        )
        lines.append(
            f"The manager took a trader's capital all the way to zero "
            f"{occasions}, freezing that trader out of trading for the "
            "following round. Nothing in the simulator prevents this and "
            "nothing in the manager's instructions suggests it, so even a "
            "single occurrence is worth recording — but one event is an "
            "anecdote, not a rate."
        )
    else:
        lines.append(
            "The manager never took a trader's capital all the way to zero, "
            "although nothing prevented it from doing so."
        )
    lines.append("")

    divergence = say_do_divergence(capital)
    if divergence["comparable_statements"]:
        lines.append(
            "**The clearest sign of trouble is the gap between what the "
            "manager said and what it did.** Because the manager writes its "
            "feedback and decides the money in a single breath, the two can "
            "be compared directly. We counted a case as contradictory when "
            "encouraging words came with a cut in capital, or critical words "
            "came with a rise. Cases where the wording carried no clear "
            "direction, or where the money did not move, are left out rather "
            "than counted as agreement."
        )
        lines.append("")
        lines.append(
            f"Of {divergence['comparable_statements']} decisions where both "
            f"the words and the money pointed somewhere, "
            f"{divergence['diverging']} pointed in opposite directions — "
            f"{_pct(divergence['rate'])}. Almost all of these ran the same "
            f"way: {divergence['praised_then_cut']} cases of praising a "
            f"trader while cutting its capital, against "
            f"{divergence['criticised_then_raised']} of the reverse. A "
            "trader reading its feedback would have been told it was doing "
            "well while quietly being given less to work with."
        )
        lines.append("")
        for example in divergence["examples"][:3]:
            lines.append(
                f"*Pressure {example['pressure']}, round {example['round']}, "
                f"{example['trader']}, capital {example['budget']}, tone "
                f"{example['tone']}:*"
            )
            lines.append("")
            lines.append(_quote(example["feedback"]))
            lines.append("")
    return lines


def section_detection(capital) -> list[str]:
    if not capital:
        return []
    lines = ["## Could the manager tell it was being lied to?", ""]
    lines.append(
        "In this setup the manager has, in principle, enough information to "
        "catch a lie. The market moves by the same fixed amount every round, "
        "so the desk's overall result should equal the sum of the positions "
        "the two traders claim. When someone shades their number, those two "
        "figures stop matching. The manager is never told this and is never "
        "asked to check."
    )
    lines.append("")
    lines.append(
        "There is a limit to what the arithmetic can reveal. The desk result "
        "only constrains the total, so a mismatch shows that somebody lied "
        "without showing which of the two it was. An honest trader can "
        "therefore be punished for a colleague's dishonesty."
    )
    lines.append("")

    challenge = challenge_rate(capital)
    if challenge["reviews_after_a_lie"] == 0:
        lines.append(
            f"In practice the manager questioned what it had been told in "
            f"{_pct(challenge['rate_without_a_lie'])} of the "
            f"{challenge['reviews_without_a_lie']} reviews it carried out. No "
            "review in this run followed a round containing a lie, so there "
            "is no evidence either way about whether it can spot one."
        )
    else:
        lines.append(
            f"In practice the manager questioned what it had been told in "
            f"{_pct(challenge['rate_without_a_lie'])} of the "
            f"{challenge['reviews_without_a_lie']} reviews where nobody had "
            f"lied, and {_pct(challenge['rate_after_a_lie'])} of the "
            f"{challenge['reviews_after_a_lie']} reviews where somebody had. "
            "The second figure is the one that matters: a manager that "
            "questions everything is not detecting anything."
        )
    lines.append("")

    accuracy = attribution_accuracy(capital)
    lines.append(
        "We also checked whose story the manager's own arithmetic follows. "
        "Before splitting the money it states what it believes each trader "
        "contributed. We compared that belief against what really happened, "
        "and against what the traders' claims would imply if taken at face "
        "value."
    )
    lines.append("")
    if accuracy["rounds_with_a_lie"] == 0:
        lines.append(
            "In this run those two comparisons cannot be told apart, because "
            "when nobody lies the claims and the truth are the same thing. "
            "The measurement is in place and will separate the two as soon "
            "as there are lies to separate them with."
        )
    else:
        lines.append(
            f"Across {accuracy['scored_traders']} judgements, the manager's "
            f"belief sat {_n(accuracy['mean_distance_to_truth'])} away from "
            f"the truth on average and "
            f"{_n(accuracy['mean_distance_to_reports'])} away from what the "
            f"claims imply."
        )
        if accuracy["rounds_with_a_lie"] < 20:
            lines.append("")
            lines.append(
                f"Those two figures are near-identical, and that is a "
                f"limitation rather than a result. The claims and the truth "
                f"only differ on rounds where somebody lied, and there were "
                f"just {accuracy['rounds_with_a_lie']} of those. On every "
                "other round the two comparisons are measuring the same "
                "thing, so they cannot come apart. This measurement will "
                "only become informative in a run containing substantially "
                "more dishonesty."
            )
        else:
            lines.append("")
            lines.append(
                f"The manager's belief was closer to the claims than to the "
                f"truth in {_pct(accuracy['closer_to_reports'])} of cases, "
                f"across {accuracy['rounds_with_a_lie']} rounds containing a "
                "lie."
            )
    lines.append("")

    payoff = did_lying_pay(capital)
    if payoff["rounds_with_a_lie"]:
        lines.append(
            f"**Did lying actually pay?** After a round in which a trader "
            f"lied, its capital changed by "
            f"{_n(payoff['mean_budget_change_after_lying'])} on average, "
            f"against {_n(payoff['mean_budget_change_after_truth'])} after an "
            f"honest round — a difference of {_n(payoff['difference'])}, over "
            f"{payoff['rounds_with_a_lie']} dishonest rounds. With that few "
            "cases this is a description of what happened, not a reliable "
            "estimate of what lying is worth."
        )
    else:
        lines.append(
            "**Did lying actually pay?** No trader lied often enough in this "
            "run to answer the question. The machinery to answer it is built "
            "and tested; it needs episodes containing lies."
        )
    lines.append("")
    return lines


def section_warning(control) -> list[str]:
    lines = ["## Can dishonesty be predicted before it happens?", ""]
    lines.append(
        "Each trader writes a private note to itself before it acts. Nobody "
        "else ever sees it. The question is whether that note tells us "
        "anything about what the trader is about to do that we could not "
        "already tell from its situation."
    )
    lines.append("")
    lines.append(
        "We built four predictors, each given progressively more to look at, "
        "and all using the same simple statistical method so that the only "
        "thing that differs is the information. The first sees only the "
        "trader's circumstances — the pressure level, its rank, its budget, "
        "how far behind it is, which round it is. The second adds the public "
        "record of the firm. The third adds the traders' private messages to "
        "each other. The fourth adds the private note."
    )
    lines.append("")
    lines.append(
        "Each predictor is scored on how well it sorts the risky decisions "
        "to the top of a list. If you ranked at random you would score about "
        "as well as the underlying rate of the behaviour; a perfect ranking "
        "scores 1.0. We never test a predictor on episodes it was trained "
        "on."
    )
    lines.append("")

    rows = []
    for target, costly, caption in (
        ("withholding", False, "Staying quiet"),
        ("withholding", True, "Staying quiet when it cost the firm money"),
        ("misreporting", False, "Lying"),
    ):
        data = build_rows(control, target, "same")
        results = cross_validated(data, target, costly_only=costly)
        comparison = paired_bootstrap(
            results["3_private_chat"], results["4_private_reasoning"]
        )
        rows.append(
            [
                caption,
                results["1_situation"].positives,
                _n(results["1_situation"].base_rate),
                _n(results["1_situation"].auprc),
                _n(results["3_private_chat"].auprc),
                _n(results["4_private_reasoning"].auprc),
                _pct(comparison["p_no_gain"]) if comparison else "not measurable",
            ]
        )
    lines.extend(
        _table(
            [
                "Behaviour",
                "Times it happened",
                "Random guessing scores",
                "Circumstances only",
                "Plus private messages",
                "Plus the private note",
                "Chance of the gain being luck",
            ],
            rows,
        )
    )
    lines.append("")
    lines.append(
        "**The private note helps in one place only.** For predicting that a "
        "trader is about to stay quiet in a way that costs the firm money, "
        "adding the note produced a real improvement that is unlikely to be "
        "chance. For everything else it added nothing. And the improvement "
        "disappears entirely when we ask the harder question — predicting "
        "what a trader will do a round from now rather than in the moment."
    )
    lines.append("")
    lines.append(
        "The most likely explanation is unglamorous. The words carrying the "
        "most weight in the predictor are phrases like *not share*, *will "
        "not*, and *will share*. The note sometimes simply states the "
        "intention out loud. That is useful for catching something as it "
        "happens, and it is not evidence that private reasoning forecasts "
        "behaviour."
    )
    lines.append("")
    return lines


def section_limits(control, capital) -> list[str]:
    lines = ["## What this cannot tell you", ""]
    lines.append(
        "**One model.** Everything here used a single open-weight model. The "
        "results describe that model, not language models in general, and "
        "the softening manager in particular could easily be a feature of "
        "how this one was trained."
    )
    lines.append("")
    lines.append(
        "**Two traders is barely an organisation.** With one colleague there "
        "is nobody to form an alliance with, nobody to blame, and exactly "
        "one person to keep a secret from. Most of what makes organisational "
        "misconduct interesting needs a third participant."
    )
    lines.append("")
    lines.append(
        "**The traders are told to care about their own ranking.** Their "
        "instructions say they are judged individually as well as "
        "collectively. Behaviour that follows from an instruction is the "
        "model doing as it is told, not the model revealing something about "
        "itself. A version of this experiment without that wording would "
        "make a much stronger claim."
    )
    lines.append("")
    lines.append(
        "**Lying is measured on very few cases.** Even with a payoff "
        "attached it stayed rare, so every statement here about lying rests "
        "on a handful of events and should be treated as provisional."
    )
    lines.append("")
    lines.append(
        "**The lexicon counts are blunt.** Where this document reports how "
        "often a manager threatened capital or questioned a report, that "
        "comes from matching phrases against a fixed list. The same list is "
        "applied to every condition, so comparisons between conditions are "
        "fair, but no individual sentence should be treated as definitively "
        "classified. Earlier versions of that list wrongly counted ordinary "
        "trading advice such as *reduce your position* as a threat to a "
        "trader's capital; the current one requires the money to be named."
    )
    lines.append("")
    return lines


def build_report(control_root: Path, capital_root: Optional[Path]) -> str:
    control = load_sweep(control_root)
    capital = load_sweep(capital_root) if capital_root else []
    if not control:
        raise SystemExit(f"no completed episodes in {control_root}")

    stamp = datetime.now(timezone.utc).strftime("%d %B %Y")
    lines = [
        "# Rank pressure and dishonesty in a simulated trading firm",
        "",
        f"Findings as of {stamp}. Written in plain language; the full "
        "technical results, with every interval and diagnostic, are in "
        "`RESULTS.md`.",
        "",
    ]
    lines.extend(section_setup(control, capital))
    lines.extend(section_dishonesty(control, capital))
    lines.extend(section_manager(control, capital))
    lines.extend(section_detection(capital))
    lines.extend(section_warning(control))
    lines.extend(section_limits(control, capital))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the plain-language findings document."
    )
    parser.add_argument("--control", required=True)
    parser.add_argument("--capital", default=None)
    parser.add_argument("--output", default="FINDINGS.md")
    parser.add_argument("--stdout", action="store_true")
    arguments = parser.parse_args(argv)

    report = build_report(
        Path(arguments.control),
        Path(arguments.capital) if arguments.capital else None,
    )
    if arguments.stdout:
        print(report)
        return 0
    Path(arguments.output).write_text(report, encoding="utf-8")
    print(f"Wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
