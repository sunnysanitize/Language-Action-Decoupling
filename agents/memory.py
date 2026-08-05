# Each experiment lasts for multiple rounds with the same traders. The simulator
# carries rank, budget, cumulative profit, the profit gap, and misconduct counts
# between rounds. Misconduct counts are only for research and must not be shown
# to a trader. However, an LLM trader should remember details it actually saw in
# earlier rounds, such as its messages, decisions, reports, and results.
#
# Future code in this file should build a memory for each trader from completed
# RoundDetails records. A trader should receive information it already saw, but
# not another trader's private information. This lets the LLM act like the same
# trader across the whole experiment instead of starting fresh every round.
