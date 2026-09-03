import csv
import sys
from collections import Counter
from pathlib import Path

# Diffs two YourKit startup-test snapshot exports on the actual file paths
# opened during startup, instead of just the row counts StartupExtractorTask
# reports (e.g. "Table-File-Open.csv: 2493").
#
# Table-File-Open.csv only has a File_id per row, not a path. The path
# lives in Table-File.csv (ID -> Path), which the normal startup-test
# pipeline (StartupExtractorTask) deletes after extracting the metric
# tables it needs. To get both tables in one export directory, re-run the
# YourKit CLI manually against the raw .snapshot file kept in each result
# archive's startup/snapshots/ folder, instead of relying on the pipeline's
# pruned "extract" folder:
#
#   java -Dexport.apply.filters -Dexport.probes -Dexport.csv \
#     -jar <profiler.path>/lib/yourkit.jar \
#     -export <run>/startup/snapshots/tracing-Tomcat-*.snapshot <output_dir>
#
# Usage:
#   python3 diff_file_open_paths.py <baseline_export_dir> <regression_export_dir>


def load_file_paths(export_dir):
    path_by_id = {}
    with open(Path(export_dir) / "Table-File.csv") as f:
        for row in csv.DictReader(f):
            path_by_id[row["ID"]] = row["Path"]
    return path_by_id


def load_open_paths(export_dir):
    path_by_id = load_file_paths(export_dir)
    counts = Counter()
    unresolved = 0
    with open(Path(export_dir) / "Table-File-Open.csv") as f:
        for row in csv.DictReader(f):
            path = path_by_id.get(row["File_id"])
            if path is None:
                unresolved += 1
                continue
            counts[path] += 1
    return counts, unresolved


def main():
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} <baseline_export_dir> <regression_export_dir>")

    baseline, base_unresolved = load_open_paths(sys.argv[1])
    regression, reg_unresolved = load_open_paths(sys.argv[2])

    all_paths = sorted(set(baseline) | set(regression))
    changed = []
    for path in all_paths:
        before = baseline.get(path, 0)
        after = regression.get(path, 0)
        if before != after:
            changed.append((path, before, after, after - before))

    print(f"{'File Path':<110} {'Before':>7} {'After':>7} {'Delta':>7}")
    print("-" * 135)
    for path, before, after, delta in changed:
        sign = f"+{delta}" if delta > 0 else str(delta)
        print(f"{path:<110} {before:>7} {after:>7} {sign:>7}")

    delta_sum = sum(d for _, _, _, d in changed)
    print("-" * 135)
    print(f"Sum of per-file deltas: {delta_sum:+d}")
    if base_unresolved or reg_unresolved:
        print(f"(unresolved File_id rows: baseline={base_unresolved}, regression={reg_unresolved})")


if __name__ == "__main__":
    main()
