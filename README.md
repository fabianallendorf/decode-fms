# decode-fms

A utility tool for decoding the brilliantly evil forms provided by the german [Formular-Management-System (FMS) der Bundesfinanzverwaltung](https://www.formulare-bfinv.de/ffw/selectMenu.do?%24csrf=8SSY986IK3WHNJZCJ0KJJYR3N&path=%2Fstartpage)

## Setup

Install [`poetry`](https://python-poetry.org/docs/#installation)

Run:

```bash
poetry install
```

## Usage

```bash
poetry shell
python main.py
```

[![asciicast](https://asciinema.org/a/f11UPYxat3vhn0cJeVDkqujlI.svg)](https://asciinema.org/a/f11UPYxat3vhn0cJeVDkqujlI)

With search term:

```bash
python main.py --search "1454"
```

A finished xml file with comments will be created in the subfolder `formulare/`.
Do not expect a good result.
