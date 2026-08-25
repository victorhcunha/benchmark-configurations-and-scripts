import csv
import glob
import io
import os
import re
import sys
import zipfile

# An "upgrade-*.zip" archives a single db-upgrade-client run. The metrics we
# want are already aggregated by the tool itself in the top-level
# "upgrade/fullResults.log" file, one "key: value" pair per line. Some lines
# carry a trailing " = Possible regression, last value was: X" note that
# must be stripped before parsing.

NAME_RE = re.compile(
	r"^upgrade-(?P<run_type>[^-]+)-(?P<branch>.+)-(?P<hash>[0-9a-f]{40})-"
	r"(?P<timestamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.zip$"
)

COLUMN_HEADER_ROW = [
	"Execution Date",
	"Portal Version (Hash)",
	"Schema Version Initial",
	"Schema Version Final",
	"Schema Version Expected",
	"Result",
	"Status",
	"Type",
	"Partitions count",
	"Error Traces",
	"Warn Traces",
	"Exec Time (s)",
	"Phase 0 OSGI (s)",
	"Phase 1 Preverify (s)",
	"Phase 2 Cleanup (s)",
	"Phase 3 Upgrades (s)",
	"Phase 3 Core (s)",
	"Phase 3 Modules (s)",
	"Phase 3b Mid Verify (s)",
	"Phase 3c Indexes (s)",
	"Phase 5 Post Verify (s)",
	"Phase 6 Report (s)",
	"Phase 1 Steps",
	"Phase 2 Steps",
	"Phase 3 Steps",
	"Phase 3b Steps",
	"Phase 3c Steps",
	"Phase 5 Steps",
	"Result Files",
]

FULL_RESULTS_TO_METRIC = {
	"execution_date": "Execution Date",
	"schema_version_initial": "Schema Version Initial",
	"schema_version_final": "Schema Version Final",
	"schema_version_expected": "Schema Version Expected",
	"result": "Result",
	"status": "Status",
	"type": "Type",
	"partitions_count": "Partitions count",
	"error_traces": "Error Traces",
	"warn_traces": "Warn Traces",
	"exec_time_s": "Exec Time (s)",
	"phase0_osgi_s": "Phase 0 OSGI (s)",
	"phase1_preverify_s": "Phase 1 Preverify (s)",
	"phase2_cleanup_s": "Phase 2 Cleanup (s)",
	"phase3_upgrades_s": "Phase 3 Upgrades (s)",
	"phase3_core_s": "Phase 3 Core (s)",
	"phase3_modules_s": "Phase 3 Modules (s)",
	"phase3b_midverify_s": "Phase 3b Mid Verify (s)",
	"phase3c_indexes_s": "Phase 3c Indexes (s)",
	"phase5_postverify_s": "Phase 5 Post Verify (s)",
	"phase6_report_s": "Phase 6 Report (s)",
	"phase1_steps": "Phase 1 Steps",
	"phase2_steps": "Phase 2 Steps",
	"phase3_steps": "Phase 3 Steps",
	"phase3b_steps": "Phase 3b Steps",
	"phase3c_steps": "Phase 3c Steps",
	"phase5_steps": "Phase 5 Steps",
}


def parse_full_results(content):
	metrics = {}

	for line in content.splitlines():
		# strip Ant's regression-check annotations, e.g.
		# "237.87 = Possible regression, last value was: 215.27" or
		# "failure = Expected: success" -> keep only the actual value.
		line = re.split(r" = (?:Possible regression|Expected:)", line)[0].strip()

		if not line or ":" not in line:
			continue

		key, value = line.split(":", 1)
		key = key.strip()

		if key in FULL_RESULTS_TO_METRIC:
			metrics[FULL_RESULTS_TO_METRIC[key]] = value.strip()

	return metrics


