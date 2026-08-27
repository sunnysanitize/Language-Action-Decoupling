# Run Language-Action Decoupling locally

Code for the paper *Language-Action Decoupling: Speech as a Weak Proxy
for Action in LLM Hierarchies*.

Paper: not yet released — link to be added here.

## Requirements

Install Python 3.9 or newer

## macOS or Linux

Open a terminal in the project directory, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m environment.market
pip install -r requirements.txt
```

## Windows

Open PowerShell in the project directory, then run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m environment.market
pip install -r requirements.txt
```

## API Keys

Before running you need to add your Azure API keys. Copy the `.env.example` file to `.env` and fill in the key:

```bash
cp .env.example .env
```

Then fill in the `.env` file with your API key.

Create one policy per trader:

```python
from agents.llm_trader import LLMTraderPolicy

policies = {
    "trader_a": LLMTraderPolicy.from_env(),
    "trader_b": LLMTraderPolicy.from_env(),
}
```

## Run it again later

Open a terminal in the project directory and reactivate the virtual environment.

On macOS or Linux:

```bash
source .venv/bin/activate
python -m environment.market
```

On Windows:

```powershell
.venv\Scripts\Activate.ps1
py -m environment.market
```

## The control desk (browser front end)

Start the local control desk:

```bash
python -m webui.server --open        # http://127.0.0.1:8765
```

It exposes the experiment commands through validated forms, streams job output
and progress, supports cancellation, and summarizes recorded runs. The pressure
dial shows budget multipliers in Setup A and founder rhetoric in Setup B, where
the boss controls capital.

### Watching an episode

The **Trading floor** replays an episode in causal order: brief, signal, share,
trade, report, market. Solid bubbles show delivered speech, dashed bubbles show
private reasoning, and lit wires show communication channels. It supports
deep links and can follow a live pilot.

The desk uses only the Python standard library and binds to loopback. Commands
come from a validated whitelist, and the API key is never sent to the browser.

## Run the full experiment

One episode, recorded, with a live model:

```bash
python -m experiments.pilot --rounds 10 --pressure 3
```

The whole grid -- every pressure level crossed with a shared seed list, each
episode in its own process:

```bash
python -m experiments.sweep --seeds 12 --rounds 10 --workers 10
```

Seeds are shared across pressure levels so the same market is played at every
level. Episodes retry on failure and the manifest records which ones did not
finish. Expect roughly half an hour for 60 episodes; the limit is the
provider's tokens-per-minute ceiling, not local CPU, so raising `--workers`
much past 10 does not help.

Then analyze a finished sweep and append the results to `RESULTS.md`:

```bash
python -m experiments.report --sweep runs/sweep-main --output RESULTS.md
```

The report appends rather than overwrites. A sweep measures a particular set
of prompts against a particular model, and `agents/prompts.py` is versioned
data, so an earlier measurement stays recoverable after a prompt is edited.

## Run the tests

The test suite uses Python's standard library and does not require extra packages.

On macOS or Linux:

```bash
source .venv/bin/activate
python -m unittest discover -v
```

On Windows:

```powershell
.venv\Scripts\Activate.ps1
py -m unittest discover -v
```
