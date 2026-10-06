'''
Regression tests for the runAiBot.py fixes. Selenium can't drive a real browser here,
so the browser session is stubbed out at import time and the DOM is faked with small
objects that answer find_element / find_elements.

Each test fails if the specific bug it covers comes back.

License: MIT  (https://opensource.org/license/mit)
'''

import os
import sys
import types

import pytest
from selenium.common.exceptions import NoSuchElementException


@pytest.fixture(scope="module")
def bot():
    '''Import runAiBot with a stubbed browser session, so importing it never opens Chrome.'''
    fake_chrome = types.ModuleType("modules.open_chrome")
    fake_chrome.options = fake_chrome.driver = fake_chrome.actions = fake_chrome.wait = None
    sys.modules["modules.open_chrome"] = fake_chrome
    import runAiBot
    return runAiBot


class FakeElement:
    '''Stand-in for a WebElement: `children` maps an XPath/class to what it resolves to.'''

    def __init__(self, text="", value="", children=None):
        self.text = text
        self.value = value
        self.children = children or {}
        self.cleared = False

    def clear(self):
        self.cleared = True
        self.value = ""

    def send_keys(self, keys):
        self.value += str(keys)

    def get_attribute(self, name):
        return self.value if name == "value" else None

    def is_selected(self):
        return False

    def find_element(self, by, locator):
        if locator in self.children:
            return self.children[locator]
        raise NoSuchElementException(locator)

    def find_elements(self, by, locator):
        found = self.children.get(locator)
        if isinstance(found, list):
            return found
        return [found] if found else []


# --------------------------- A: the do_actions UnboundLocalError -------------------
def test_textarea_question_without_an_earlier_text_input(bot, monkeypatch):
    '''A cover-letter textarea used to read do_actions, which only the text branch set.'''
    typed = []
    monkeypatch.setattr(bot, "human_type", lambda target, text: typed.append((target, text)), raising=False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)

    textarea = FakeElement()
    question = FakeElement(children={
        ".//textarea": textarea,
        ".//label[@for]": FakeElement(text="Cover letter"),
    })
    modal = FakeElement(children={".//div[@data-test-form-element]": [question]})

    answered = bot.answer_questions(modal, set(), "Remote")   # used to raise UnboundLocalError

    assert len(answered) == 1
    assert textarea.cleared
    assert typed and typed[0][0] is textarea       # L: typed through human_type, not send_keys


def test_text_question_is_typed_through_human_type(bot, monkeypatch):
    typed = []
    monkeypatch.setattr(bot, "human_type", lambda target, text: typed.append((target, text)), raising=False)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)

    text_input = FakeElement()
    question = FakeElement(children={
        ".//input[@type='text']": text_input,
        ".//label[@for]": FakeElement(text="First name"),
    })
    modal = FakeElement(children={".//div[@data-test-form-element]": [question]})

    bot.answer_questions(modal, set(), "Remote")

    assert typed == [(text_input, bot.first_name)]


# ------------------------------ K: whole-word bad words ----------------------------
@pytest.mark.parametrize("text, words, expected", [
    ("Senior JavaScript Engineer", ["java"], None),          # the #95 bug: java != javascript
    ("Strong Java and Spring experience", ["java"], "java"),
    ("Backend role, ASP.NET Core", [".NET"], ".NET"),        # leading dot must still match
    ("We use .NETWORKING gear", [".NET"], None),
    ("No C2C please", ["No C2C"], "No C2C"),                 # multi-word phrases still work
    ("Must be a US Citizen", ["us citizen"], "us citizen"),  # case insensitive
    ("Rubyists welcome", ["Ruby"], None),
])
def test_find_bad_word_matches_whole_words_only(bot, text, words, expected):
    assert bot.find_bad_word(text, words) == expected


def test_a_javascript_job_is_not_skipped_by_the_bad_word_java(bot, monkeypatch):
    monkeypatch.setattr(bot, "bad_words", ["java"])
    monkeypatch.setattr(bot, "security_clearance", True)     # keep the clearance scan out of it
    monkeypatch.setattr(bot, "current_experience", -1)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "find_by_class",
                        lambda *a, **k: FakeElement(text="Senior JavaScript engineer, React and Node."))

    description, experience, skip, reason, message = bot.get_job_description()

    assert skip is False
    assert description.startswith("Senior JavaScript")


