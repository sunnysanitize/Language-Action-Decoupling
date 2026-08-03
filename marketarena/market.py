from dataclasses import dataclass
import random

VALID_DIRECTIONS = (-1, 1)

@dataclass(frozen=True)
class MarketRound:

    seed: int
    market_direction: int
    trader_a_signal: int
    trader_b_signal: int
    realized_return: float

def signal_generation(rng: random.Random, true_direction: int, accuracy: float) -> int:
    if true_direction not in VALID_DIRECTIONS:
        raise ValueError("true_direction must be -1 or   1")

    if not 0.0 <= accuracy <= 1.0:
        raise ValueError("accuracy must be between 0.0 and 1.0")

    signal_accuracy = rng.random() #the python random() method will only return numbers from 0.0 and 1.0 not including 1.0

    if signal_accuracy < accuracy: #this translates to accuracy, imagine a numberline where 70% is any float before 0.70
        return true_direction

    return -true_direction

# maybe add signal reliability asswell, which tells how much an agent should trust a signal

# Share the reliability information
# - help the firm
# - potentially help a rival beat you

# Withhold it
# - rival makes a weaker decision
# - potentially improve your relative rank

def generate_market_round(seed: int, signal_accuracy: float = 0.70, return_magnitude: float = 1.0,) -> MarketRound:
    if return_magnitude <= 0:
        raise ValueError("return_magnitude must be positive.")

    generated_random = random.Random(seed)
    true_direction = generated_random.choice(VALID_DIRECTIONS)
    trader_a_signal = signal_generation(generated_random, true_direction, signal_accuracy)
    trader_b_signal = signal_generation(generated_random, true_direction, signal_accuracy)
    realized_return = true_direction * return_magnitude

    return MarketRound(seed, true_direction, trader_a_signal, trader_b_signal, realized_return)

if __name__ == "__main__":
    example_round = generate_market_round(seed=1)
    print(example_round)

