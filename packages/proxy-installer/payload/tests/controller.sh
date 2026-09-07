#!/usr/bin/env bash
# HAProxy regression suite.  It deliberately runs the production program only
# with paths and process-control commands rooted in a disposable sandbox.
set -uo pipefail

script_dir="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
target="${PROXY_UNDER_TEST:-$script_dir/../proxy}"
failures=0
checks=0
sandbox=''
proxy_rc=0
host_endpoint='http://127.0.0.1:18080'
docker_endpoint='http://192.168.20.5:18080'
corporate_proxy_host='proxy-test.invalid'
corporate_proxy_port='8080'
default_no_proxy='localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.nav.gov.hu'
success_threshold=2
failure_threshold=3
configured_ca_bundle=''

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  failures=$((failures + 1))
}

pass() {
  checks=$((checks + 1))
}

cleanup() {
  [[ -n "$sandbox" && -d "$sandbox" ]] && rm -rf -- "$sandbox"
}

trap cleanup EXIT HUP INT TERM

assert_true() {
  local description="$1"
  shift
  if "$@"; then
    pass
  else
    fail "$description"
  fi
}

assert_rc() {
  local expected="$1" description="$2"
  [[ "$proxy_rc" -eq "$expected" ]] && pass || fail "$description (exit $proxy_rc, expected $expected)"
}

assert_nonzero() {
  [[ "$proxy_rc" -ne 0 ]] && pass || fail "$1 (unexpected success)"
}

assert_file_contains() {
  local path="$1" needle="$2" description="$3" content=''
  [[ -f "$path" ]] && content=$(<"$path")
  [[ "$content" == *"$needle"* ]] && pass || fail "$description"
}

assert_file_equals() {
  local path="$1" expected="$2" description="$3" actual=''
  [[ -f "$path" ]] && actual=$(<"$path")
  [[ "$actual" == "$expected" ]] && pass || fail "$description"
}

make_mock() {
  local name="$1" body="$2"
  printf '%s\n%s\n' '#!/usr/bin/bash' 'set -uo pipefail' > "$sandbox/mocks/$name"
  printf '%s\n' "$body" >> "$sandbox/mocks/$name"
  chmod 700 "$sandbox/mocks/$name"
}

setup_mocks() {
  mkdir -p "$sandbox/mocks" "$sandbox/home/.config/test-trust" "$sandbox/state" "$sandbox/etc" "$sandbox/docker"
  : > "$sandbox/nc-results"
  : > "$sandbox/mock-nc.log"
  : > "$sandbox/mock-systemctl.log"
  : > "$sandbox/mock-journal.log"
  : > "$sandbox/mock-listener.log"
  : > "$sandbox/mock-haproxy.log"
  : > "$sandbox/mock-crash.log"
  printf '4242\n' > "$sandbox/service.pid"

  make_mock nc '
printf "%s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-nc.log"
mapfile -t results < "$PROXY_TEST_ROOT/nc-results"
index=0
[[ -f "$PROXY_TEST_ROOT/nc-index" ]] && index=$(<"$PROXY_TEST_ROOT/nc-index")
printf "%s\\n" "$((index + 1))" > "$PROXY_TEST_ROOT/nc-index"
[[ "${results[index]:-fail}" == ok ]]
'
  make_mock systemctl '
printf "%s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-systemctl.log"
case " $* " in
  *" show "*|*" MainPID "*) cat "$PROXY_TEST_ROOT/service.pid" ;;
  *" is-active "*) printf "active\\n" ;;
  *" reload "*|*" restart "*)
    [[ "${PROXY_TEST_SYSTEMCTL_RESULT:-ok}" == ok ]] || exit 70
    [[ "${PROXY_TEST_JOURNAL_RESULT:-ok}" != timeout ]] || exit 124
    if [[ "${PROXY_TEST_JOURNAL_RESULT:-ok}" == pid-change ]]; then printf "4243\n" > "$PROXY_TEST_ROOT/service.pid"; fi
    ;;
