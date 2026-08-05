# One isolated market round, start to finish. This is the original demo and it
# is intentionally the simplest thing in the project.
#
# Nothing carries forward here. There is no rank, no budget, no messages, no
# reasoning, and no misconduct labels, so nothing in this file can build
# pressure across rounds. Positions come straight from agents.trader, which
# follows the private signal and cannot behave strategically.
#
# It is still useful for checking the market itself: signal accuracy, realized
# returns, and profit arithmetic, without an agent in the way.
#
# For anything in the research pipeline use simulation.episode.run_episode
# instead. That runs connected rounds where state carries forward and traders
# act through the three phases of agents.policy.TraderPolicy.

from environment.market import generate_market_round
from environment.datacontainers import (Execution, LedgerEntry, RoundResult, TraderObservation, WorldState)
from agents.trader import choose_position

def run_round(seed: int, signal_accuracy: float = 0.70, return_magnitude: float = 1.0) -> RoundResult:

    market = generate_market_round(seed, signal_accuracy, return_magnitude)
    world = WorldState(market.market_direction, market.realized_return)

    # We set the observations for the traders
    Trader_A_Observations = TraderObservation("trader_a", market.trader_a_signal, signal_accuracy)
    Trader_B_Observations = TraderObservation("trader_b", market.trader_b_signal, signal_accuracy)

    # Store the observation object for each agent in a list to parse actions
    observations = [Trader_A_Observations, Trader_B_Observations]

    # Store the actions of each of the traders with their observations with a list
    actions = [choose_position(trader) for trader in observations]

    # Store the executions of each agent in a list
    executions = [Execution(action.trader_id, action.position, action.position) for action in actions]

    # Store the ledger entry in a list
    ledger = [LedgerEntry(execution.trader_id,
                          execution.executed_position,
                          execution.executed_position * world.realized_return) for execution in executions]

    return RoundResult(seed, world, observations, actions, executions, ledger)


if __name__ == "__main__":
    print(run_round(seed=1))
