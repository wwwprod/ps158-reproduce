"""Reproduce Section 3's mean wealth figure from the downloaded SCF data."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
YEARS = list(range(1989, 2026, 3))
GROUPS = ("BA or more", "HS or less")


def weighted_stats(frame):
    """Pool the five implicates with the Fed's already-divided WGT.

    This reproduces the public table's point estimates. No standard errors
    are estimated by treating the five records as independent families.
    """
    ordered = frame.sort_values("NETWORTH")
    values = ordered["NETWORTH"].to_numpy()
    weights = ordered["WGT"].to_numpy()
    median = values[np.searchsorted(weights.cumsum(), weights.sum() / 2)]
    return {"mean": np.average(values, weights=weights), "median": median}


def load_year(raw, year):
    case_id, record_id = ("XX1", "X1") if year == 1989 else ("YY1", "Y1")
    columns = [case_id, record_id, "WGT", "EDCL", "KIDS", "NETWORTH", "ASSET", "DEBT"]
    frame = pd.read_csv(raw / f"scf{year}.csv", usecols=columns)
    if not np.isfinite(frame.to_numpy()).all() or not (frame.WGT > 0).all():
        raise ValueError(f"{year}: missing/nonfinite values or nonpositive weights")
    if not frame.EDCL.isin([1, 2, 3, 4]).all() or not (frame.KIDS >= 0).all():
        raise ValueError(f"{year}: unexpected education or children codes")
    if not frame[record_id].is_unique:
        raise ValueError(f"{year}: duplicate record IDs")
    if not frame.groupby(case_id).size().eq(5).all():
        raise ValueError(f"{year}: expected five implicates per family")
    if not frame.groupby(case_id)[record_id].agg(lambda x: set(x % 10) == {1, 2, 3, 4, 5}).all():
        raise ValueError(f"{year}: invalid implicate IDs")
    # Allow only floating-point/CSV rounding error in the accounting identity.
    if not np.allclose(frame.NETWORTH, frame.ASSET - frame.DEBT, rtol=1e-8, atol=0.01):
        raise ValueError(f"{year}: net worth differs from assets minus debts")
    return frame, case_id


def verify_source_table(table, frame, year):
    """Check Table 4's all-family and four education-group estimates.

    The published table is in thousands, rounded to 0.01 ($10).
    These checks deliberately use all families; the plotted child-at-home
    subsample does not have a corresponding row in this published table.
    """
    year_columns = [c for c in table.columns if table.iloc[2, c] == year]
    if len(year_columns) != 1:
        raise ValueError(f"Table 4 has no unique column for {year}")
    column = year_columns[0]
    checks = []
    labels = [("All families", None), ("No high school diploma", 1),
              ("High school diploma", 2), ("Some college", 3), ("College degree", 4)]
    for label, education in labels:
        rows = table.index[table[0].astype(str).str.strip().eq(label)]
        if len(rows) != 1:
            raise ValueError(f"Table 4 has no unique row for {label}")
        row = rows[0]
        subset = frame if education is None else frame[frame.EDCL.eq(education)]
        estimates = weighted_stats(subset)
        for offset, measure in enumerate(("median", "mean")):
            published = float(table.iloc[row, column + offset]) * 1000
            calculated = float(estimates[measure])
            difference = calculated - published
            if abs(difference) > 5.01:
                raise ValueError(f"{year} {label} {measure}: table difference ${difference:.2f}")
            checks.append({"year": year, "population": label, "measure": measure,
                           "calculated_dollars": calculated, "published_dollars": published,
                           "difference_dollars": difference})
    return checks


def draw(summary, destination):
    plt.rcParams.update({
        "font.family": "DejaVu Serif", "font.size": 11,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.8, "savefig.facecolor": "white",
    })
    fig, ax = plt.subplots(figsize=(11, 7.2))
    fig.subplots_adjust(left=0.105, right=0.96, top=0.96, bottom=0.24)
    for label, color, marker, line in zip(GROUPS, ["#171717", "#737373"], ["o", "s"], ["-", "--"]):
        series = summary[summary.group.eq(label)]
        values = series["mean_net_worth"]
        ax.plot(series.year, values, label=label, color=color, marker=marker,
                markerfacecolor="white", markersize=5, linewidth=1.8, linestyle=line)
        end = float(values.iloc[-1])
        ax.annotate(f"${end / 1000:,.0f}k", (2025, end), xytext=(9, 0),
                    textcoords="offset points", va="center", color=color, fontsize=10)
    ax.set_xlim(1988, 2028)
    ax.set_xticks(YEARS)
    ax.tick_params(axis="x", labelsize=9)
    ax.set_xlabel("Survey year", labelpad=10)
    ax.set_ylabel("Mean family net worth (2025 dollars)", labelpad=12)
    ax.set_ylim(0, 2_400_000)
    ax.yaxis.set_major_locator(MultipleLocator(400_000))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x / 1e6:.1f}m"))
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", frameon=False)
    fig.text(0.105, 0.145,
             "Figure 1. Mean family wealth by reference person's education, 1989–2025.",
             fontsize=11, weight="bold")
    fig.text(0.105, 0.108,
             "Notes: Families with a child at home (KIDS > 0). BA or more: EDCL = 4; HS or less: EDCL = 1 or 2.",
             fontsize=8.5)
    fig.text(0.105, 0.083,
             "Survey-weighted point estimates pooled across five implicates. Some-college families excluded. No confidence intervals.",
             fontsize=8.5)
    fig.text(0.105, 0.048,
             "Source: Federal Reserve, Survey of Consumer Finances. federalreserve.gov/econres/scfindex.htm",
             fontsize=8.5)
    fig.savefig(destination, dpi=220)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    raw = args.data_dir / "raw"
    manifest = json.loads((args.data_dir / "sources.json").read_text())
    for record in manifest["files"]:
        path = args.data_dir / record.get("csv_file", record.get("file"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Changed download: {path}; rerun get_data.py")
    table = pd.read_excel(raw / "scf2025_tables_public_real_historical.xlsx",
                          sheet_name="Table 4", header=None)
    if "2025 dollars" not in str(table.iloc[1, 0]):
        raise ValueError("Table 4 uses an unexpected dollar base")
    summary, checks = [], []
    for year in YEARS:
        frame, case_id = load_year(raw, year)
        checks.extend(verify_source_table(table, frame, year))
        parents = frame[frame.KIDS.gt(0)]
        for label in GROUPS:
            subset = parents[parents.EDCL.eq(4) if label == "BA or more" else parents.EDCL.le(2)]
            stats = weighted_stats(subset)
            summary.append({
                "year": year, "group": label,
                "mean_net_worth": float(stats["mean"]),
                "unique_families": subset[case_id].nunique(),
                "implicate_records": len(subset),
                "weighted_families": float(subset.WGT.sum()),
            })
    summary, checks = pd.DataFrame(summary), pd.DataFrame(checks)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    draw(summary, args.output_dir / "figure.png")
    print(f"Validated {len(checks)} source-table estimates; maximum difference "
          f"${checks.difference_dollars.abs().max():.2f} (table rounds to $10).")
    print(summary[summary.year.eq(2025)].to_string(index=False))
    print("Saved figure.png.")


if __name__ == "__main__":
    main()
