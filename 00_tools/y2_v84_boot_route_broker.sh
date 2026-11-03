#!/system/bin/sh

BUILD="y2-v84-coherent-boot-settings"
PROTOCOL_VERSION="2"
CONTENT="/system/bin/content"
REQUEST_URI="content://org.rockbox.y2.bootroutes/request"
RESPONSE_URI="content://org.rockbox.y2.bootroutes/response"
STATUS_URI="content://org.rockbox.y2.bootroutes/status"
ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"

ACTION="$1"
ROUTE="$2"
EXPECTED_BOOT_ID="$3"
LOG="$4"

log_event() {
    printf '%s\n' "build=$BUILD date=$(date 2>/dev/null) uptime=$(cat /proc/uptime 2>/dev/null) $*" >> "$LOG"
    chmod 0644 "$LOG"
}

read_kv() {
    READ_FILE="$1"
    READ_KEY="$2"
    READ_VALUE=""
    while IFS= read -r READ_LINE || [ -n "$READ_LINE" ]; do
        case "$READ_LINE" in
            "$READ_KEY="*)
                READ_VALUE=${READ_LINE#*=}
                break
                ;;
        esac
    done < "$READ_FILE"
    printf '%s' "$READ_VALUE"
}

query_value() {
    QUERY_KEY="$1"
    QUERY_REMAINDER=${QUERY_OUTPUT#*"$QUERY_KEY="}
    if [ "$QUERY_REMAINDER" = "$QUERY_OUTPUT" ]; then
        QUERY_VALUE=""
        return
    fi
    QUERY_VALUE=${QUERY_REMAINDER%%,*}
}

write_response() {
    RESPONSE_STATUS="$1"
    RESPONSE_OUTPUT=$("$CONTENT" insert --uri "$RESPONSE_URI" \
        --bind "protocol_version:s:$PROTOCOL_VERSION" \
        --bind "broker_build:s:$BUILD" \
        --bind "boot_id:s:$EXPECTED_BOOT_ID" \
        --bind "request_id:s:$REQUEST_ID" \
        --bind "status:s:$RESPONSE_STATUS" 2>&1)
    RESPONSE_EXIT=$?
    [ "$RESPONSE_EXIT" -eq 0 ]
}

CURRENT_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -z "$EXPECTED_BOOT_ID" ] ||
   [ "$EXPECTED_BOOT_ID" = "noid" ] ||
   [ "$CURRENT_BOOT_ID" != "$EXPECTED_BOOT_ID" ]; then
    log_event "settings_broker=rejected reason=boot-id-mismatch expected=$EXPECTED_BOOT_ID current=$CURRENT_BOOT_ID"
    exit 3
fi

case "$ACTION" in
    ready)
        STATUS_OUTPUT=$("$CONTENT" insert --uri "$STATUS_URI" \
            --bind "protocol_version:s:$PROTOCOL_VERSION" \
            --bind "broker_build:s:$BUILD" \
            --bind "boot_id:s:$EXPECTED_BOOT_ID" 2>&1)
        STATUS_EXIT=$?
        if [ "$STATUS_EXIT" -ne 0 ]; then
            printf '%s\n' "$STATUS_OUTPUT"
            exit "$STATUS_EXIT"
        fi
        log_event "settings_broker=ready transport=system-helper protocol=$PROTOCOL_VERSION boot_id=$EXPECTED_BOOT_ID route=$ROUTE"
        exit 0
        ;;
    poll)
        ;;
    *)
        log_event "settings_broker=rejected reason=invalid-helper-action action=$ACTION"
        exit 2
        ;;
esac

QUERY_OUTPUT=$("$CONTENT" query --uri "$REQUEST_URI" 2>&1)
QUERY_EXIT=$?
if [ "$QUERY_EXIT" -ne 0 ]; then
    log_event "settings_broker=query-failed transport=system-helper exit=$QUERY_EXIT output=$QUERY_OUTPUT"
    exit 4
fi
case "$QUERY_OUTPUT" in
    ""|*"No result found."*)
        exit 0
        ;;
    *"protocol_version="*"broker_build="*"boot_id="*"request_id="*"no_button="*"volume_up="*"volume_down="*"reboot="*)
        ;;
    *)
        QUARANTINE_OUTPUT=$("$CONTENT" delete --uri "$REQUEST_URI" 2>&1)
        QUARANTINE_EXIT=$?
        log_event "settings_broker=rejected reason=malformed-provider-output query_exit=$QUERY_EXIT quarantine_exit=$QUARANTINE_EXIT"
        exit 5
        ;;
esac

