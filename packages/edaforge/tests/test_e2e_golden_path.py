"""The golden path in a real browser (PROJECT_PROMPT.md section 10, milestone 6).

Upload two related files -> inspect their profiles -> review and confirm a relationship -> run
discovery -> view ranked findings -> open a finding -> switch explanation levels -> inspect the
method -> export a report. Also opens the Data Universe. Fails on any page error.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "apps" / "web" / "dist"
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    if not (DIST / "index.html").is_file():
        pytest.skip("web app not built (npm --prefix apps/web run build)")
    uvicorn = pytest.importorskip("uvicorn")
    from edaforge.server.app import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(
        create_app(tmp_path_factory.mktemp("home"), web_dist=DIST),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    sys.path.insert(0, str(ROOT / "examples" / "demo"))
    from make_demo import make_demo  # type: ignore[import-not-found]

    out = make_demo(tmp_path_factory.mktemp("demo"), n_customers=600, n_orders=2500)
    return [p for p in out if p.name in {"customers_us.csv", "orders.xlsx"}]


def test_golden_path(server: str, files: list[Path], tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    errors: list[str] = []
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
            )
        except Exception as exc:  # noqa: BLE001 - no browser installed: skip, do not fail
            pytest.skip(f"Chromium is not available: {exc}")
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(60_000)

        # 1. workspace + upload two related files
        page.goto(server + "/")
        page.get_by_label("Workspace name").fill("Golden path")
        page.get_by_role("button", name="Create workspace").click()
        page.wait_for_url("**/data**")
        page.get_by_test_id("file-input").set_input_files([str(f) for f in files])
        page.get_by_text("2 of 2 files read").wait_for()
        assert page.locator(".file .hdot").count() == 2  # health traffic lights

        # 2. inspect profiles
        page.get_by_text("Data health").first.wait_for()
        page.get_by_role("tab", name="Columns").first.click()
        page.get_by_role("tab", name="Preview rows").click()
        page.locator("table.data tbody tr").first.wait_for()

        # 3. review and confirm the join
        page.get_by_role("button", name="Next: connect files →").click()
        page.locator(".suggestion", has_text="Join").first.get_by_role(
            "button", name="Review & preview"
        ).click()
        page.get_by_text("rows in the result").wait_for()
        page.get_by_role("button", name="Confirm link").click()
        page.get_by_text("Find patterns in it →").wait_for()

        # 4. run discovery on the combined table, with an outcome
        page.get_by_text("Find patterns in it →").click()
        page.wait_for_url("**/discover**")
        page.get_by_text("What will run").wait_for()
        page.get_by_label("Outcome column").select_option("returned")
        page.wait_for_timeout(800)
        page.get_by_role("button", name="Find hidden patterns", exact=True).last.click()
        page.wait_for_url("**/runs/**")

        # 5. ranked findings
        page.locator(".fcard").first.wait_for(timeout=300_000)
        assert page.locator(".fcard").count() >= 3
        assert page.locator(".fcard .rank").first.inner_text() == "#1"

        # 6. open a finding, switch lenses, inspect the method
        page.locator(".fcard").first.click()
        tabs = page.get_by_role("tablist", name="Explanation level")
        tabs.wait_for()
        for lens in ("Analyst", "Scientist", "Plain"):
            page.get_by_role("tab", name=lens).click()
            assert page.locator(".lens").inner_text().strip()
        page.get_by_role("button", name="Show method & evidence").click()
        assert "p-value" in page.locator(".method").inner_text()
        page.get_by_text("← Insight Feed").click()

        # 7. the Data Universe
        page.get_by_role("button", name="Enter the Data Universe ✦").click()
        page.get_by_test_id("universe-canvas").wait_for()
        page.get_by_text("DATA UNIVERSE").wait_for()
        page.go_back()

        # 8. export the report
        page.get_by_role("button", name="Report & export →").click()
        with page.expect_download(timeout=180_000) as dl:
            page.get_by_role("button", name="Download HTML report").click()
        report = tmp_path / "report.html"
        dl.value.save_as(report)
        html = report.read_text("utf-8")
        assert "<script" not in html.lower()  # self-contained and inert
        assert "Grade" in html
        assert "returned" in html
        browser.close()
    assert not errors, errors
