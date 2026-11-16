'''
LinkedIn's "AI-powered job search" page (/jobs/search-results/, 2026-11) replaced the
job list, the description panel and the pagination with randomized classes. These tests
pin the new stable anchors (tests/fixtures/07_ai_job_search.html) and the bot code that
reads them, while the old layout keeps working.

License: MIT  (https://opensource.org/license/mit)
'''

import os
import sys
import types

import pytest
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "07_ai_job_search.html")


@pytest.fixture(scope="module")
def bot():
    fake_chrome = types.ModuleType("modules.open_chrome")
    fake_chrome.options = fake_chrome.driver = fake_chrome.actions = fake_chrome.wait = None
    sys.modules["modules.open_chrome"] = fake_chrome
    import runAiBot
    return runAiBot


@pytest.fixture
def quiet(bot, monkeypatch):
    monkeypatch.setattr(bot, "buffer", lambda *a: None)
    monkeypatch.setattr(bot, "scroll_to_view", lambda *a, **k: None)
    monkeypatch.setattr(bot, "print_lg", lambda *a, **k: None)


class El:
    def __init__(self, text="", attrs=None, children=None):
        self.text, self.attrs, self.children, self.clicked = text, attrs or {}, children or {}, False

    def get_dom_attribute(self, name):
        return self.attrs.get(name)

    def get_attribute(self, name):
        return self.attrs.get(name)

    def find_elements(self, by, xpath):
        return self.children.get(xpath, [])

    def find_element(self, by, xpath):
        found = self.children.get(xpath)
        if not found: raise NoSuchElementException(xpath)
        return found[0]

    def click(self):
        self.clicked = True


def new_card(job_id, *lines):
    return El(attrs={"role": "button", "componentkey": f"job-card-component-ref-{job_id}"},
              children={".//p": [El(text=line) for line in lines]})


# ------------------------------- fixture anchors ----------------------------------
def test_fixture_has_the_measured_anchors():
    html = open(FIXTURE, encoding="utf-8").read()
    assert 'role="button" tabindex="0" componentkey="job-card-component-ref-4464121141"' in html
    assert 'data-sdui-screen="com.linkedin.sdui.flagshipnav.jobs.SemanticJobDetails"' in html
    assert '<h2>About the job</h2>' in html and 'data-testid="expandable-text-box"' in html
    assert 'aria-label="Page 1" aria-current="true"' in html
    assert 'aria-label="Apply on company website"' in html
    assert 'data-occludable-job-id' not in html and 'jobs-box__html-content' not in html


# ------------------------------- job cards ----------------------------------------
def test_job_card_xpath_covers_both_layouts(bot):
    assert "@data-occludable-job-id" in bot.job_card_xpath
    assert "job-card-component-ref-" in bot.job_card_xpath


def test_card_job_id_from_new_and_old_cards(bot):
    assert bot.card_job_id(new_card("4472458608")) == "4472458608"
    assert bot.card_job_id(El(attrs={"data-occludable-job-id": "123"})) == "123"
    assert bot.card_job_id(El()) is None


def test_card_xpath_for_id_finds_either_layout(bot):
    xp = bot.card_xpath_for_id("42")
    assert "@data-occludable-job-id='42'" in xp and "@componentkey='job-card-component-ref-42'" in xp


def test_new_card_details_are_read_and_card_clicked(bot, quiet):
    card = new_card("4472458608", "Power Apps developer", "Example Consulting", "Chennai, Tamil Nadu, India (Hybrid)", "Viewed")
    assert bot.get_job_main_details(card, set(), set()) == (
        "4472458608", "Power Apps developer", "Example Consulting", "Chennai, Tamil Nadu, India", "Hybrid", False)
    assert card.clicked


def test_new_card_verified_title_is_not_doubled(bot, quiet):
    # Live 2026-11-07: the title <p> reads "<title> (Verified job)\n<title>".
    card = new_card("3", "Custom Software Engineer (Verified job)\nCustom Software Engineer", "Accenture in India", "Chennai")
    assert bot.get_job_main_details(card, set(), set())[1] == "Custom Software Engineer"


# ------------------------------- blacklist check ----------------------------------
def test_missing_top_card_is_not_a_blacklist_hit(bot, quiet, monkeypatch):
    # The AI search page has no old top card; that must not read as "blacklisted company".
    monkeypatch.setattr(bot, "try_find_by_classes", lambda *a: (_ for _ in ()).throw(ValueError("Failed to find an element with given classes")))
    with pytest.raises(Exception) as err:
        bot.check_blacklist(set(), "1", "Acme", set())
    assert not isinstance(err.value, bot.BlacklistedCompanyFound)


def test_real_blacklist_word_still_raises_blacklisted(bot, quiet, monkeypatch):
    monkeypatch.setattr(bot, "try_find_by_classes", lambda *a: El())
    monkeypatch.setattr(bot, "find_by_class", lambda *a, **k: El(text="We are a staffing agency"))
    monkeypatch.setattr(bot, "about_company_good_words", [])
    monkeypatch.setattr(bot, "about_company_bad_words", ["staffing"])
    with pytest.raises(bot.BlacklistedCompanyFound):
        bot.check_blacklist(set(), "1", "Acme", set())


def test_apply_loop_only_skips_on_a_real_blacklist_hit(bot):
    import inspect
    source = inspect.getsource(bot.apply_to_jobs)
    assert "except BlacklistedCompanyFound as e:" in source
    assert "except ValueError as e:\n                        print_lg(e, 'Skipping this job!" not in source