query_value protocol_version
REQUEST_PROTOCOL="$QUERY_VALUE"
query_value broker_build
REQUEST_BUILD="$QUERY_VALUE"
query_value boot_id
REQUEST_BOOT_ID="$QUERY_VALUE"
query_value request_id
REQUEST_ID="$QUERY_VALUE"
query_value no_button
REQUEST_NO="$QUERY_VALUE"
query_value volume_up
REQUEST_UP="$QUERY_VALUE"
query_value volume_down
REQUEST_DOWN="$QUERY_VALUE"
query_value reboot
REQUEST_REBOOT="$QUERY_VALUE"

REQUEST_VALID=1
[ "$REQUEST_PROTOCOL" = "$PROTOCOL_VERSION" ] || REQUEST_VALID=0
[ "$REQUEST_BUILD" = "$BUILD" ] || REQUEST_VALID=0
[ "$REQUEST_BOOT_ID" = "$EXPECTED_BOOT_ID" ] || REQUEST_VALID=0
case "$REQUEST_ID" in
    ""|*[!0-9]*) REQUEST_VALID=0 ;;
esac
for REQUEST_VALUE in "$REQUEST_NO" "$REQUEST_UP" "$REQUEST_DOWN"; do
    case "$REQUEST_VALUE" in
        rockbox|stock|settings) ;;
        *) REQUEST_VALID=0 ;;
    esac
done
if [ "$REQUEST_NO" = "$REQUEST_UP" ] ||
   [ "$REQUEST_NO" = "$REQUEST_DOWN" ] ||
   [ "$REQUEST_UP" = "$REQUEST_DOWN" ]; then
    REQUEST_VALID=0
fi
if [ "$REQUEST_NO" != "settings" ] &&
   [ "$REQUEST_UP" != "settings" ] &&
   [ "$REQUEST_DOWN" != "settings" ]; then
    REQUEST_VALID=0
fi
if [ "$REQUEST_VALID" -ne 1 ]; then
    write_response error-invalid-request
    log_event "settings_broker=rejected request_id=$REQUEST_ID reason=invalid-request protocol=$REQUEST_PROTOCOL request_build=$REQUEST_BUILD request_boot_id=$REQUEST_BOOT_ID"
    exit 6
fi

log_event "settings_broker=received request_id=$REQUEST_ID route=$ROUTE transport=system-helper protocol=$REQUEST_PROTOCOL boot_id=$REQUEST_BOOT_ID fields=valid"
ROUTE_MAP_TMP="$ROUTE_MAP_FILE.tmp.$$"
if umask 077 &&
   printf '%s\n' 'version=1' "no_button=$REQUEST_NO" \
       "volume_up=$REQUEST_UP" "volume_down=$REQUEST_DOWN" > "$ROUTE_MAP_TMP" &&
   chmod 0600 "$ROUTE_MAP_TMP" &&
   mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"; then
    VERIFY_VERSION=$(read_kv "$ROUTE_MAP_FILE" version)
    VERIFY_NO=$(read_kv "$ROUTE_MAP_FILE" no_button)
    VERIFY_UP=$(read_kv "$ROUTE_MAP_FILE" volume_up)
    VERIFY_DOWN=$(read_kv "$ROUTE_MAP_FILE" volume_down)
    if [ "$VERIFY_VERSION" = "1" ] &&
       [ "$VERIFY_NO" = "$REQUEST_NO" ] &&
       [ "$VERIFY_UP" = "$REQUEST_UP" ] &&
       [ "$VERIFY_DOWN" = "$REQUEST_DOWN" ]; then
        log_event "settings_broker=verified request_id=$REQUEST_ID no_button=$VERIFY_NO volume_up=$VERIFY_UP volume_down=$VERIFY_DOWN"
        sync
        if write_response ok; then
            log_event "settings_broker=acknowledged request_id=$REQUEST_ID status=ok"
            sync
            if [ "$REQUEST_REBOOT" = "1" ]; then
                sleep 2
                log_event "settings_broker=reboot request_id=$REQUEST_ID"
                sync
                reboot
            fi
        else
            log_event "settings_broker=rejected request_id=$REQUEST_ID reason=response-write-failed output=$RESPONSE_OUTPUT"
            exit 7
        fi
        exit 0
    fi
    write_response error-verify-failed
    log_event "settings_broker=rejected request_id=$REQUEST_ID reason=verify-failed verify_no=$VERIFY_NO verify_up=$VERIFY_UP verify_down=$VERIFY_DOWN"
    exit 8
fi

rm -f "$ROUTE_MAP_TMP"
write_response error-write-failed
log_event "settings_broker=rejected request_id=$REQUEST_ID reason=write-failed"
exit 9
