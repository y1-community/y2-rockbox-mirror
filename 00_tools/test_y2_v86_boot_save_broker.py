#!/usr/bin/env python3
"""Host-side behavioral tests for the V86 Android shell save broker."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "00_tools" / "y2_v86_boot_save_broker.sh"


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def run_broker(
        broker: Path,
        tools: Path,
        boot_id: str,
        log: Path,
        mode: str,
        action: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({
        "PATH": f"{tools}:{environment['PATH']}",
        "MOCK_CONTENT_MODE": mode,
        "MOCK_BOOT_ID": boot_id,
        "MOCK_RESPONSE_FILE": str(tools / "response.txt"),
        "MOCK_REBOOT_FILE": str(tools / "reboot.txt"),
    })
    return subprocess.run(
        ["bash", str(broker), action, "settings", boot_id, str(log)],
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
    )


def main() -> None:
    source = BROKER.read_text(encoding="utf-8")
    boot_id = Path(
        "/proc/sys/kernel/random/boot_id").read_text().strip()
    with tempfile.TemporaryDirectory(prefix="y2-v86-broker-test-") as raw:
        temp = Path(raw)
        tools = temp / "bin"
        tools.mkdir()
        route_map = temp / "y2_boot_routes.conf"
        test_broker = temp / "broker.sh"
        transformed = source.replace(
            'CONTENT="/system/bin/content"',
            f'CONTENT="{tools / "content"}"',
        ).replace(
            'ROUTE_MAP_FILE="/data/system/y2_boot_routes.conf"',
            f'ROUTE_MAP_FILE="{route_map}"',
        )
        write_executable(test_broker, transformed)
        write_executable(
            tools / "content",
            """#!/usr/bin/env bash
case "$1:$MOCK_CONTENT_MODE" in
    query:no-result)
        echo "No result found."
        exit 0
        ;;
    query:request-rockbox)
        echo "Row: 0 protocol_version=3, boot_id=$MOCK_BOOT_ID, request_id=12345, normal_boot=rockbox, reboot=1"
        exit 0
        ;;
    query:request-stock)
        echo "Row: 0 protocol_version=3, boot_id=$MOCK_BOOT_ID, request_id=67890, normal_boot=stock, reboot=1"
        exit 0
        ;;
    query:java-error)
        echo "Error while accessing provider:org.rockbox.y2.bootroutes" >&2
        echo "java.lang.IllegalStateException: provider unavailable" >&2
        exit 0
        ;;
    insert:*)
        printf '%s\n' "$*" > "$MOCK_RESPONSE_FILE"
        exit 0
        ;;
esac
exit 9
""",
        )
        write_executable(
            tools / "sleep",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        write_executable(
            tools / "reboot",
            """#!/usr/bin/env bash
printf '%s\n' rebooted > "$MOCK_REBOOT_FILE"
exit 0
""",
        )

        ready_log = temp / "ready.log"
        ready = run_broker(
            test_broker, tools, boot_id, ready_log, "no-result", "ready")
        assert ready.returncode == 0, ready.stderr
        assert "health=provider-query-ok" in ready_log.read_text()

        error_log = temp / "error.log"
        error = run_broker(
            test_broker, tools, boot_id, error_log, "java-error", "ready")
        assert error.returncode == 4, error.returncode
        assert "save_broker=health-failed" in error_log.read_text()

        rockbox_log = temp / "rockbox.log"
        rockbox = run_broker(
            test_broker, tools, boot_id, rockbox_log,
            "request-rockbox", "poll")
        assert rockbox.returncode == 0, rockbox.stderr
        assert route_map.read_text() == (
            "version=1\n"
            "no_button=rockbox\n"
            "volume_up=stock\n"
            "volume_down=settings\n"
        )
        assert "status:s:ok" in (tools / "response.txt").read_text()
        assert (tools / "reboot.txt").read_text().strip() == "rebooted"
        assert "save_broker=verified request_id=12345" in (
            rockbox_log.read_text())

        (tools / "response.txt").unlink()
        (tools / "reboot.txt").unlink()
        stock_log = temp / "stock.log"
        stock = run_broker(
            test_broker, tools, boot_id, stock_log,
            "request-stock", "poll")
        assert stock.returncode == 0, stock.stderr
        assert route_map.read_text() == (
            "version=1\n"
            "no_button=stock\n"
            "volume_up=rockbox\n"
            "volume_down=settings\n"
        )
        assert "status:s:ok" in (tools / "response.txt").read_text()
        assert (tools / "reboot.txt").read_text().strip() == "rebooted"
        assert "save_broker=verified request_id=67890" in (
            stock_log.read_text())

    print(f"PASS: {BROKER.name} ready/error/Rockbox/stock behavior")


if __name__ == "__main__":
    main()