esac
'
  make_mock journal-confirm '
printf "%s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-journal.log"
case "${PROXY_TEST_JOURNAL_RESULT:-ok}" in
  ok) printf "confirmed pid=%s\\n" "$(<"$PROXY_TEST_ROOT/service.pid")" ;;
  timeout) exit 124 ;;
  pid-change) printf "confirmed pid=4243\\n" ;;
  *) exit 71 ;;
esac
'
  make_mock listener-wakeup '
printf "%s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-listener.log"
[[ "${PROXY_TEST_LISTENER_RESULT:-ok}" == ok ]]
'
  make_mock haproxy '
printf "%s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-haproxy.log"
[[ "${PROXY_TEST_TINYPROXY_RESULT:-ok}" == ok ]]
'
  make_mock crash-point '
printf "%s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-crash.log"
[[ "${1:-}" != "${PROXY_TEST_CRASH_AT:-never}" ]]
'
  make_mock sudo '
printf "sudo unexpectedly invoked: %s\\n" "$*" >> "$PROXY_TEST_ROOT/mock-sudo.log"
exit 80
'
  : > "$sandbox/mock-sudo.log"
}

reset_sandbox() {
  rm -rf -- "$sandbox/state" "$sandbox/etc" "$sandbox/docker"
  mkdir -p "$sandbox/state" "$sandbox/etc" "$sandbox/docker"
  printf '4242\n' > "$sandbox/service.pid"
  : > "$sandbox/nc-results"
  rm -f -- "$sandbox/nc-index"
  : > "$sandbox/mock-nc.log"
  : > "$sandbox/mock-systemctl.log"
  : > "$sandbox/mock-journal.log"
  : > "$sandbox/mock-listener.log"
  : > "$sandbox/mock-haproxy.log"
  : > "$sandbox/mock-crash.log"
  : > "$sandbox/mock-sudo.log"
  configured_ca_bundle="$sandbox/home/.config/test-trust/corp-ca-bundle.pem"
}

set_nc_results() {
  printf '%s\n' "$@" > "$sandbox/nc-results"
  rm -f -- "$sandbox/nc-index"
}

run_proxy() {
  local operation="${1:-status}"
  shift || true
  env -i \
    HOME="$sandbox/home" \
    PATH="$sandbox/mocks:/usr/bin:/bin" \
    LC_ALL=C \
    PROXY_TEST_ROOT="$sandbox" \
    PROXY_STATE="$sandbox/state/proxy-state" \
    DOCKER_CONFIG="$sandbox/docker" \
    PROXY_NC="$sandbox/mocks/nc" \
    PROXY_HOST="$corporate_proxy_host" \
    PROXY_PORT="$corporate_proxy_port" \
    PROXY_NO_PROXY="$default_no_proxy" \
    PROXY_HAPROXY_CONFIG="$sandbox/etc/haproxy.conf" \
    PROXY_ENDPOINT_SERVICE='proxy-test-haproxy.service' \
    PROXY_SYSTEMCTL="$sandbox/mocks/systemctl" \
    PROXY_JOURNAL_CONFIRM="$sandbox/mocks/journal-confirm" \
    PROXY_LISTENER_WAKEUP="$sandbox/mocks/listener-wakeup" \
    PROXY_CRASH_HOOK="$sandbox/mocks/crash-point" \
    PROXY_CA_BUNDLE="$configured_ca_bundle" \
    PROXY_HOST_ENDPOINT="$host_endpoint" \
    PROXY_DOCKER_ENDPOINT="$docker_endpoint" \
    PROXY_SUCCESS_THRESHOLD="$success_threshold" \
    PROXY_FAILURE_THRESHOLD="$failure_threshold" \
    PROXY_TEST_SYSTEMCTL_RESULT="${PROXY_TEST_SYSTEMCTL_RESULT:-ok}" \
    PROXY_TEST_JOURNAL_RESULT="${PROXY_TEST_JOURNAL_RESULT:-ok}" \
    PROXY_TEST_LISTENER_RESULT="${PROXY_TEST_LISTENER_RESULT:-ok}" \
    PROXY_TEST_CRASH_AT="${PROXY_TEST_CRASH_AT:-never}" \
    /usr/bin/timeout -k 1s 8s /usr/bin/bash "$target" "$operation" "$@" > "$sandbox/last.stdout" 2> "$sandbox/last.stderr"
  proxy_rc=$?
}

