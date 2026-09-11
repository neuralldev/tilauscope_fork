# How to run TilauScope from source

## Introduction

TilauScope does not provides install packages for all supported platforms, as this fork is destinated to home roasters, they have to be built locally.  The code can be run directly from the local computer without the need to build a distribution package.

## Installation on macOS/Windows

1. Install visual studio and add git tools

2. Install Python 3.14 from [python.org](https://www.python.org/) or for Windows 11, from the Microsoft Store

3. Create and activate a virtual environment from visual studio after having downloaded a copy of the repository

### on macOS and Linux

- open a terminal
- check that python is running

```bash
python3 -m venv TilauScope_venv
source TilauScope_venv/bin/activate
```

this will create a new compartimented environnemnt for Tilauscope and activate the virtual environment, you are now ready to install all the packages

### on Windows 11

> you might have to elevate the shell before running the commands with: Set-ExecutionPolicy -ExecutionPolicy Unrestricted

```powershell
python3 -m venv TilauScope_venv
TilauScope_venv\scripts\activate
```

### moving on

1. Clone the TilauScope repository

```bash or powershell
git clone https://github.com/neuralldev/tilauscope.git
```
2. Install required packages

    ```bash or powershell
    cd TilauScope/src
    pip install -r requirements.txt
    ```

3. Start TilauScope from the TilauScope/src directory

```bash or posershell
python3 TilauScope.py
```

### Application log

The application log can be found at the following directory. however all the debug messages are sent to TCP 9021 port by default. this can be changed by editing src/includes/logging.yaml

- macOS

   ```bash
   tail -f ~/Library/Application\ Support/TilauScope/TilauScope.log
   ```

- Windows

   ```powershell
   notepad %localappdata%\TilauScope\TilauScope\TilauScope.log
   ```

### Installing and running dev tools

connect to your virtual environment first, then use the following command:

```bash or powershell
pip install -r requirements-dev.txt
```

### Linting

```bash
codespell
ruff check .
pylint */*.py
```

### Typing

```bash
mypy
pyright
mypy --strict
```

## additional consideration if you want to build a distribution package locally for a specific platform

Only MacOS and Windows 11 are currently supported

- On both, you need to instal QT6 from the official download directory (do not install everything with documentation, limit to basic installation)
- in addition on 