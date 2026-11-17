"""Both services start as separate processes on different ports."""

from pathlib import Path

import httpx

from tests.support.leak import CANARIES, assert_no_leak
from tests.support.process import ServiceProcess
from tests.support.settings_data import write_settings_file


def test_both_services_start_independently_and_report_health(
    empty_database_url: str, tmp_path: Path
) -> None:
    settings_file = write_settings_file(tmp_path / "settings.json")
    san_env = {
        "PRIVYFLOW_SAN_DATABASE_URL": empty_database_url,
        "PRIVYFLOW_SETTINGS_FILE": str(settings_file),
    }
    # The De-sanitization process gets no database setting at all.
    desan_env = {"PRIVYFLOW_DESAN_SANITIZATION_BASE_URL": "http://127.0.0.1:1"}
    with (
        ServiceProcess("sanitization_service", san_env, tmp_path / "san.log") as san,
        ServiceProcess("desanitization_service", desan_env, tmp_path / "desan.log") as desan,
    ):
        san.wait_until_live()
        desan.wait_until_live()
        assert san.port != desan.port
        for service in (san, desan):
            live = httpx.get(f"{service.base_url}/health/live")
            ready = httpx.get(f"{service.base_url}/health/ready")
            assert (live.status_code, ready.status_code) == (200, 200)
        assert not [name for name in desan_env if "DATABASE" in name]


def test_sanitization_readiness_is_503_in_a_real_process_when_database_is_down(
    tmp_path: Path,
) -> None:
    env = {"PRIVYFLOW_SAN_DATABASE_URL": "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none"}
    with ServiceProcess("sanitization_service", env, tmp_path / "san.log") as san:
        san.wait_until_live()
        assert httpx.get(f"{san.base_url}/health/live").status_code == 200
        assert httpx.get(f"{san.base_url}/health/ready").status_code == 503


def test_process_output_has_no_query_string_header_or_body_capture(tmp_path: Path) -> None:
    env = {"PRIVYFLOW_DESAN_SANITIZATION_BASE_URL": "http://127.0.0.1:1"}
    with ServiceProcess("desanitization_service", env, tmp_path / "desan.log") as service:
        service.wait_until_live()
        httpx.post(
            f"{service.base_url}/api/v1/unknown?q={CANARIES[1]}",
            content=CANARIES[0],
            headers={"Authorization": CANARIES[3], "X-Correlation-ID": "canary-check-0001"},
        )
        output = service.output()
    assert "canary-check-0001" in output
    assert_no_leak(output)