# ------------------------- F: recommended_wait was inverted ------------------------
def test_recommended_filter_wait_is_not_inverted(bot):
    assert bot.recommended_filter_wait(1) == 1    # the default click_gap must still pause
    assert bot.recommended_filter_wait(3) == 1
    assert bot.recommended_filter_wait(0) == 0    # only "no click gap" means no pause


# -------------------- B: an unreadable job description must skip -------------------
def test_unreadable_job_description_skips_the_job(bot, monkeypatch):
    def boom(*args, **kwargs):
        raise NoSuchElementException("jobs-box__html-content")

    monkeypatch.setattr(bot, "find_by_class", boom)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)

    description, experience, skip, reason, message = bot.get_job_description()

    assert description == "Unknown"
    assert skip is True          # never apply to a job whose description we never read
    assert reason and message


# ------------------ H: a run where nothing applied must not report zeros -----------
def test_non_easy_apply_job_is_counted_as_skipped(bot, monkeypatch):
    monkeypatch.setattr(bot, "easy_apply_only", True)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)
    monkeypatch.setattr(bot, "skip_count", 0)

    skip, link, tabs = bot.external_apply(object(), "1", "link", "resume", None, "Easy Applied", "shot")

    assert skip is True
    assert bot.skip_count == 1


# --------------------------- C: resilient Easy Apply detection ---------------------
def test_easy_apply_detection_is_an_ordered_fallback_list(bot):
    xpaths = [xpath for _, xpath in bot.easy_apply_locators]
    assert len(xpaths) > 1                                   # fallbacks, not one brittle locator
    # Measured 2026-09-09: `id="jobs-apply-button-id"` is on the real button and is the most
    # stable anchor there is, so it leads. The openSDUIApplyFlow flag was NOT in the captured
    # DOM, so it is kept only as one of the fallbacks.
    assert "jobs-apply-button-id" in xpaths[0]
    assert any("openSDUIApplyFlow=true" in xpath for xpath in xpaths)
    assert not any("artdeco-button--3" in xpath for xpath in xpaths)

    source = open(os.path.join(os.path.dirname(__file__), os.pardir, "runAiBot.py"), encoding="utf-8").read()
    assert "artdeco-button--3" not in source                 # the size token is gone everywhere


# ------------------------------- M: the no-submit flag -----------------------------
def test_stop_before_submit_setting_is_always_defined(bot):
    assert isinstance(bot.stop_before_submit, bool)


# ------------------------- N: survey and company-by-company mode ---------------------
def test_survey_csv_round_trips_into_company_list_most_postings_first(bot, tmp_path, monkeypatch):
    survey = tmp_path / "survey.csv"
    monkeypatch.setattr(bot, "survey_file_name", str(survey))
    monkeypatch.setattr(bot, "target_companies", [])
    bot.write_company_survey({
        "Small Co": {"postings_seen": 1, "actively_hiring_signal": False, "sample_titles": {"Analyst"}},
        "Big Co": {"postings_seen": 7, "actively_hiring_signal": True, "sample_titles": {"Developer"}},
    })
    assert bot.load_target_companies() == ["Big Co", "Small Co"]


def test_explicit_target_companies_win_over_the_survey(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "survey_file_name", str(tmp_path / "survey.csv"))
    monkeypatch.setattr(bot, "target_companies", ["Microsoft"])
    assert bot.load_target_companies() == ["Microsoft"]


def test_no_targets_and_no_survey_gives_an_empty_list(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "survey_file_name", str(tmp_path / "missing.csv"))
    monkeypatch.setattr(bot, "target_companies", [])
    assert bot.load_target_companies() == []


