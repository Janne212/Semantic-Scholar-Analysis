import csv
from itertools import islice
from pathlib import Path


SOURCE_FILE = Path(__file__).with_name("semantic_scholar_2026.csv")
OUTPUT_FILE = Path(__file__).with_name("semantic_scholar_200_samples.csv")
SAMPLE_SIZE = 200


def main():
    with SOURCE_FILE.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"Source CSV is empty: {SOURCE_FILE}")

        rows = list(islice(reader, SAMPLE_SIZE))

    if len(rows) < SAMPLE_SIZE:
        raise ValueError(
            f"Expected {SAMPLE_SIZE} data rows, found {len(rows)} in {SOURCE_FILE}"
        )

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()