run_proxy_background() {
  local operation="$1" output="$2"
  (
    run_proxy "$operation"
    printf '%s\n' "$proxy_rc" > "$output.rc"
  ) > "$output.stdout" 2> "$output.stderr" &
  concurrent_pids+=("$!")
}

require_injected_contract() {
  local source hook default_pattern missing=0
  local -a hooks=(
    PROXY_HAPROXY_CONFIG PROXY_ENDPOINT_SERVICE PROXY_SYSTEMCTL PROXY_LISTENER_WAKEUP
    PROXY_HOST_ENDPOINT PROXY_DOCKER_ENDPOINT PROXY_SUCCESS_THRESHOLD
    PROXY_FAILURE_THRESHOLD PROXY_CA_BUNDLE
  )

  if [[ ! -f "$target" || ! -x "$target" ]]; then
    fail 'target must be an executable file'
    return
  fi
  source=$(<"$target")
  for hook in "${hooks[@]}"; do
    default_pattern="\${${hook}:-"
    if [[ "$source" != *"$hook"* || "$source" != *"$default_pattern"* ]]; then
      fail "target must expose a defaulted $hook injection hook"
      missing=1
    else
      pass
    fi
  done
  (( missing == 0 )) || return 0
}

require_host_safe_management_policy() {
  local line line_number=0 policy_failed=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    case "$line" in
      *'/etc/systemd/'*|*'/etc/haproxy/'*|*'docker.service.d'*|*'daemon-reload'*|*'sudo systemctl '*|*'sudo service '*)
        fail "target line $line_number manages recurring root-owned services"
        policy_failed=1
        ;;
      *'systemctl start '*|*'systemctl stop '*|*'systemctl restart '*|*'systemctl enable '*|*'systemctl disable '*)
        if [[ "$line" != *'--user'* && "$line" != *'PROXY_SYSTEMCTL'* ]]; then
          fail "target line $line_number manages a non-user service"
          policy_failed=1
        fi
        ;;
    esac
  done < "$target"
  (( policy_failed == 0 )) && pass
}

state_path() { printf '%s\n' "$sandbox/state/proxy-state"; }
config_path() { printf '%s\n' "$sandbox/etc/haproxy.conf"; }
pending_path() { printf '%s.pending\n' "$(state_path)"; }

assert_shell_state() {
  local expected_route="$1" state marker="$sandbox/source-marker"
  state=$(state_path)
  rm -f -- "$marker"
  if [[ ! -f "$state" ]] || ! env -i HOME="$sandbox/home" /usr/bin/timeout 3s /usr/bin/bash -c '
    source "$1"
    [[ "$http_proxy" == "http://127.0.0.1:18080" ]]
    [[ "$https_proxy" == "http://127.0.0.1:18080" ]]
    [[ "$HTTP_PROXY" == "http://127.0.0.1:18080" ]]
    [[ "$HTTPS_PROXY" == "http://127.0.0.1:18080" ]]
    [[ "$REQUESTS_CA_BUNDLE" == "$2" && "$SSL_CERT_FILE" == "$2" ]]
    [[ "$PROXY_EFFECTIVE" == "$3" ]]
    [[ "$PROXY_SUCCESS_COUNT" =~ ^[0-9]+$ ]]
    [[ "$PROXY_FAILURE_COUNT" =~ ^[0-9]+$ ]]
  ' bash "$state" "$configured_ca_bundle" "$expected_route" || [[ -e "$marker" ]]; then
    fail "state for $expected_route must source safely with permanent local proxy and CA exports"
  else
    pass
  fi
}

