# Run MarketArena locally

## Requirements

Install Python 3.9 or newer

## macOS or Linux

Open a terminal in the project directory, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m marketarena.market
pip install -r requirements.txt
```

## Windows

Open PowerShell in the project directory, then run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m marketarena.market
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
python -m marketarena.market
```

On Windows:

```powershell
.venv\Scripts\Activate.ps1
py -m marketarena.market
```

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
