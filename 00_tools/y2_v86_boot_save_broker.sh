#!/system/bin/sh

BUILD="y2-v86-boot-save-repair"
PROTOCOL_VERSION="3"
CONTENT="/system/bin/content"
REQUEST_URI="content://org.rockbox.y2.bootroutes/request"
RESPONSE_URI="content://org.rockbox.y2.bootroutes/response"
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

query_request() {
    QUERY_OUTPUT=$("$CONTENT" query --uri "$REQUEST_URI" 2>&1)
    QUERY_EXIT=$?
    if [ "$QUERY_EXIT" -ne 0 ]; then
        QUERY_ERROR="content-query-exit-$QUERY_EXIT output=$QUERY_OUTPUT"
        return 1
    fi
    case "$QUERY_OUTPUT" in
        ""|*"No result found."*)
            QUERY_HAS_REQUEST=0
            return 0
            ;;
        *"Row:"*"protocol_version="*"boot_id="*"request_id="*"normal_boot="*"reboot="*)
            QUERY_HAS_REQUEST=1
            return 0
            ;;
        *)
            QUERY_ERROR="unexpected-content-output output=$QUERY_OUTPUT"
            return 1
            ;;
    esac
}

write_response() {
    RESPONSE_STATUS="$1"
    RESPONSE_OUTPUT=$("$CONTENT" insert --uri "$RESPONSE_URI" \
        --bind "protocol_version:s:$PROTOCOL_VERSION" \
        --bind "boot_id:s:$EXPECTED_BOOT_ID" \
        --bind "request_id:s:$REQUEST_ID" \
        --bind "status:s:$RESPONSE_STATUS" 2>&1)
    RESPONSE_EXIT=$?
    if [ "$RESPONSE_EXIT" -ne 0 ]; then
        return 1
    fi
    case "$RESPONSE_OUTPUT" in
        *"Error while accessing provider:"*|*"Exception"*)
            return 1
            ;;
    esac
    return 0
}

CURRENT_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
if [ -z "$EXPECTED_BOOT_ID" ] ||
   [ "$EXPECTED_BOOT_ID" = "noid" ] ||
   [ "$CURRENT_BOOT_ID" != "$EXPECTED_BOOT_ID" ]; then
    log_event "save_broker=rejected reason=boot-id-mismatch expected=$EXPECTED_BOOT_ID current=$CURRENT_BOOT_ID"
    exit 3
fi

case "$ACTION" in
    ready)
        if ! query_request; then
            log_event "save_broker=health-failed reason=$QUERY_ERROR"
            exit 4
        fi
        log_event "save_broker=ready health=provider-query-ok protocol=$PROTOCOL_VERSION boot_id=$EXPECTED_BOOT_ID route=$ROUTE request_waiting=$QUERY_HAS_REQUEST"
        exit 0
        ;;
    poll)
        ;;
    *)
        log_event "save_broker=rejected reason=invalid-helper-action action=$ACTION"
        exit 2
        ;;
esac

if ! query_request; then
    log_event "save_broker=query-failed reason=$QUERY_ERROR"
    exit 4
fi
if [ "$QUERY_HAS_REQUEST" -ne 1 ]; then
    exit 0
fi

query_value protocol_version
REQUEST_PROTOCOL="$QUERY_VALUE"
query_value boot_id
REQUEST_BOOT_ID="$QUERY_VALUE"
query_value request_id
REQUEST_ID="$QUERY_VALUE"
query_value normal_boot
REQUEST_NORMAL="$QUERY_VALUE"
query_value reboot
REQUEST_REBOOT="$QUERY_VALUE"

REQUEST_VALID=1
[ "$REQUEST_PROTOCOL" = "$PROTOCOL_VERSION" ] || REQUEST_VALID=0
[ "$REQUEST_BOOT_ID" = "$EXPECTED_BOOT_ID" ] || REQUEST_VALID=0
[ "$REQUEST_REBOOT" = "1" ] || REQUEST_VALID=0
case "$REQUEST_ID" in
    ""|*[!0-9]*) REQUEST_VALID=0 ;;
esac
case "$REQUEST_NORMAL" in
    rockbox)
        REQUEST_UP="stock"
        ;;
    stock)
        REQUEST_UP="rockbox"
        ;;
    *)
        REQUEST_VALID=0
        REQUEST_UP=""
        ;;
esac
REQUEST_DOWN="settings"

if [ "$REQUEST_VALID" -ne 1 ]; then
    write_response error-invalid-request
    log_event "save_broker=rejected request_id=$REQUEST_ID reason=invalid-request protocol=$REQUEST_PROTOCOL request_boot_id=$REQUEST_BOOT_ID normal_boot=$REQUEST_NORMAL"
    exit 6
fi

log_event "save_broker=received request_id=$REQUEST_ID normal_boot=$REQUEST_NORMAL derived_volume_up=$REQUEST_UP fixed_volume_down=$REQUEST_DOWN"
ROUTE_MAP_TMP="$ROUTE_MAP_FILE.tmp.$$"
if umask 077 &&
   printf '%s\n' 'version=1' "no_button=$REQUEST_NORMAL" \
       "volume_up=$REQUEST_UP" "volume_down=$REQUEST_DOWN" \
       > "$ROUTE_MAP_TMP" &&
   chmod 0600 "$ROUTE_MAP_TMP" &&
   mv "$ROUTE_MAP_TMP" "$ROUTE_MAP_FILE"; then
    VERIFY_VERSION=$(read_kv "$ROUTE_MAP_FILE" version)
    VERIFY_NO=$(read_kv "$ROUTE_MAP_FILE" no_button)
    VERIFY_UP=$(read_kv "$ROUTE_MAP_FILE" volume_up)
    VERIFY_DOWN=$(read_kv "$ROUTE_MAP_FILE" volume_down)
    if [ "$VERIFY_VERSION" = "1" ] &&
       [ "$VERIFY_NO" = "$REQUEST_NORMAL" ] &&
       [ "$VERIFY_UP" = "$REQUEST_UP" ] &&
       [ "$VERIFY_DOWN" = "$REQUEST_DOWN" ]; then
        log_event "save_broker=verified request_id=$REQUEST_ID no_button=$VERIFY_NO volume_up=$VERIFY_UP volume_down=$VERIFY_DOWN"
        sync
        if write_response ok; then
            log_event "save_broker=acknowledged request_id=$REQUEST_ID status=ok"
            sync
            sleep 2
            log_event "save_broker=reboot request_id=$REQUEST_ID"
            sync
            reboot
        else
            log_event "save_broker=rejected request_id=$REQUEST_ID reason=response-write-failed exit=$RESPONSE_EXIT output=$RESPONSE_OUTPUT"
            exit 7
        fi
        exit 0
    fi
    write_response error-verify-failed
    log_event "save_broker=rejected request_id=$REQUEST_ID reason=verify-failed verify_no=$VERIFY_NO verify_up=$VERIFY_UP verify_down=$VERIFY_DOWN"
    exit 8
fi

rm -f "$ROUTE_MAP_TMP"
write_response error-write-failed
log_event "save_broker=rejected request_id=$REQUEST_ID reason=write-failed"
exit 9
