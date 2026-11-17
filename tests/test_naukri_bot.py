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


# ------------------------------- login field filling ----------------------------------
class LoginField:
    '''A login input. `sticks=False` models Naukri wiping what was typed while its page loads.'''

    def __init__(self, sticks):
        self.value, self.sticks = "", sticks

    def clear(self):
        self.value = ""

    def send_keys(self, text):
        if self.sticks: self.value += text

    def get_attribute(self, name):
        return self.value if name == "value" else None


def test_fill_login_field_types_normally(naukri, monkeypatch):
    field = LoginField(sticks=True)
    monkeypatch.setattr(naukri, "driver", types.SimpleNamespace(execute_script=lambda *a: pytest.fail("JS not needed")))
    naukri.fill_login_field(field, "me@example.com")
    assert field.value == "me@example.com"


def test_fill_login_field_sets_value_when_typing_is_wiped(naukri, monkeypatch):
    # Live 2026-11-16: both fields read empty after typing -> "cannot be left blank".
    field = LoginField(sticks=False)

    def execute_script(script, element, text):
        assert "dispatchEvent" in script
        element.value = text

    monkeypatch.setattr(naukri, "driver", types.SimpleNamespace(execute_script=execute_script))
    naukri.fill_login_field(field, "me@example.com")
    assert field.value == "me@example.com"


def test_login_fills_fields_through_the_checked_helper(naukri):
    import inspect
    source = inspect.getsource(naukri.login_naukri)
    assert "fill_login_field(username_field, naukri_username)" in source
    assert "fill_login_field(password_field, naukri_password)" in source
    assert "username_field.send_keys(naukri_username)" not in source


# ------------------------------- Career-Ops fit check ----------------------------------
class TextDriver:
    '''Answers find_elements with elements carrying `.text`, for every XPath in `texts`.'''

    def __init__(self, texts):
        self.texts = texts
        self.visited = []

    def find_elements(self, by, xpath):
        return [types.SimpleNamespace(text=t) for t in self.texts.get(xpath, [])]

    def get(self, url):
        self.visited.append(url)


def test_read_job_description_takes_the_jd_section(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "driver", TextDriver({naukri.job_description_xpath: ["Need Power Apps and Dataverse"]}))
    monkeypatch.setattr(naukri, "buffer", lambda *a: None)
    assert naukri.read_job_description() == "Need Power Apps and Dataverse"


def test_read_job_description_empty_when_page_has_none(naukri, monkeypatch):
    monkeypatch.setattr(naukri, "driver", TextDriver({}))
    monkeypatch.setattr(naukri, "buffer", lambda *a: None)
    assert naukri.read_job_description() == ""


@pytest.fixture
def one_job_run(naukri, monkeypatch):
    '''run() over a single job card, recording what gets written instead of touching a browser.'''
    job = {"title": "Java Developer", "company": "Acme", "link": "https://www.naukri.com/job-listings-9"}
    recorded = []
    # run() bails out when no credentials are configured, so set dummy ones here rather than
    # letting these tests depend on whatever is in the developer's own user_config.json.
    monkeypatch.setattr(naukri, "naukri_username", "tester@example.com")
    monkeypatch.setattr(naukri, "naukri_password", "not-a-real-password")
    monkeypatch.setattr(naukri, "driver", TextDriver({naukri.job_description_xpath: ["Java, Spring, Kafka"]}))
    monkeypatch.setattr(naukri, "login_naukri", lambda: True)
    monkeypatch.setattr(naukri, "search_terms", ["Java Developer"])
    monkeypatch.setattr(naukri, "naukri_pages_per_keyword", 1)
    monkeypatch.setattr(naukri, "get_recorded_naukri_links", set)
    monkeypatch.setattr(naukri, "collect_job_cards", lambda: [job])
    monkeypatch.setattr(naukri, "buffer", lambda *a: None)
    monkeypatch.setattr(naukri, "record_naukri", lambda *row: recorded.append(row))
    return recorded


def test_low_match_job_is_recorded_as_skipped_without_applying(naukri, monkeypatch, one_job_run):
    monkeypatch.setattr(naukri, "check_job_fit", lambda description: "Career-Ops match 10% is below 40%")
    monkeypatch.setattr(naukri, "apply_to_current_job", lambda: pytest.fail("applied to a low-match job"))
    naukri.run()
    assert one_job_run[0][2] == "Skipped - Career-Ops match 10% is below 40%"