# Fallback for zips whose run did not make it far enough to produce a
# fullResults.log (e.g. failed early). Only the summary fields available in
# the per-run "*-upgrade_report.txt" are recovered; per-phase timings/steps
# are left blank.
REPORT_FIELD_PATTERNS = [
	("Execution Date", r"^Execution date:\s*(.+)$"),
	("Exec Time (s)", r"^Execution time:\s*(\d+)\s*seconds"),
	("Result", r"^Result:\s*(.+)$"),
	("Status", r"^Status:\s*(.+)$"),
	("Type", r"^Type:\s*(.+)$"),
	("Schema Version Initial", r"^Portal initial schema version:\s*(.+)$"),
	("Schema Version Final", r"^Portal final schema version:\s*(.+)$"),
	("Schema Version Expected", r"^Portal expected schema version:\s*(.+)$"),
]


def parse_upgrade_report(content):
	metrics = {}

	for label, pattern in REPORT_FIELD_PATTERNS:
		match = re.search(pattern, content, re.MULTILINE)
		if match:
			metrics[label] = match.group(1).strip()

	execution_date = metrics.get("Execution Date")
	if execution_date:
		try:
			import datetime

			parsed = datetime.datetime.strptime(execution_date, "%a, %b %d, %Y %H:%M:%S %Z")
			metrics["Execution Date"] = parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
		except ValueError:
			pass

	return metrics


def find_entry(namelist, suffix):
	matches = [n for n in namelist if n.endswith(suffix)]
	return matches[0] if matches else None


def process_upgrade_zip(zip_path):
	filename = os.path.basename(zip_path)
	name_match = NAME_RE.match(filename)
	portal_hash = name_match.group("hash") if name_match else "-"

	metrics = {}

	try:
		with zipfile.ZipFile(zip_path) as zip_file:
			full_results_entry = find_entry(zip_file.namelist(), "fullResults.log")

			if full_results_entry:
				content = zip_file.read(full_results_entry).decode("utf-8", errors="replace")
				metrics = parse_full_results(content)
			else:
				report_entry = find_entry(zip_file.namelist(), "upgrade_report.txt")
				if report_entry:
					content = zip_file.read(report_entry).decode("utf-8", errors="replace")
					metrics = parse_upgrade_report(content)
	except (zipfile.BadZipFile, OSError) as error:
		print(f"Warning: could not read {zip_path}: {error}")

	return [metrics.get(column, "-") for column in COLUMN_HEADER_ROW[:1]] + \
		[portal_hash] + \
		[metrics.get(column, "-") for column in COLUMN_HEADER_ROW[2:-1]] + \
		[filename]


def find_upgrade_zips(paths):
	zip_paths = []

	for path in paths:
		if os.path.isdir(path):
			zip_paths.extend(sorted(glob.glob(os.path.join(path, "upgrade-*.zip"))))
		else:
			zip_paths.append(path)

	return zip_paths


def append_rows_to_csv(rows, output_path):
	is_empty = not os.path.exists(output_path) or os.path.getsize(output_path) == 0

	with open(output_path, mode="a", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)

		if is_empty:
			writer.writerow(COLUMN_HEADER_ROW)

		writer.writerows(rows)


if __name__ == "__main__":
	if len(sys.argv) < 2:
		raise SystemExit(
			"Usage: python3 extract_upgrade_results.py <zip_or_folder> [<zip_or_folder> ...] [-o output.csv]"
		)

	args = sys.argv[1:]
	output_path = "upgrade_benchmarck_results.csv"

	if "-o" in args:
		index = args.index("-o")
		output_path = args[index + 1]
		del args[index:index + 2]

	zip_paths = find_upgrade_zips(args)

	if not zip_paths:
		raise SystemExit("No upgrade-*.zip files found")

	rows = []
	for zip_path in zip_paths:
		print(f"Processing {zip_path}")
		rows.append(process_upgrade_zip(zip_path))

	append_rows_to_csv(rows, output_path)
	print(f"Appended {len(rows)} row(s) to {output_path}")
