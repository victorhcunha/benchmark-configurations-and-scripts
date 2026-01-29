import sys
import os
import zipfile
from pathlib import Path
import shutil

if len(sys.argv) > 2:
	folder_path = sys.argv[1]
	test_hash = sys.argv[2]
else:
	raise SystemExit("Folder or hash not found")

output_dir = folder_path + f"{test_hash}_results"

def create_unique_output_dir(folder_path, test_hash):
    base_dir = Path(folder_path)
    base_name = f"{test_hash}_results"

    output_dir = base_dir / base_name
    counter = 1

    while output_dir.exists():
        output_dir = base_dir / f"{base_name}_{counter}"
        counter += 1

    output_dir.mkdir()
    print("Output directory created:", output_dir)
    return output_dir


def get_files_name(folder_path, test_hash, prefix):
    log_list = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if f.endswith('.zip') and f.startswith(prefix) and test_hash in f
    ]
    return log_list


def get_file_most_recent(files):
    most_recent_file = max(files, key=os.path.getmtime)
    return most_recent_file


def get_HEAP_snapshot_file(output_dir):
    original_zip = get_file_most_recent(
        get_files_name(folder_path, test_hash, "log-")
    )

    original_zip = Path(original_zip)

    heap_path = "portals/m2portal1/logs/heapdumps/"

    with zipfile.ZipFile(original_zip, "r") as z:
        heap_files = [
            f for f in z.namelist()
            if f.startswith(heap_path) and f.endswith(".bin")
        ]

        if not heap_files:
            print("No HEAP snapshot found.")
            return None

        heap_file = heap_files[0]

        filename = os.path.basename(heap_file)
        output_zip = os.path.join(output_dir, filename + ".zip")

        with z.open(heap_file) as src:
            with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                filename = Path(heap_file).name
                with zout.open(filename, "w") as dst:
                    shutil.copyfileobj(src, dst)

        print("Heap snapshot file extracted and zipped in:")
        print(output_zip)

        return output_zip

def remove_heap_from_zip(output_dir):
    original_zip = get_file_most_recent(
        get_files_name(folder_path, test_hash, "log-")
    )

    original_zip = Path(original_zip)
    heap_path = "portals/m2portal1/logs/heapdumps/"

    filename = os.path.basename(original_zip)
    output_zip = os.path.join(output_dir, filename)

    with zipfile.ZipFile(original_zip, "r") as zin:
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename.startswith(heap_path):
                    continue

                with zin.open(item) as src:
                    with zout.open(item.filename, "w") as dst:
                        shutil.copyfileobj(src, dst)

    print("Zip without heap file zipped in:")
    print(output_zip)

    return output_zip

def get_cpu_sampling_snapshot_file(output_dir):
    original_zip = get_file_most_recent(
        get_files_name(folder_path, test_hash, "profile-cpu-sampling-")
    )

    original_zip = Path(original_zip)

    cpu_sampling_path = "snapshots/"

    with zipfile.ZipFile(original_zip, "r") as z:
        snapshot_files = [
            f for f in z.namelist()
            if f.startswith(cpu_sampling_path) and f.endswith(".snapshot")
        ]

        if not snapshot_files:
            print("No CPU Sampling file found.")
            return None

        snapshot_file = snapshot_files[0]

        filename = os.path.basename(snapshot_file)
        output_zip = os.path.join(output_dir, filename + ".zip")

        with z.open(snapshot_file) as src:
            with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                filename = Path(snapshot_file).name
                with zout.open(filename, "w") as dst:
                    shutil.copyfileobj(src, dst)

        print("CPU Sampling file extracted and zipped in:")
        print(output_zip)

        return output_zip

def copy_sql_log_and_warmup_fies(output_dir):
    original_sql_log_zip =  Path(get_file_most_recent(
        get_files_name(folder_path, test_hash, "sql-log-")
    ))

    dest = output_dir / original_sql_log_zip.name
    shutil.copy2(original_sql_log_zip, dest)

    print("SQL Log file copied to:")
    print(dest)


    original_warmup_zip =  Path(get_file_most_recent(
        get_files_name(folder_path, test_hash, "warmup-")
    ))

    dest = output_dir / original_warmup_zip.name
    shutil.copy2(original_warmup_zip, dest)

    print("Warmup file copied to:")
    print(dest)


output_dir = create_unique_output_dir(folder_path, test_hash)
get_HEAP_snapshot_file(output_dir)
remove_heap_from_zip(output_dir)
get_cpu_sampling_snapshot_file(output_dir)
copy_sql_log_and_warmup_fies(output_dir)