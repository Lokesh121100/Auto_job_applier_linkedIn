'''
Regression tests for runNaukriBot.py. Selenium can't drive a real browser here, so the
browser session is stubbed out at import time (same pattern as test_runaibot_fixes.py)
and the DOM is faked with small objects that answer find_elements.

License: MIT  (https://opensource.org/license/mit)
'''

import sys
import types

import pytest


@pytest.fixture(scope="module")
def naukri():
    '''Import runNaukriBot with a stubbed browser session, so importing it never opens Chrome.'''
    fake_chrome = types.ModuleType("modules.open_chrome")
    fake_chrome.driver = fake_chrome.actions = fake_chrome.wait = None
    sys.modules["modules.open_chrome"] = fake_chrome
    import runNaukriBot
    return runNaukriBot


class FakeDriver:
    '''Stand-in for the Selenium driver: `matches` is the set of XPaths find_elements should hit on.'''

    def __init__(self, matches=()):
        self.matches = set(matches)

    def find_elements(self, by, xpath):
        return [object()] if xpath in self.matches else []


# ------------------------------- search URL building ---------------------------------
def test_search_url_with_location(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "search_location", "Bengaluru, Karnataka, India")
    url = naukri.build_search_url("Power Platform Developer", 1)
    assert url == "https://www.naukri.com/power-platform-developer-jobs-in-bengaluru,-karnataka,-india"


def test_search_url_without_location(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "search_location", "")
    assert naukri.build_search_url("Data Analyst", 1) == "https://www.naukri.com/data-analyst-jobs"


def test_search_url_page_number_only_suffixes_after_page_1(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "search_location", "")
    assert naukri.build_search_url("Data Analyst", 1) == "https://www.naukri.com/data-analyst-jobs"
    assert naukri.build_search_url("Data Analyst", 3) == "https://www.naukri.com/data-analyst-jobs-3"


# ------------------------------- quota detection --------------------------------------
def test_quota_exceeded_is_case_insensitive(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "driver", FakeDriver(matches=[
        "//*[contains(translate(normalize-space(.),"
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'daily quota')]"
    ]))
    assert naukri.quota_exceeded() is True


def test_quota_not_exceeded_when_phrase_is_absent(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "driver", FakeDriver(matches=[]))
    assert naukri.quota_exceeded() is False


# ------------------------------- recorded-links CSV round trip ------------------------
def test_recorded_links_round_trip_and_dedupe(naukri, tmp_path, monkeypatch):
    csv_path = tmp_path / "naukri_history.csv"
    monkeypatch.setattr(naukri, "naukri_file_name", str(csv_path))

    assert naukri.get_recorded_naukri_links() == set()

    naukri.record_naukri("Power BI Developer", "Acme Corp", "Applied (Naukri form)",
                          "https://www.naukri.com/job-listings-1")
    naukri.record_naukri("Data Analyst", "Beta Inc", "External - apply manually: https://beta.example/apply",
                          "https://www.naukri.com/job-listings-2")

    recorded = naukri.get_recorded_naukri_links()
    assert recorded == {"https://www.naukri.com/job-listings-1", "https://www.naukri.com/job-listings-2"}


def test_record_naukri_truncates_oversized_fields(naukri, tmp_path, monkeypatch):
    csv_path = tmp_path / "naukri_history.csv"
    monkeypatch.setattr(naukri, "naukri_file_name", str(csv_path))
    naukri.record_naukri("T" * 200000, "C" * 200000, "Applied (clicked Apply)", "https://www.naukri.com/job-listings-3")
    import csv
    with open(csv_path, encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert "[TRUNCATED]" in row["Title"]
    assert "[TRUNCATED]" in row["Company"]


# ------------------------------- config wiring -----------------------------------------
def test_naukri_run_settings_are_always_defined(naukri):
    assert isinstance(naukri.naukri_max_applications, int) and naukri.naukri_max_applications > 0
    assert isinstance(naukri.naukri_pages_per_keyword, int) and naukri.naukri_pages_per_keyword > 0
