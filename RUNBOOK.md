# Windows Runbook

Use these steps to run the Azure DevOps Agile Metrics Portal on another Windows machine.

## Prerequisites

- Install Python 3.11 or later from [python.org](https://www.python.org/downloads/).
- During Python installation, select **Add Python to PATH**.
- Copy the complete project folder to the new machine. Keep the `src`, `tests`, `app.py`, and `pyproject.toml` files and folders together.
- Create an Azure DevOps PAT with `Project and Team: Read`, `Work Items: Read`, and Analytics access.

## Automated Setup Script

Run every step (venv, dependencies, `.env` creation, tests, and start) in order with one command from PowerShell:

```powershell
Set-Location C:\path\to\ado
.\scripts\setup.ps1
```

Options:

```powershell
.\scripts\setup.ps1 -Build     # also generate a wheel/sdist before running
.\scripts\setup.ps1 -SkipRun   # set up the environment and run tests, but don't start Streamlit
```

Edit `.env` with your Azure DevOps values the first time the script creates it, then re-run the script.

## Command Prompt Setup

Open **Command Prompt** and navigate to the project folder:

```cmd
cd C:\path\to\ado
```

Create and activate a virtual environment:

```cmd
py -m venv .venv
.venv\Scripts\activate.bat
```

Install the portal and its dependencies:

```cmd
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create `.env` in the project root. Do not copy another user's `.env` or share your PAT.

```cmd
copy .env.example .env
notepad .env
```

Set these values in `.env`:

```env
AZDO_ORGANIZATION=https://dev.azure.com/your-organization
AZDO_ADMIN_PAT=your-personal-access-token
AZDO_API_VERSION=7.1
REPORTING_LOOKBACK_DAYS=365
ADO_COMPLETED_STATES=Accepted
AZDO_TIME_ZONE=America/Chicago
```

Start the portal:

```cmd
python -m streamlit run app.py
```

Open `http://localhost:8501` in a browser. Select **Use configured PAT**, then choose the project and Area Path to generate charts.

Stop the application with `Ctrl+C` in the Command Prompt window.

## PowerShell Setup

Open **PowerShell** in the project folder:

```powershell
Set-Location C:\path\to\ado
py -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
python -m streamlit run app.py
```

## Daily Start Commands

Command Prompt:

```cmd
cd C:\path\to\ado
.venv\Scripts\activate.bat
python -m streamlit run app.py
```

PowerShell:

```powershell
Set-Location C:\path\to\ado
.\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

## Verify Installation

Run from an activated virtual environment:

```cmd
set PYTHONPATH=src
python -m pytest -q
```

Expected result: all tests pass.

## Generate a Build (Wheel/Sdist)

Install the build tool inside the activated virtual environment:

```cmd
python -m pip install --upgrade build
```

Generate the distributable package (creates `dist\*.whl` and `dist\*.tar.gz`):

```cmd
python -m build
```

Install the built wheel on another machine to verify it:

```cmd
python -m pip install dist\ado_agile_metrics-0.1.0-py3-none-any.whl
```

Clean previous build artifacts before rebuilding:

```powershell
Remove-Item -Recurse -Force build, dist, src\ado_agile_metrics.egg-info -ErrorAction SilentlyContinue
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `py` or `python` is not recognized | Reinstall Python and select **Add Python to PATH**, then open a new terminal. |
| `ModuleNotFoundError: ado_agile_metrics` | Activate `.venv`, then run `python -m pip install -e ".[dev]"`. |
| Port 8501 is already in use | Run `python -m streamlit run app.py --server.port 8502`, then open `http://localhost:8502`. |
| Azure access fails | Confirm `.env` contains the correct organization URL and a valid PAT. Never add quotes or spaces around the PAT. |
| Charts do not update | Stop Streamlit with `Ctrl+C`, start it again, and refresh the browser. |