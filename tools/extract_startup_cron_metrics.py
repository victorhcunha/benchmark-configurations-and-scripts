import csv
import glob
import io
import os
import re
import sys
import zipfile

import requests

# A "startup-all-*.zip" contains one sub-zip per benchmark phase
# (normal, expect, jmap, profile-tracing, profile-call_counting, ...).
# Each sub-zip has its own "startup/cron.log", which is a cumulative log
# snapshot up to the moment that sub-zip was built. To isolate the block
# that belongs to the current run (and not previous days/executions still
# present in the log) we cut the text between the last "Buildfile:" marker
# before the sub-zip's own "Building zip: <name>" line and that line itself.

BUILDFILE_MARKER = "Buildfile: /home/liferay/dev/projects/liferay-benchmark-ee/build.xml"

OUTER_NAME_RE = re.compile(
	r"^startup-all-(?P<branch>.+)-(?P<revision>[0-9a-f]{40})-(?P<timestamp>\d{4}-\d{2}-\d{2})-\d{2}-\d{2}-\d{2}\.zip$"
)

GITHUB_REPO = "liferay/liferay-portal"

merge_date_cache = {}


def get_merge_date(revision):
	if not revision:
		return "-"

	if revision in merge_date_cache:
		return merge_date_cache[revision]

	merge_date = "-"

	try:
		response = requests.get(
			f"https://api.github.com/repos/{GITHUB_REPO}/commits/{revision}",
			headers={"Accept": "application/vnd.github+json"},
			timeout=10,
		)
		response.raise_for_status()
		commit = response.json()
		# committer date reflects when the commit actually landed on master
		# (can be days after the author date, e.g. after a rebase)
		merge_date = commit["commit"]["committer"]["date"].split("T")[0]
	except (requests.RequestException, KeyError) as error:
		print(f"Could not look up merge date for commit {revision}: {error}")

	merge_date_cache[revision] = merge_date
	return merge_date

GROUP_HEADER_ROW = [
	"", "", "",
	"Cold Start-Shutdown - Time (ms)", "",
	"Startup - Hot Start - Time (ms)", "", "", "", "",
	"Shutdown - Hot Start - Time (ms)", "", "", "", "",
	"", "", "", "", "", "", "", "", "", "", "", "", "", "",
]

COLUMN_HEADER_ROW = [
	"Date", "Portal Version", "Server",
	"Startup - Cold start", "Shutdown - Cold start",
	"Run 1", "Run 2", "Run 3", "Run 4", "Run 5",
	"Run 1", "Run 2", "Run 3", "Run 4", "Run 5",
	"Thread Create Count",
	"Open File Number",
	"Open count of Prepared Statement",
	"Count of Prepared Statement Query",
	"Open count of SQL",
	"Open service tracker Count",
	"Open bundle tracker Count",
	"ACTIVE",
	"SATISFIED",
	"Objects",
	"Shallow size (MB)",
	"Retained size (MB)",
	"java.lang.ClassNotFoundException Count",
	"java.lang.NoSuchMethodException Count",
	"java.lang.NoSuchFieldException Count",
]


def read_zip_entry_bytes(zip_bytes, entry_suffix):
	with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
		matches = [n for n in z.namelist() if n.endswith(entry_suffix)]
		if not matches:
			return None
		with z.open(matches[0]) as f:
			return f.read()


def isolate_run_section(cron_log_text, sub_zip_filename):
	anchor = cron_log_text.find(sub_zip_filename)
	if anchor == -1:
		return cron_log_text

	start = cron_log_text.rfind(BUILDFILE_MARKER, 0, anchor)
	if start == -1:
		start = 0

	return cron_log_text[start:anchor]


def extract_phase_metrics(section):
	metrics = {}

	warmup = re.search(r"Warmup started in (\d+)ms, stopped in (\d+)ms", section)
	if warmup:
		metrics["Warmup Started (ms)"] = warmup.group(1)
		metrics["Warmup Stopped (ms)"] = warmup.group(2)

	for i, value in enumerate(re.findall(r"Startup took (\d+)ms", section), 1):
		metrics[f"Startup {i} (ms)"] = value

	for i, value in enumerate(re.findall(r"Shutdown took (\d+)ms", section), 1):
		metrics[f"Shutdown {i} (ms)"] = value

	active_satisfied = re.search(r"ACTIVE:\s*(\d+),\s*SATISFIED:\s*(\d+)", section)
	if active_satisfied:
		metrics["ACTIVE"] = active_satisfied.group(1)
		metrics["SATISFIED"] = active_satisfied.group(2)

	jmap_fields = [
		("Jmap Total bundleTracker count", r"Jmap Total bundleTracker count:\s*(\d+)"),
		("Jmap Total serviceTracker count", r"Jmap Total serviceTracker count:\s*(\d+)"),
		("Jmap Total objects", r"Jmap Total objects:\s*(\d+)"),
		("Jmap Total shallow size", r"Jmap Total shallow size:\s*(\d+)"),
		("Jmap Total retained size", r"Jmap Total retained size:\s*(\d+)"),
	]
	for label, pattern in jmap_fields:
		match = re.search(pattern, section)
		if match:
			metrics[label] = match.group(1)

	for name, value in re.findall(r"Table-([\w.\-]+?)\.csv:\s*(\d+)", section):
		metrics[f"Table-{name}.csv"] = value

	return metrics


