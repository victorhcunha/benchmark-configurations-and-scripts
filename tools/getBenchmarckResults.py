import sys
from zipfile import ZipFile

import csv
import cv2
import io
import numpy as np
from grinderTendency import analyze_session_trend

zip_path = ''

if len(sys.argv) > 1:
	zip_path = sys.argv[1]
else:
	raise SystemExit("No file found")

def extract_file_content(zip_path, file_path):
	with ZipFile(zip_path, 'r') as zip_file_content:
		with zip_file_content.open(file_path) as file_oppended:
			with io.TextIOWrapper(file_oppended, encoding='utf-8') as file_content:
				content = file_content.read()
		return content

def extract_grinder_results(data,rows=["Instant Session Waiting Time"],sample=-1):
	results = {row: None for row in rows}

	blocks = data.split("****************************")
	blocks = [x for x in blocks if "This is Sample" not in x]

	lines = [line for line in blocks[-1].strip().splitlines() if line.strip()]

	if "Instant Session Waiting Time" in rows:
		for line in lines:
			if line.startswith("Instant"):
				results["Instant Session Waiting Time"] = line.strip().split()[4]
				break

	for row in rows:
		for line in lines[3:]:
			if line.startswith(row):
				results[row] = line.strip().split()[-4]

	return results

def extract_logs_from_summary(columns_list):

	results = {
		"Error or exception in catalina.out": None,
		"WARN in catalina.out": None,
		"Grinder error": None
	}

	for log in results:
		if log in columns_list:
			results[log] = extract_section_from_text(extract_file_content(zip_path,'summary.log'),keyword=log)

	return results

def extract_portal_cg_results (zip_path):
	file_content = extract_file_content(zip_path, "portal/logs/portal-gc.log.results")

	results = {}

	for line in file_content.strip().splitlines():
		if ":" in line:
			key, value = line.split(":", 1)
			parts = value.strip().split(maxsplit=1)
			num = float(parts[0])

			suffix = parts[1] if len(parts) > 1 else ""

			if suffix:
				key = f"{key.strip()} ({suffix})"
			else:
				key = key.strip()

			results[key] = num

	return results

def extract_section_from_text(log_text, keyword=None, include_keyword_line=False):
	capture = False
	result = ""

	for line in log_text.splitlines(keepends=True):
		if capture:
			if line.strip() == "":
				break
			result += line
		elif keyword and keyword in line:
			capture = True
			if include_keyword_line:
				result += line
		elif keyword is None: 
			capture = True
			result += line

	return result

def extract_summary_data_from_string(log_content):
	keywords_next_line = {
		"Benchmark version:": "Benchmark Version",
		"Database name:": "database_name_value",
		"Portal version:": "Portal Version",
		"Result archive file name:": "Result archive file name",
	}

	results = {
		"Session Count": None,
		"Meantime of Login": None,
		"Benchmark Version": None,
		"database_name_value": None,
		"Portal Version": None,
		"Result archive file name": None,
		"Benchmark Config": None,
	}

	capture_next = None

	for line in log_content.splitlines():
		line = line.strip()

		if "Session count" in line:
			results["Session Count"] = line.split()[-1]
		elif "Log in meantime" in line:
			results["Meantime of Login"] = line.split()[-1]

		elif line in keywords_next_line:
			capture_next = keywords_next_line[line]
		elif capture_next:
			results[capture_next] = line

			if capture_next == "database_name_value":
				last_char = line[-1]
				if last_char in {"1", "2", "3", "4", "5", "6"}:
					results["Benchmark Config"] = last_char
				else:
					results["Benchmark Config"] = "master"

			capture_next = None

	return results

def extract_system_usage(columns_list):

	results = {
		"DB CPU Usage": None,
		"ES CPU Usage":None,
		"Portal CPU Usage": None
	}

	content = ""

	for log in results:
		if log in columns_list:
			if log == "DB CPU Usage":
				content = extract_file_content(zip_path,'database/logs/db-vmstat.log')
			elif log == "ES CPU Usage":
				content = extract_file_content(zip_path,'es/logs/elasticsearch-vmstat.log')
			elif log == "Portal CPU Usage":
				content = extract_file_content(zip_path,'portal/logs/portal-vmstat.log')
			results[log] = get_last_us_values_from_string(content)

	return results

def get_grinder_tendency(zip_path, file_path="grinder/logs/addtionalDataImage.jpg"):
	return {"Grinder 图": analyze_session_trend(zip_path, file_path)}

def get_last_us_values_from_string(content, us_column_index=12, position="last_three"):
	lines = content.strip().splitlines()
	data_lines = []

	for line in lines:
		parts = line.strip().split()

		if len(parts) > us_column_index and parts[0].isdigit():
			data_lines.append(parts)

	if position == "first_middle_last":
		first = int(data_lines[0][us_column_index])
		middle = int(data_lines[len(data_lines) // 2][us_column_index])
		last = int(data_lines[-1][us_column_index])

		return [first, middle, last]
	else:
		position="last_three"

	last_three = [int(row[us_column_index]) for row in data_lines[-3:]]
	return last_three

def save_to_csv(data, filename, columns_list):
	with open(filename, mode='w', newline='', encoding='utf-8') as file:
		writer = csv.writer(file)
		writer.writerow(columns_list)

		results_line = []
		for column in columns_list:
			if "Usage" in column:
				results_line.append((",".join(map(str, data.get(column,"")))))
				continue
			results_line.append(data.get(column,""))

		writer.writerow(results_line)

columns_list = ["Date", "Portal Version", "Benchmark Version", "Benchmark Config","Session Count","Percentage Change (%)","Meantime of Login","Error or exception in catalina.out", "WARN in catalina.out", "Grinder error","Result archive file name","Grinder 图","Meantime Specific Step", "Instant Session Waiting Time","DB CPU Usage","ES CPU Usage","Portal CPU Usage","Total Allocations (MB)","Average Allocation Rate (MB/S)","Total G1 Evacuation Pause count","Total Concurrent GC count","The Max Young GC Pause Time (ms)"]

def test_case_specific_steps():
	test_cases_steps = {
		"content": ["View Page"],
		"login": ["Log out"],
		"login1": ["Log out"],
		"objectDefinition": ["View Object Definition Page"],
		"documentlibrary": ["Add DL File"],
		"assetpublisher": ["View Page Without Filter", "View Page With Filter"]
	}

	file_name_parts = zip_path.split("/")[-1].split("-")

	for i in file_name_parts[::-1]:
		if i in test_cases_steps:
			test_case = i
			steps = test_cases_steps[test_case]
			break

	if "Meantime Specific Step" in columns_list:
		index = columns_list.index("Meantime Specific Step")
		columns_list.pop(index)

		for item in reversed(steps):
			if item not in columns_list:
				columns_list.insert(index, item)

	steps.append("Instant Session Waiting Time")

	return steps,test_case

save_to_csv((extract_summary_data_from_string(extract_file_content(zip_path,'summary.log'))) |
			(extract_logs_from_summary(columns_list)) |
			(get_grinder_tendency(zip_path)) |
			(extract_grinder_results(extract_file_content(zip_path,'grinder/logs/grinder.log'),test_case_specific_steps()[0])) |
			(extract_system_usage(columns_list)) |
			(extract_portal_cg_results(zip_path))
			,test_case_specific_steps()[1] + "_benchmarck_results.csv",columns_list)