assert_counter() {
  local name="$1" expected="$2"
  assert_file_contains "$(state_path)" "$name=$expected" "$name must equal $expected"
}

assert_route_config() {
  local expected="$1"
  assert_file_contains "$(config_path)" 'mode tcp' 'frontend must preserve TCP bytes'
  assert_file_contains "$(config_path)" 'bind 127.0.0.1:18080' 'loopback listener required'
  assert_file_contains "$(config_path)" 'bind 192.168.20.5:18080' 'Docker listener required'
  assert_file_contains "$(config_path)" 'tcp-request connection reject if !allowed_client' 'source ACL required'
  /usr/bin/python3 - "$(config_path)" "$expected" <<'PY'
import sys
lines=[x.strip() for x in open(sys.argv[1])]
assert [x for x in lines if x.startswith('bind ')] == ['bind 127.0.0.1:18080', 'bind 192.168.20.5:18080']
servers=[x for x in lines if x.startswith('server ')]
assert len(servers)==1 and servers[0].startswith(sys.argv[2])
assert not any(x.startswith(('http-request ', 'http-response ', 'option http', 'upstream ')) for x in lines)
PY
  [[ "$?" == 0 ]] && pass || fail 'exact TCP listeners and exactly one selected backend required'
}
assert_direct_config() { assert_route_config 'server direct 127.0.0.1:18081'; }
assert_corporate_config() { assert_route_config "server corporate $corporate_proxy_host:$corporate_proxy_port resolvers wsl"; }

assert_docker_unchanged() {
  local expected="$1" docker="$sandbox/docker/config.json"
  assert_file_equals "$docker" "$expected" 'route transitions must not rewrite unrelated Docker JSON'
}

prepare_unrelated_docker_json() {
  local docker="$sandbox/docker/config.json" fixture='{"auths":{"registry.invalid":{"auth":"opaque"}},"credsStore":"pass","stackOrchestrator":"swarm"}'
  mkdir -p -- "$(dirname -- "$docker")"
  printf '%s' "$fixture" > "$docker"
  printf '%s' "$fixture"
}

assert_reload_confirmed() {
  if [[ $(<"$sandbox/mock-systemctl.log") == *'--user reload proxy-test-haproxy.service'* && -s "$sandbox/mock-listener.log" ]]; then
    pass
  else
    fail 'route changes must use synchronous user-service reload and listener verification'
  fi
}

assert_no_host_management() {
  [[ ! -s "$sandbox/mock-sudo.log" ]] && pass || fail 'test run must never invoke sudo'
}

assert_no_pending_intent() {
  [[ ! -e "$(pending_path)" ]] && pass || fail "$1"
}

assert_nonblocking_restart_fallback() {
  local line index restart_index no_block_index service_index reload_seen=0 restart_seen=0
  local -a arguments=()

  while IFS= read -r line || [[ -n "$line" ]]; do
    read -r -a arguments <<< "$line"
    restart_index=-1
    no_block_index=-1
    service_index=-1
    for index in "${!arguments[@]}"; do
      case "${arguments[index]}" in
        reload) reload_seen=1 ;;
        restart) restart_index=$index ;;
        --no-block) no_block_index=$index ;;
        proxy-test-haproxy.service) service_index=$index ;;
      esac
    done
    if (( restart_index >= 0 && no_block_index >= 0 && service_index > restart_index )); then
      restart_seen=1
    fi
  done < "$sandbox/mock-systemctl.log"

  if (( reload_seen == 1 && restart_seen == 1 )); then
    pass
  else
    fail 'canonical recovery fallback must invoke injected systemctl restart --no-block for the HAProxy user service'
  fi
}

