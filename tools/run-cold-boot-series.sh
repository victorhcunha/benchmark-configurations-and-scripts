#!/bin/bash

# Runs a series of startup "normal" runs on a remote test console, rebooting the
# machine between runs so that every warmup starts from a freshly booted OS.
#
# Each iteration:
# 1. Waits until the console accepts SSH connections.
# 2. Waits until no Tomcat or Ant process is running there and no daily run is
# pending (auto-resume marker), so the series never overlaps the daily runner.
# 3. Runs "ant all-startup-runs -DtargetsList=normal" in the benchmark
# repository, detached with nohup so a dropped SSH session does not kill it,
# and streams its output live.
# 4. Collects the portal commit, the warmup time, and the result archive name
# into a local TSV summary, and keeps a local copy of each run log.
# 5. Reboots the console (skipped after the last iteration), waits
# --wait-before-connect seconds before the first SSH attempt, and then waits
# --wait-after-reboot seconds after SSH is back before the next iteration.
#
# Every command sent to the console is printed before it runs.
#
# The run uses the manual baseline and log directory (log/startup), never the
# daily auto baseline (log/startup/auto). The @reboot cron of
# run-startup-tests-daily.sh ignores these reboots because no auto-resume
# marker is written.
#
# Usage:
# scripts/run-cold-boot-series.sh [--host <user@host>] [--iterations <n>]
# [--wait-after-reboot <seconds>] [--wait-before-connect <seconds>]
# [--remote-dir <path>] [--output <dir>]
#
# Prerequisites on the console:
# liferay ALL=(ALL) NOPASSWD: /sbin/shutdown (in /etc/sudoers)

set -euo pipefail

HOST="liferay@m1console2"
ITERATIONS=10
OUTPUT_DIR=""
REMOTE_DIR="dev/projects/liferay-benchmark-ee"
WAIT_AFTER_REBOOT=20
WAIT_BEFORE_CONNECT=30

readonly POLL_INTERVAL=15
readonly RUN_TIMEOUT=1800
readonly SSH_TIMEOUT=900

readonly REMOTE_ANT_HOME="/opt/java/apache-ant-1.10.14"
readonly REMOTE_JAVA_HOME="/opt/java/jdk21"

# Kept outside log/startup because the clean-startup-sample target run by
# all-startup-runs deletes that whole directory before each run.

readonly REMOTE_SERIES_DIR="cold-boot-series"

_info() { echo "[$(date '+%H:%M:%S')] $*"; }

_usage() {
	sed --quiet '/^# Usage:/,/^# \[--remote-dir/p' "$0" | sed 's/^# \{0,1\}//'
	exit 1
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--host)
			HOST="$2"
			shift 2
			;;
		--iterations)
			ITERATIONS="$2"
			shift 2
			;;
		--output)
			OUTPUT_DIR="$2"
			shift 2
			;;
		--remote-dir)
			REMOTE_DIR="$2"
			shift 2
			;;
		--wait-after-reboot)
			WAIT_AFTER_REBOOT="$2"
			shift 2
			;;
		--wait-before-connect)
			WAIT_BEFORE_CONNECT="$2"
			shift 2
			;;
		*)
			_usage
			;;
	esac
done

readonly SERIES_ID="$(date '+%Y-%m-%d-%H-%M-%S')"

if [[ -z "${OUTPUT_DIR}" ]]; then
	OUTPUT_DIR="cold-boot-series-${SERIES_ID}"
fi

readonly SUMMARY_FILE="${OUTPUT_DIR}/summary.tsv"

mkdir --parents "${OUTPUT_DIR}"

_ssh() {
	ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 "${HOST}" "$@"
}

# Same as _ssh, but prints the command first. Used for every step except the
# repeated polling probes, which would otherwise flood the output.

_ssh_logged() {
	echo "  \$ ssh ${HOST} '$*'" >&2

	_ssh "$@"
}

_wait_for_ssh() {
	local deadline=$((SECONDS + SSH_TIMEOUT))

	_info "Waiting for SSH on ${HOST} (probe: ssh ${HOST} true, every ${POLL_INTERVAL}s)..."

	until _ssh true 2>/dev/null; do
		if [[ ${SECONDS} -ge ${deadline} ]]; then
			_info "ERROR: ${HOST} did not accept SSH within ${SSH_TIMEOUT}s."

			exit 1
		fi

		sleep "${POLL_INTERVAL}"
	done

	_info "SSH is up."
}

_console_busy_reason() {

	# The bracketed first letter keeps the pattern from matching the command
	# line of the remote shell that runs pgrep itself.

	_ssh "pgrep --full --list-full '[o]rg\.apache\.catalina\.startup\.Bootstrap|[o]rg\.apache\.tools\.ant\.launch\.Launcher' | cut --characters=1-150; test -e \${HOME}/.startup-test-state/auto-resume && echo 'auto-resume marker present (daily run pending)'" || true
}

_wait_for_idle_console() {
	local deadline=$((SECONDS + RUN_TIMEOUT))

	_info "Checking that ${HOST} is idle (no Tomcat/Ant, no auto-resume marker)..."

	local reason
	reason="$(_console_busy_reason)"

	while [[ -n "${reason}" ]]; do
		if [[ ${SECONDS} -ge ${deadline} ]]; then
			_info "ERROR: ${HOST} stayed busy for ${RUN_TIMEOUT}s:"
			echo "${reason}"

			exit 1
		fi

		_info "Console busy, waiting:"
		echo "${reason}"

		sleep "${POLL_INTERVAL}"

		reason="$(_console_busy_reason)"
	done

	_info "Console is idle."
}