# ------------------------------- O: referral requests --------------------------------
def test_referral_note_fills_placeholders_and_fits_linkedins_limit(bot, monkeypatch):
    monkeypatch.setattr(bot, "first_name", "Lokesh")
    monkeypatch.setattr(bot, "last_name", "J")
    note = bot.referral_note("Asha", "Power BI Developer", "Philips")
    assert note.startswith("Hi Asha,") and "Power BI Developer" in note and "Philips" in note and "Lokesh J" in note
    long_note = bot.referral_note("Asha", "Data Analyst II (Sharepoint/ PowerApps/ Power Automate Developer)- Only Bangalore Based Candidates", "AtkinsRealis")
    assert len(long_note) <= bot.REFERRAL_NOTE_LIMIT
    assert long_note.endswith("Lokesh J")


def test_referral_targets_are_only_submitted_easy_applies_one_per_company(bot, tmp_path, monkeypatch):
    applied = tmp_path / "applied.csv"
    applied.write_text(
        "Company,Title,External Job link,Date Applied,HR Link,HR Name\n"
        "GIVA,Business Analyst,Easy Applied,2026-10-01 11:50:09,Unknown,Unknown\n"
        "Philips,Power BI Developer,https://careers.philips.com/x,Pending,Unknown,Unknown\n"
        "GIVA,Data Analyst,Easy Applied,2026-10-01 11:55:00,Unknown,Unknown\n"
        "Jobgether,Data Engineer,Easy Applied,Pending,Unknown,Unknown\n"
        "Kaufman Rossin,Analyst,Easy Applied,2026-10-01 11:58:00,Unknown,Unknown\n",
        encoding="utf-8")
    monkeypatch.setattr(bot, "file_name", str(applied))
    targets = bot.load_referral_targets()
    assert [(t["Company"], t["Title"]) for t in targets] == [("Kaufman Rossin", "Analyst"), ("GIVA", "Data Analyst")]


@pytest.mark.parametrize("full, short", [
    ("ZettaMine Labs Pvt. Ltd.", "ZettaMine Labs"),
    ("Weekday AI (YC W21)", "Weekday AI"),
    ("FyerX Global Private Limited", "FyerX Global"),
    ("Smart IMS Inc.", "Smart IMS"),
    ("Kaufman Rossin", "Kaufman Rossin"),
    ("GIVA", "GIVA"),
])
def test_company_names_are_shortened_to_what_profiles_show(bot, full, short):
    assert bot.short_company_name(full) == short


def test_referral_history_counts_only_sent_requests_towards_limits(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "referral_file_name", str(tmp_path / "referrals.csv"))
    bot.record_referral("GIVA", "Business Analyst", "Asha K", "https://www.linkedin.com/in/asha", "Hiring team", "Sent with note")
    bot.record_referral("GIVA", "Business Analyst", "Ravi M", "https://www.linkedin.com/in/ravi", "People search", "Skipped - no Connect button (already connected, pending, or follow-only)")
    contacted, per_company, today = bot.load_referral_history()
    assert contacted == {"https://www.linkedin.com/in/asha"}
    assert per_company == {"GIVA": 1}
    assert today == 1


# ------------------------------- N: location via URL, not the UI box ----------------
def test_jobs_search_url_includes_both_keywords_and_location(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_location", "Singapore")
    url = bot.jobs_search_url("Power Platform Developer")
    assert url == "https://www.linkedin.com/jobs/search/?keywords=Power%20Platform%20Developer&location=Singapore"


def test_jobs_search_url_with_no_keywords_for_company_mode(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_location", "Singapore")
    url = bot.jobs_search_url()
    assert url == "https://www.linkedin.com/jobs/search/?location=Singapore"


def test_jobs_search_url_omits_location_when_blank(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_location", "")
    url = bot.jobs_search_url("Data Analyst")
    assert url == "https://www.linkedin.com/jobs/search/?keywords=Data%20Analyst"
    assert "location=" not in url


# ------------------------------- O: multi-location search -----------------------------
def test_locations_to_search_falls_back_to_single_location(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_locations", [])
    monkeypatch.setattr(bot, "search_location", "India")
    assert bot.locations_to_search() == ["India"]


def test_locations_to_search_uses_the_list_when_set(bot, monkeypatch):
    monkeypatch.setattr(bot, "search_locations", ["Singapore", "Chennai", "Bengaluru"])
    monkeypatch.setattr(bot, "search_location", "India")
    assert bot.locations_to_search() == ["Singapore", "Chennai", "Bengaluru"]