test_legacy_cli_is_safe() {
  reset_sandbox
  run_proxy init
  assert_rc 0 'init compatibility command must be inert'
  [[ ! -e "$(state_path)" && ! -e "$(config_path)" && ! -e "$sandbox/docker/config.json" ]] && pass || fail 'init must not create route, state, or Docker files'
  run_proxy help
  assert_rc 0 'help must succeed'
  assert_file_contains "$sandbox/last.stdout" 'Usage:' 'help must retain CLI usage output'
  run_proxy not-a-command
  assert_rc 2 'unknown commands must retain exit status 2'
}

test_manual_modes_and_source_state() {
  local docker_before
  reset_sandbox
  docker_before=$(prepare_unrelated_docker_json)

  run_proxy off
  assert_rc 0 'manual off must select the direct route'
  assert_file_contains "$(state_path)" 'PROXY_MODE=force-off' 'manual off must persist force-off mode'
  assert_shell_state off
  assert_direct_config
  assert_docker_unchanged "$docker_before"

  run_proxy on
  assert_rc 0 'manual on must select the corporate route'
  assert_file_contains "$(state_path)" 'PROXY_MODE=force-on' 'manual on must persist force-on mode'
  assert_shell_state on
  assert_corporate_config
  assert_reload_confirmed
  assert_docker_unchanged "$docker_before"

  run_proxy toggle
  assert_rc 0 'toggle must select direct from corporate'
  assert_file_contains "$(state_path)" 'PROXY_MODE=force-off' 'toggle must persist the selected manual mode'
  assert_direct_config
  assert_shell_state off
  assert_docker_unchanged "$docker_before"
}

test_auto_hysteresis_and_resets() {
  local docker_before
  reset_sandbox
  docker_before=$(prepare_unrelated_docker_json)
  run_proxy off
  assert_rc 0 'auto hysteresis setup must create the direct route'
  run_proxy auto
  assert_rc 0 'auto must be selectable without a probe'
  assert_file_contains "$(state_path)" 'PROXY_MODE=auto' 'auto mode must persist'

  set_nc_results ok ok
  run_proxy check
  assert_rc 0 'first successful auto probe must succeed'
  assert_shell_state off
  assert_counter PROXY_SUCCESS_COUNT 1
  assert_counter PROXY_FAILURE_COUNT 0
  run_proxy check
  assert_rc 0 'second successful auto probe must succeed'
  assert_shell_state on
  assert_corporate_config
  assert_counter PROXY_SUCCESS_COUNT "$success_threshold"

  set_nc_results fail
  run_proxy check
  assert_rc 0 'opposing failure must reset a successful streak'
  assert_shell_state on
  assert_counter PROXY_SUCCESS_COUNT 0
  assert_counter PROXY_FAILURE_COUNT 1

  set_nc_results fail fail
  run_proxy check
  assert_shell_state on
  assert_counter PROXY_FAILURE_COUNT 2
  run_proxy check
  assert_rc 0 'third failed auto probe must select direct'
  assert_shell_state off
  assert_direct_config
  assert_counter PROXY_FAILURE_COUNT "$failure_threshold"

  set_nc_results ok
  run_proxy check
  assert_rc 0 'opposing success must reset a failed streak'
  assert_shell_state off
  assert_counter PROXY_FAILURE_COUNT 0
  assert_counter PROXY_SUCCESS_COUNT 1
  assert_docker_unchanged "$docker_before"
  assert_file_contains "$sandbox/mock-nc.log" '-z' 'automatic checks must use the injected nc TCP probe'
}