def test_new_card_already_applied_is_skipped_unclicked(bot, quiet):
    card = new_card("1", "Power Apps developer", "Example Consulting", "Chennai", "Applied")
    assert bot.get_job_main_details(card, set(), set())[-1] is True
    assert not card.clicked


def test_new_card_blacklisted_company_is_skipped(bot, quiet):
    card = new_card("2", "Power Apps developer", "Bad Co", "Chennai")
    assert bot.get_job_main_details(card, {"Bad Co"}, set())[-1] is True


# ------------------------------- description --------------------------------------
def test_description_read_from_new_panel_in_full(bot, quiet, monkeypatch):
    box = El(text="cut off by the more button",
             attrs={"data-testid": "expandable-text-box", "textContent": "  Full description: Power Apps and Dataverse.  "})
    monkeypatch.setattr(bot, "driver", El(children={bot.job_description_xpath: [box]}))
    monkeypatch.setattr(bot, "find_by_class", lambda *a, **k: pytest.fail("fell back to the old layout"))
    description, _exp, skip, _reason, _msg = bot.get_job_description()
    assert description == "Full description: Power Apps and Dataverse."
    assert skip is False


# ------------------------------- pagination ---------------------------------------
def test_page_info_reads_new_pagination(bot, quiet, monkeypatch):
    current = El(attrs={"aria-label": "Page 2"})
    pager = El(children={".//button[@aria-current='true']": [current]})
    monkeypatch.setattr(bot, "try_find_by_classes", lambda *a: (_ for _ in ()).throw(ValueError("old pager gone")))
    monkeypatch.setattr(bot, "driver", El(children={bot.pagination_xpath: [pager]}))
    assert bot.get_page_info() == (pager, 2)


# ------------------------------- search URL ---------------------------------------
# The AI search page drops a `location=` param on redirect (live-verified 2026-11-06), but
# honours a location written into the query: "X in Chennai" returned only Chennai jobs.
@pytest.mark.parametrize("location, expected", [
    ("Chennai", "https://www.linkedin.com/jobs/search-results/?keywords=Power%20Platform%20Developer%20in%20Chennai"),
    ("Remote", "https://www.linkedin.com/jobs/search-results/?keywords=Power%20Platform%20Developer%20remote"),
    ("", "https://www.linkedin.com/jobs/search-results/?keywords=Power%20Platform%20Developer"),
])
def test_search_url_puts_location_in_the_query(bot, monkeypatch, location, expected):
    monkeypatch.setattr(bot, "search_location", location)
    assert bot.jobs_search_url("Power Platform Developer") == expected


# ------------------------------- waiting for cards --------------------------------
def test_wait_for_job_cards_rides_out_the_redirect(bot, monkeypatch):
    # Old page's cards, then nothing while the AI search page loads, then the real cards.
    answers = iter([["old"], [], [], ["c1", "c2"], ["c1", "c2"]])
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=lambda by, xp: next(answers)))
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    assert bot.wait_for_job_cards(timeout=30) == ["c1", "c2"]


def test_wait_for_job_cards_gives_up_empty(bot, monkeypatch):
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=lambda by, xp: []))
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(bot.time, "time", lambda: next(clock))
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    assert bot.wait_for_job_cards(timeout=20) == []


# ------------------------------- apply button -------------------------------------
def test_apply_locators_cover_new_layout_without_the_filter_pill(bot):
    xpaths = [xp for _, xp in bot.easy_apply_locators]
    assert any("Apply on company website" in xp for xp in xpaths)
    easy = [xp for xp in xpaths if "'Easy Apply'" in xp and "Filter" in xp]
    assert easy, "need an Easy Apply aria-label locator that excludes the 'Filter by Easy Apply' pill"


def test_wait_for_apply_control_rides_out_a_late_button(bot, monkeypatch):
    # Live 2026-11-16: the description rendered before the apply button, so an instant
    # check found nothing and the job ended in "Failed to apply!".
    calls = {"n": 0}

    def find_elements(by, xp):
        calls["n"] += 1
        return ["button"] if calls["n"] > 2 * len(bot.easy_apply_locators) else []

    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=find_elements))
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    assert bot.wait_for_apply_control(timeout=30) is True


def test_wait_for_apply_control_gives_up(bot, monkeypatch):
    monkeypatch.setattr(bot, "driver", types.SimpleNamespace(find_elements=lambda by, xp: []))
    clock = iter(range(0, 1000, 2))
    monkeypatch.setattr(bot.time, "time", lambda: next(clock))
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    assert bot.wait_for_apply_control(timeout=6) is False


def test_apply_loop_waits_for_the_apply_control(bot):
    import inspect
    source = inspect.getsource(bot.apply_to_jobs)
    assert source.index("wait_for_apply_control()") < source.index("for how, xpath in easy_apply_locators:")


def test_apply_locators_match_links_as_well_as_buttons(bot):
    # Live 2026-11-07: "Apply on company website" was an <a target="_blank">, so a //button
    # locator missed it and every external job ended in "Failed to apply!".
    html = open(FIXTURE, encoding="utf-8").read()
    assert '<a aria-disabled="false"' in html and 'aria-label="Apply on company website">Apply</a>' in html
    for name in ("AI search company website", "AI search Easy Apply"):
        xp = dict(bot.easy_apply_locators)[name]
        assert "self::a" in xp and "self::button" in xp, name