def test_run_searches_every_location(naukri, monkeypatch, one_job_run):
    monkeypatch.setattr(naukri, "search_locations", ["Chennai", "Bengaluru"])
    monkeypatch.setattr(naukri, "check_job_fit", lambda description: None)
    monkeypatch.setattr(naukri, "apply_to_current_job", lambda: "Applied (Naukri form)")
    naukri.run()
    assert "https://www.naukri.com/java-developer-jobs-in-chennai" in naukri.driver.visited
    assert "https://www.naukri.com/java-developer-jobs-in-bengaluru" in naukri.driver.visited


def test_good_match_job_is_applied_with_its_description_scored(naukri, monkeypatch, one_job_run):
    scored = []
    monkeypatch.setattr(naukri, "check_job_fit", lambda description: scored.append(description))
    monkeypatch.setattr(naukri, "apply_to_current_job", lambda: "Applied (Naukri form)")
    naukri.run()
    assert scored == ["Java, Spring, Kafka"]
    assert one_job_run[0][2] == "Applied (Naukri form)"


# --------------------- a dead browser stops the run, it isn't a job failure ---------------------
def test_browser_is_gone_recognises_a_dropped_driver_connection(naukri):
    '''The live run died on a urllib3 ProtocolError, which is not a WebDriverException.'''
    from urllib3.exceptions import ProtocolError
    dropped = ProtocolError("Connection aborted.", ConnectionResetError(10054, "forcibly closed"))
    assert naukri.browser_is_gone(dropped)


def test_browser_is_gone_sees_through_a_wrapping_error(naukri):
    try:
        try:
            raise ConnectionResetError(10054, "forcibly closed")
        except ConnectionResetError as cause:
            raise RuntimeError("while applying") from cause
    except RuntimeError as wrapped:
        assert naukri.browser_is_gone(wrapped)


def test_browser_is_gone_is_false_for_an_ordinary_job_failure(naukri):
    assert not naukri.browser_is_gone(ValueError("odd job page"))


def test_run_stops_instead_of_recording_every_job_once_the_browser_dies(naukri, monkeypatch, one_job_run):
    from urllib3.exceptions import ProtocolError
    jobs = [{"title": f"Job {n}", "company": "Acme", "link": f"https://www.naukri.com/job-{n}"}
            for n in range(5)]
    monkeypatch.setattr(naukri, "collect_job_cards", lambda: jobs)
    monkeypatch.setattr(naukri, "check_job_fit", lambda description: None)
    monkeypatch.setattr(naukri, "apply_to_current_job",
                        lambda: (_ for _ in ()).throw(ProtocolError("Connection aborted.")))
    naukri.run()
    assert one_job_run == [], "a dead browser was recorded as a per-job failure"


def test_run_still_records_a_single_odd_job_as_failed(naukri, monkeypatch, one_job_run):
    monkeypatch.setattr(naukri, "check_job_fit", lambda description: None)
    monkeypatch.setattr(naukri, "apply_to_current_job",
                        lambda: (_ for _ in ()).throw(ValueError("odd job page")))
    naukri.run()
    assert one_job_run[0][2] == "Failed - ValueError"


# ------------------------- results pages are re-read before giving up -------------------------
def test_wait_for_job_cards_retries_until_the_page_renders(naukri, monkeypatch):
    reads = []
    jobs = [{"title": "Java Developer", "company": "Acme", "link": "https://www.naukri.com/job-9"}]
    def collect():
        reads.append(1)
        return jobs if len(reads) >= 3 else []
    monkeypatch.setattr(naukri, "collect_job_cards", collect)
    monkeypatch.setattr(naukri, "buffer", lambda *a: None)
    assert naukri.wait_for_job_cards() == jobs
    assert len(reads) == 3


def test_wait_for_job_cards_gives_up_on_a_genuinely_empty_page(naukri, monkeypatch):
    reads = []
    monkeypatch.setattr(naukri, "collect_job_cards", lambda: reads.append(1) or [])
    monkeypatch.setattr(naukri, "buffer", lambda *a: None)
    assert naukri.wait_for_job_cards(attempts=4) == []
    assert len(reads) == 4
