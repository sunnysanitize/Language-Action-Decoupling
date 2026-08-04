from environment.datacontainers import TraderAction, TraderObservation

# This is a very simple trading strategy that just follows the market states.
def choose_position(observation: TraderObservation) -> TraderAction:
    return TraderAction(observation.trader_id, observation.signal)


# Right now, its a TraderObservation -> Trader (This File), right now its a scripted 
# policy, but in the future this will be an LLM call