test_saturated_counters_do_not_rewrite() {
  local before_state before_config after_state after_config before_identity after_identity
  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy on
  run_proxy auto
  set_nc_results fail fail fail
  run_proxy check; run_proxy check; run_proxy check
  assert_shell_state off
  if [[ ! -f "$(state_path)" || ! -f "$(config_path)" ]]; then
    fail 'failure-saturation setup must leave canonical state and HAProxy config'
    return
  fi
  before_state=$(<"$(state_path)")
  before_config=$(<"$(config_path)")
  before_identity=$(stat -c '%i:%s:%Y' "$(state_path)" "$(config_path)")
  set_nc_results fail fail
  run_proxy check; run_proxy check
  after_state=$(<"$(state_path)")
  after_config=$(<"$(config_path)")
  after_identity=$(stat -c '%i:%s:%Y' "$(state_path)" "$(config_path)")
  if [[ "$before_state" == "$after_state" && "$before_config" == "$after_config" && "$before_identity" == "$after_identity" ]]; then
    pass
  else
    fail 'saturated failure counter must avoid state/config rewrites'
  fi

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy off
  run_proxy auto
  set_nc_results ok ok
  run_proxy check; run_proxy check
  assert_shell_state on
  if [[ ! -f "$(state_path)" || ! -f "$(config_path)" ]]; then
    fail 'success-saturation setup must leave canonical state and HAProxy config'
    return
  fi
  before_state=$(<"$(state_path)")
  before_config=$(<"$(config_path)")
  before_identity=$(stat -c '%i:%s:%Y' "$(state_path)" "$(config_path)")
  set_nc_results ok ok
  run_proxy check; run_proxy check
  after_state=$(<"$(state_path)")
  after_config=$(<"$(config_path)")
  after_identity=$(stat -c '%i:%s:%Y' "$(state_path)" "$(config_path)")
  if [[ "$before_state" == "$after_state" && "$before_config" == "$after_config" && "$before_identity" == "$after_identity" ]]; then
    pass
  else
    fail 'saturated success counter must avoid state/config rewrites'
  fi
}

test_pending_retry_cancellation_and_crash_recovery() {
  local pending docker_before
  reset_sandbox
  docker_before=$(prepare_unrelated_docker_json)
  run_proxy off
  PROXY_TEST_SYSTEMCTL_RESULT=fail run_proxy on
  assert_nonzero 'failed reload must fail the route request'
  pending=$(pending_path)
  assert_file_contains "$pending" 'PROXY_TARGET=on' 'failed reload must retain an on pending record'
  assert_direct_config
  assert_docker_unchanged "$docker_before"
  PROXY_TEST_SYSTEMCTL_RESULT=ok run_proxy check
  assert_rc 0 'check must retry a pending route after reload recovery'
  assert_shell_state on
  [[ ! -e "$pending" ]] && pass || fail 'successful pending retry must clear pending record'

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy off
  PROXY_TEST_SYSTEMCTL_RESULT=fail run_proxy on
  run_proxy auto
  assert_rc 0 'auto must cancel a failed manual pending request'
  [[ ! -e "$(pending_path)" ]] && pass || fail 'auto must cancel pending manual intent'
  assert_shell_state off
  assert_direct_config

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy off
  PROXY_TEST_CRASH_AT=after-pending run_proxy on
  assert_nonzero 'injected after-pending crash must interrupt a route apply'
  assert_file_contains "$(pending_path)" 'PROXY_TARGET=on' 'crash point must leave recoverable pending intent'
  PROXY_TEST_CRASH_AT=never run_proxy check
  assert_rc 0 'check must recover a pending intent after injected crash'
  assert_shell_state on
}

