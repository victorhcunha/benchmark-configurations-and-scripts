import pandas as pd

# Load data
report_csv = pd.read_csv("report.csv")
suite_results_csv = pd.read_csv("suite.csv")

# Replace NaN with empty string in the target column
report_csv["Status from other runs"] = report_csv["Status from other runs"].fillna("")

# Filter tests that passed in the suite results
passed_tests = suite_results_csv[suite_results_csv["Status"].str.upper() == "PASSED"]
passed_tests_dict = dict(zip(passed_tests["Case Name"], passed_tests["Case Result URL"]))

# DEBUG: how many tests in report match the ones that passed in suite results
report_names = set(report_csv["Case Name"])
suite_names = set(passed_tests_dict.keys())
matched_names = report_names & suite_names

print(f"🔍 Tests in report: {len(report_names)}")
print(f"✅ Tests passed in suite results: {len(passed_tests_dict)}")
print(f"🎯 Tests matched: {len(matched_names)}")

# Update the column
def update_status(row):
    case_name = row["Case Name"]
    existing = row["Status from other runs"]
    if existing == "" and case_name in passed_tests_dict:
        return f"Passed in another run {passed_tests_dict[case_name]}"
    return existing

report_csv["Status from other runs"] = report_csv.apply(update_status, axis=1)

# Show 5 examples of updated rows
updated_rows = report_csv[report_csv["Status from other runs"].str.startswith("Passed in another run")]
print("\n📋 Examples of updated rows:")
print(updated_rows[["Case Name", "Status from other runs"]].head())

# Save the result
report_csv.to_csv("report_updated.csv", index=False)
print("\n✅ File saved as 'report_updated.csv'")
