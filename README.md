# N8_stats

Analyze GGPoker Rush & Cash hand-history files and generate session statistics.

## What this project does

`analyze.py` parses hand-history text files in a date folder (for example `0407/`) and reports:

- Total hands, fold/showdown distribution
- Gross/net PnL and BB/100
- Position-level performance (BTN/CO/MP/LP/SB/BB)
- Top 10 most profitable starting hands
- Optional visualization chart image (`pnl_<DATE>.png`)

## Requirements

- Python 3.8+
- Python packages:
  - `pandas`
  - `matplotlib`
  - `seaborn`

Install dependencies:

```bash
pip install pandas matplotlib seaborn
```

## Data layout

Place hand-history files under a date folder next to `analyze.py`.

Example:

```text
N8_stats/
├── analyze.py
├── 0406/
│   └── GG*.txt
├── 0407/
│   └── GG*.txt
└── 0408/
    └── GG*.txt
```

## How to use

From the repository root:

```bash
# Print statistics only
python analyze.py --DATE 0407

# Print statistics and generate chart
python analyze.py --DATE 0407 --plot
```

## Output

- Console summary: overall stats, position analysis, top 10 starting hands
- Optional chart file: `pnl_<DATE>.png`

## Notes

- `--DATE` must match an existing folder name (e.g. `0406`, `0407`, `0408`).
- The script reads files matching `GG*.txt` in that folder.
- For detailed Chinese usage documentation, see `USAGE.md`.