test_explicit_modes_supersede_pending_intents() {
  local pending

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy off
  assert_rc 0 'force-off setup must establish canonical direct routing'
  PROXY_TEST_SYSTEMCTL_RESULT=fail run_proxy on
  assert_nonzero 'failed force-on over canonical off must retain pending intent'
  pending=$(pending_path)
  assert_file_contains "$pending" 'PROXY_TARGET=on' 'failed force-on must record pending on over canonical off'
  run_proxy off
  assert_rc 0 'explicit force-off must supersede pending on'
  assert_no_pending_intent 'explicit force-off must clear stale pending on'
  run_proxy check
  assert_rc 0 'check after explicit force-off must succeed'
  assert_file_contains "$(state_path)" 'PROXY_EFFECTIVE=off' 'check must not apply stale pending on after explicit force-off'

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy on
  assert_rc 0 'force-on setup must establish canonical corporate routing'
  PROXY_TEST_SYSTEMCTL_RESULT=fail run_proxy off
  assert_nonzero 'failed force-off over canonical on must retain pending intent'
  pending=$(pending_path)
  assert_file_contains "$pending" 'PROXY_TARGET=off' 'failed force-off must record pending off over canonical on'
  run_proxy on
  assert_rc 0 'explicit force-on must supersede pending off'
  assert_no_pending_intent 'explicit force-on must clear stale pending off'
  run_proxy check
  assert_rc 0 'check after explicit force-on must succeed'
  assert_file_contains "$(state_path)" 'PROXY_EFFECTIVE=on' 'check must not apply stale pending off after explicit force-on'
}

test_malformed_records_and_source_safety() {
  local state pending marker before_state
  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  state=$(state_path)
  printf '%s\n' 'PROXY_MODE=auto' 'PROXY_MODE=force-on' 'PROXY_EFFECTIVE=off' > "$state"
  before_state=$(<"$state")
  run_proxy status
  assert_nonzero 'malformed duplicate state must be rejected read-only'
  assert_file_equals "$state" "$before_state" 'malformed state must not be rewritten by status'

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy off
  pending=$(pending_path)
  marker="$sandbox/pending-executed"
  printf 'PROXY_TARGET=on; touch %q\n' "$marker" > "$pending"
  run_proxy check
  assert_nonzero 'malformed pending record must be rejected'
  [[ ! -e "$marker" ]] && pass || fail 'pending records must never be sourced as shell'

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  configured_ca_bundle="$sandbox/home/ca bundle;\$(touch $sandbox/source-executed)"
  run_proxy off
  assert_rc 0 'quoted injected CA path must be accepted'
  assert_shell_state off
  [[ ! -e "$sandbox/source-executed" ]] && pass || fail 'generated state must quote injected values when sourced'
}

test_missing_success_counter_is_rejected_read_only() {
  local state before_state

  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  state=$(state_path)
  cat > "$state" <<EOF
PROXY_MODE=auto
PROXY_DETECTED=off
PROXY_EFFECTIVE=off
PROXY_FAILURE_COUNT=0
export REQUESTS_CA_BUNDLE=$(printf '%q' "$configured_ca_bundle")
export SSL_CERT_FILE=$(printf '%q' "$configured_ca_bundle")
export HTTP_PROXY=$(printf '%q' "$host_endpoint")
export HTTPS_PROXY=$(printf '%q' "$host_endpoint")
export http_proxy=$(printf '%q' "$host_endpoint")
export https_proxy=$(printf '%q' "$host_endpoint")
export NO_PROXY=$(printf '%q' "$default_no_proxy")
export no_proxy=$(printf '%q' "$default_no_proxy")
EOF
  before_state=$(<"$state")
  run_proxy status
  assert_nonzero 'canonical metadata without PROXY_SUCCESS_COUNT must be rejected read-only'
  assert_file_equals "$state" "$before_state" 'missing-success metadata must not be rewritten by status'
}

test_status_is_read_only() {
  local state_before config_before docker_before output
  reset_sandbox
  docker_before=$(prepare_unrelated_docker_json)
  run_proxy off
  if [[ ! -f "$(state_path)" || ! -f "$(config_path)" ]]; then
    fail 'read-only command setup must leave canonical direct state and config'
    return
  fi
  state_before=$(<"$(state_path)")
  config_before=$(<"$(config_path)")
  run_proxy status
  assert_rc 0 'status must succeed'
  output=$(<"$sandbox/last.stdout")
  [[ "$output" == *'route:'* && "$output" == *'service:'* && "$output" == *'pending:'* && "$output" == *'successes:'* && "$output" == *'failures:'* ]] && pass || fail 'status must report route, service, pending, and both counters'
  assert_file_equals "$(state_path)" "$state_before" 'status must not rewrite state'
  assert_file_equals "$(config_path)" "$config_before" 'status must not rewrite config'
  assert_docker_unchanged "$docker_before"

}