def find_phase_section(outer_zip, phase_prefix):
	sub_zip_names = [n for n in outer_zip.namelist() if n.endswith(".zip") and os.path.basename(n).startswith(phase_prefix)]
	if not sub_zip_names:
		return {}

	sub_zip_name = sub_zip_names[0]
	sub_zip_bytes = outer_zip.read(sub_zip_name)
	cron_log_bytes = read_zip_entry_bytes(sub_zip_bytes, "cron.log")
	if cron_log_bytes is None:
		return {}

	cron_log_text = cron_log_bytes.decode("utf-8", errors="replace")
	section = isolate_run_section(cron_log_text, sub_zip_name)

	return extract_phase_metrics(section)


def find_server(outer_zip, phase_prefix="startup-normal-"):
	sub_zip_names = [n for n in outer_zip.namelist() if n.endswith(".zip") and os.path.basename(n).startswith(phase_prefix)]
	if not sub_zip_names:
		return "-"

	sub_zip_bytes = outer_zip.read(sub_zip_names[0])
	runner_log_bytes = read_zip_entry_bytes(sub_zip_bytes, "runner.log")
	if runner_log_bytes is None:
		return "-"

	runner_log_text = runner_log_bytes.decode("utf-8", errors="replace")
	matches = re.findall(r"startup-test-state/(\S+?)\.\.\.", runner_log_text)

	return matches[-1] if matches else "-"


def process_startup_all_zip(outer_zip_path):
	filename = os.path.basename(outer_zip_path)
	name_match = OUTER_NAME_RE.match(filename)
	portal_version = name_match.group("revision") if name_match else "-"
	date = get_merge_date(portal_version if name_match else None)

	normal = expect = jmap = tracing = {}
	server = "-"

	try:
		with zipfile.ZipFile(outer_zip_path) as outer_zip:
			normal = find_phase_section(outer_zip, "startup-normal-")
			expect = find_phase_section(outer_zip, "startup-expect-")
			jmap = find_phase_section(outer_zip, "startup-jmap-")
			tracing = find_phase_section(outer_zip, "startup-profile-tracing-")
			server = find_server(outer_zip)
	except (zipfile.BadZipFile, OSError) as error:
		print(f"Warning: could not read {outer_zip_path}: {error}")

	return [
		date,
		portal_version,
		server,
		normal.get("Warmup Started (ms)", "-"),
		normal.get("Warmup Stopped (ms)", "-"),
		normal.get("Startup 1 (ms)", "-"),
		normal.get("Startup 2 (ms)", "-"),
		normal.get("Startup 3 (ms)", "-"),
		normal.get("Startup 4 (ms)", "-"),
		normal.get("Startup 5 (ms)", "-"),
		normal.get("Shutdown 1 (ms)", "-"),
		normal.get("Shutdown 2 (ms)", "-"),
		normal.get("Shutdown 3 (ms)", "-"),
		normal.get("Shutdown 4 (ms)", "-"),
		normal.get("Shutdown 5 (ms)", "-"),
		tracing.get("Table-Thread-Create.csv", "-"),
		tracing.get("Table-File-Open.csv", "-"),
		tracing.get("Table-SQL-Prepared-Statement-Open.csv", "-"),
		tracing.get("Table-SQL-Prepared-Statement-Query.csv", "-"),
		tracing.get("Table-SQL-Open.csv", "-"),
		jmap.get("Jmap Total serviceTracker count", "-"),
		jmap.get("Jmap Total bundleTracker count", "-"),
		expect.get("ACTIVE", "-"),
		expect.get("SATISFIED", "-"),
		jmap.get("Jmap Total objects", "-"),
		jmap.get("Jmap Total shallow size", "-"),
		jmap.get("Jmap Total retained size", "-"),
		tracing.get("Table-ClassNotFoundException.csv", "-"),
		tracing.get("Table-NoSuchMethodException.csv", "-"),
		tracing.get("Table-NoSuchFieldException.csv", "-"),
	]


def find_startup_all_zips(paths):
	zip_paths = []

	for path in paths:
		if os.path.isdir(path):
			zip_paths.extend(sorted(glob.glob(os.path.join(path, "startup-all-*.zip"))))
		else:
			zip_paths.append(path)

	return zip_paths


def append_rows_to_csv(rows, output_path):
	is_empty = not os.path.exists(output_path) or os.path.getsize(output_path) == 0

	with open(output_path, mode="a", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)

		if is_empty:
			writer.writerow(GROUP_HEADER_ROW)
			writer.writerow(COLUMN_HEADER_ROW)

		writer.writerows(rows)


if __name__ == "__main__":
	if len(sys.argv) < 2:
		raise SystemExit(
			"Usage: python3 extract_startup_cron_metrics.py <zip_or_folder> [<zip_or_folder> ...] [-o output.csv]"
		)

	args = sys.argv[1:]
	output_path = "startup_benchmarck_results.csv"

	if "-o" in args:
		index = args.index("-o")
		output_path = args[index + 1]
		del args[index:index + 2]

	zip_paths = find_startup_all_zips(args)

	if not zip_paths:
		raise SystemExit("No startup-all-*.zip files found")

	rows = []
	for zip_path in zip_paths:
		print(f"Processing {zip_path}")
		rows.append(process_startup_all_zip(zip_path))

	append_rows_to_csv(rows, output_path)
	print(f"Appended {len(rows)} row(s) to {output_path}")
