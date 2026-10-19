"""Download the Federal Reserve SCF public extracts, 1989–2025.

Run with Python 3.10+ and curl. All files come directly from the Fed.
The downloaded summary extracts already express money in 2025 dollars.
"""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent
BASE = "https://www.federalreserve.gov"
YEARS = range(1989, 2026, 3)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(urljoin(BASE, href))


def download(url, destination):
    """Use curl because the Fed rejects some Python HTTP client requests."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        subprocess.run(
            ["curl", "--fail", "--location", "--silent", "--show-error",
             "--retry", "3", "--connect-timeout", "30", "--max-time", "180",
             url, "--output", str(temporary)],
            check=True,
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    raw = args.data_dir / "raw"
    records = []

    for year in YEARS:
        page_url = (f"{BASE}/econres/scfindex.htm" if year == 2025
                    else f"{BASE}/econres/scf_{year}.htm")
        page_path = raw / f"source_{year}.html"
        download(page_url, page_path)
        page = page_path.read_text(encoding="utf-8-sig")
        # Fail rather than silently mix vintages with different dollar bases.
        text = " ".join(page.lower().replace("&nbsp;", " ").split())
        if "inflation-adjusted to 2025 dollars" not in text:
            raise ValueError(f"Check dollar base on {page_url}; expected 2025.")
        links = Links()
        links.feed(page)
        matches = [u for u in links.links if u.endswith(f"scfp{year}excel.zip")]
        if not matches:
            raise ValueError(f"No CSV extract link found on {page_url}")
        url = matches[0]
        archive = raw / f"scfp{year}excel.zip"
        download(url, archive)
        with zipfile.ZipFile(archive) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(csv_names) != 1:
                raise ValueError(f"Expected one CSV in {archive}: {csv_names}")
            csv_bytes = zf.read(csv_names[0])
        csv_path = raw / f"scf{year}.csv"
        csv_path.write_bytes(csv_bytes)
        records.append({
            "year": year, "source_page": page_url, "download_url": url,
            "dollar_year": 2025, "csv_file": str(csv_path.relative_to(args.data_dir)),
            "sha256": hashlib.sha256(csv_bytes).hexdigest(),
        })
        print(f"Downloaded {year}: {len(csv_bytes):,} bytes", flush=True)

    for filename in ("bulletin.macro.txt", "scf2025_tables_public_real_historical.xlsx"):
        url = f"{BASE}/econres/files/{filename}"
        path = raw / filename
        download(url, path)
        records.append({"download_url": url, "file": str(path.relative_to(args.data_dir)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Board of Governors of the Federal Reserve System",
        "files": records,
    }
    (args.data_dir / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Saved data/sources.json with source URLs and checksums.")


if __name__ == "__main__":
    main()