test_reload_rollback() {
  local cause docker_before canonical
  for cause in systemctl timeout pid-change; do
    reset_sandbox
    docker_before=$(prepare_unrelated_docker_json)
    run_proxy off
    if [[ ! -f "$(config_path)" ]]; then
      fail "$cause rollback setup must leave canonical direct config"
      continue
    fi
    canonical=$(<"$(config_path)")
    case "$cause" in
      systemctl) PROXY_TEST_SYSTEMCTL_RESULT=fail run_proxy on ;;
      timeout) PROXY_TEST_JOURNAL_RESULT=timeout run_proxy on ;;
      pid-change) PROXY_TEST_JOURNAL_RESULT=pid-change run_proxy on ;;
    esac
    assert_nonzero "$cause reload confirmation failure must fail the route request"
    assert_file_equals "$(config_path)" "$canonical" "$cause reload failure must roll back canonical direct config"
    assert_docker_unchanged "$docker_before"
    assert_file_contains "$(pending_path)" 'PROXY_TARGET=on' "$cause rollback must preserve retryable pending intent"
  done
}

test_restart_fallback_is_nonblocking() {
  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  run_proxy off
  assert_rc 0 'restart-fallback setup must establish canonical direct routing'
  PROXY_TEST_JOURNAL_RESULT=timeout run_proxy on
  assert_nonzero 'timed-out reload confirmation must fail the route request'
  assert_nonblocking_restart_fallback
}

test_concurrent_operations() {
  local operation pid concurrent_failed=0
  local -a concurrent_pids=()
  reset_sandbox
  prepare_unrelated_docker_json >/dev/null
  mkdir -p "$sandbox/concurrent"
  for operation in on off toggle auto on toggle off; do
    run_proxy_background "$operation" "$sandbox/concurrent/$operation-${#concurrent_pids[@]}"
  done
  for pid in "${concurrent_pids[@]}"; do
    wait "$pid" || concurrent_failed=1
  done
  (( concurrent_failed == 0 )) && pass || fail 'concurrent operations must serialize without timeout failures'
  assert_shell_state "$(grep_effective_route)"
  if [[ -f "$(config_path)" ]]; then
    pass
  else
    fail 'concurrent operations must leave a canonical HAProxy config'
  fi
}

grep_effective_route() {
  local state
  state=$(state_path)
  if [[ -f "$state" && $(<"$state") == *'PROXY_EFFECTIVE=on'* ]]; then
    printf 'on\n'
  else
    printf 'off\n'
  fi
}

main() {
  require_injected_contract
  require_host_safe_management_policy
  sandbox=$(mktemp -d "${TMPDIR:-/tmp}/proxy-test.XXXXXX")
  setup_mocks

  test_legacy_cli_is_safe
  test_manual_modes_and_source_state
  test_auto_hysteresis_and_resets
  test_saturated_counters_do_not_rewrite
  test_pending_retry_cancellation_and_crash_recovery
  test_explicit_modes_supersede_pending_intents
  test_malformed_records_and_source_safety
  test_missing_success_counter_is_rejected_read_only
  test_status_is_read_only
  test_reload_rollback
  test_restart_fallback_is_nonblocking
  test_concurrent_operations
  assert_no_host_management

  if (( failures > 0 )); then
    printf 'proxy-test: %d failure(s), %d checks passed\n' "$failures" "$checks" >&2
    return 1
  fi
  printf 'proxy-test: %d checks passed\n' "$checks"
}

main "$@"