_run_normal_target() {
	local iteration="$1"
	local log_file="\${HOME}/${REMOTE_SERIES_DIR}/${SERIES_ID}-run-${iteration}.log"
	local rc_file="\${HOME}/${REMOTE_SERIES_DIR}/${SERIES_ID}-run-${iteration}.rc"
	local local_log="${OUTPUT_DIR}/run-${iteration}.log"

	_info "Run ${iteration}/${ITERATIONS}: starting ant on ${HOST}."

	# Only the nohup command is backgrounded, with all of its streams detached,
	# so this SSH session returns immediately instead of waiting for Ant.

	_ssh_logged "mkdir --parents \${HOME}/${REMOTE_SERIES_DIR} && rm --force ${rc_file} && cd ${REMOTE_DIR} && { nohup env ANT_HOME=${REMOTE_ANT_HOME} ANT_OPTS=-Xmx2560m JAVA_HOME=${REMOTE_JAVA_HOME} PATH=${REMOTE_JAVA_HOME}/bin:${REMOTE_ANT_HOME}/bin:/usr/local/bin:/usr/bin:/bin bash -c \"ant all-startup-runs -DtargetsList=normal > ${log_file} 2>&1; echo \\\$? > ${rc_file}\" > /dev/null 2>&1 < /dev/null & }"

	_info "Run ${iteration}/${ITERATIONS}: streaming the ant log (local copy: ${local_log})..."

	# Follow the remote log until the exit code file appears. If the stream
	# drops, fall back to polling for the exit code file below.

	timeout "${RUN_TIMEOUT}" ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 "${HOST}" "tail --follow=name --lines=+1 --retry ${log_file} 2>/dev/null & tail_pid=\$!; while [ ! -e ${rc_file} ]; do sleep 2; done; sleep 2; kill \${tail_pid}" \
		| tee "${local_log}" \
		|| _info "Log stream ended unexpectedly, polling for the result instead."

	local deadline=$((SECONDS + RUN_TIMEOUT))

	until _ssh "test -e ${rc_file}" 2>/dev/null; do
		if [[ ${SECONDS} -ge ${deadline} ]]; then
			_info "ERROR: run ${iteration} did not finish within ${RUN_TIMEOUT}s (see ~/${REMOTE_SERIES_DIR} on ${HOST})."

			exit 1
		fi

		sleep "${POLL_INTERVAL}"
	done

	local rc
	rc="$(_ssh_logged "cat ${rc_file}")"

	_ssh "cat ${log_file}" > "${local_log}"

	local run_log
	run_log="$(cat "${local_log}")"

	local commit
	commit="$(grep --only-matching --max-count=1 'Set Git ID \[[0-9a-f]*\]' <<< "${run_log}" | grep --only-matching '[0-9a-f]\{40\}' || echo "unknown")"

	local warmup
	warmup="$(grep --only-matching --max-count=1 'Warmup started in [0-9]*ms, stopped in [0-9]*ms' <<< "${run_log}" || true)"

	local warmup_ms
	warmup_ms="$(sed --quiet 's/Warmup started in \([0-9]*\)ms.*/\1/p' <<< "${warmup}")"

	local stopped_ms
	stopped_ms="$(sed --quiet 's/.*stopped in \([0-9]*\)ms/\1/p' <<< "${warmup}")"

	local zip_file
	zip_file="$(grep --only-matching --max-count=1 'Building zip: [^ ]*\.zip' <<< "${run_log}" | sed 's/Building zip: //' || true)"

	printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
		"${iteration}" "$(date --utc '+%Y-%m-%d %H:%M:%S UTC')" "${commit}" \
		"${warmup_ms:-NA}" "${stopped_ms:-NA}" "${rc}" "${zip_file:-NA}" \
		>> "${SUMMARY_FILE}"

	_info "Run ${iteration}/${ITERATIONS} done: commit=${commit:0:10} warmup=${warmup_ms:-NA}ms rc=${rc}"
}

_reboot_console() {
	_info "Rebooting ${HOST}..."

	_ssh_logged "sudo --non-interactive shutdown --reboot now" || true

	# Wait for the console to actually go down before polling for it to return.

	_info "Waiting for ${HOST} to go down..."

	local deadline=$((SECONDS + SSH_TIMEOUT))

	while _ssh true 2>/dev/null; do
		if [[ ${SECONDS} -ge ${deadline} ]]; then
			_info "ERROR: ${HOST} did not go down after the reboot request."

			exit 1
		fi

		sleep 5
	done

	_info "${HOST} is down, waiting ${WAIT_BEFORE_CONNECT}s before the first SSH attempt..."

	sleep "${WAIT_BEFORE_CONNECT}"

	_wait_for_ssh

	_info "Waiting ${WAIT_AFTER_REBOOT}s before the next run..."

	sleep "${WAIT_AFTER_REBOOT}"
}

printf 'iteration\ttimestamp\tportal_commit\twarmup_ms\tstopped_ms\tant_rc\tzip\n' > "${SUMMARY_FILE}"

_info "Series ${SERIES_ID}: ${ITERATIONS} iterations on ${HOST}, output in ${OUTPUT_DIR}/."

for ((iteration = 1; iteration <= ITERATIONS; iteration++)); do
	_wait_for_ssh
	_wait_for_idle_console
	_run_normal_target "${iteration}"

	if [[ ${iteration} -lt ${ITERATIONS} ]]; then
		_reboot_console
	fi
done

_info "Series finished. Summary:"

column --table --separator $'\t' "${SUMMARY_FILE}"
