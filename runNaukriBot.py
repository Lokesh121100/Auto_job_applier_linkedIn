'''
License:    MIT License
            https://opensource.org/license/mit

Naukri.com job applier. Reuses this project's existing Chrome driver setup
(modules/open_chrome.py) and job-title/location settings (config/search.py) -
only the login and the apply flow are Naukri-specific, written fresh for this
project below.

The shape of Naukri's apply flow (login field ids, job-card classes, the
"Apply on company site" redirect) was studied from the open-source reference
github.com/lordzohar/Naukri-autoapply-bot for research purposes only, to learn
how Naukri's pages behave. No code from that project is used here - it carries
no license, so copying it would not have been legally reusable in this
MIT-licensed project.

IMPORTANT, and different from LinkedIn: most Naukri jobs use an "Apply on
company site" button that opens the company's own site in a new tab. The bot
cannot fill that in - same limitation as LinkedIn's external jobs - so those
are logged with their link for you to finish by hand, not counted as applied.
'''

import os
import csv
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, NoSuchWindowException,
    WebDriverException, StaleElementReferenceException,
)

from config.personals import first_name, last_name
from config.search import search_terms, search_location
from config.naukri import naukri_username, naukri_password, naukri_max_applications, naukri_pages_per_keyword

from modules.open_chrome import driver, wait, actions
from modules.helpers import print_lg, logger, critical_error_log, buffer, truncate_for_csv

naukri_file_name = "all excels/naukri_applied_history.csv"
naukri_fields = ['Date Applied', 'Title', 'Company', 'Status', 'Job Link']


def get_recorded_naukri_links() -> set[str]:
    '''Job links already recorded (applied, external, or failed) so a later run never repeats them.'''
    try:
        with open(naukri_file_name, encoding='utf-8') as csv_file:
            return {row['Job Link'] for row in csv.DictReader(csv_file)}
    except FileNotFoundError:
        return set()


def record_naukri(title: str, company: str, status: str, link: str) -> None:
    try:
        folder = os.path.dirname(naukri_file_name)
        if folder: os.makedirs(folder, exist_ok=True)
        with open(naukri_file_name, mode='a', newline='', encoding='utf-8') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=naukri_fields)
            if csv_file.tell() == 0: writer.writeheader()
            writer.writerow({
                'Date Applied': datetime.now().strftime("%Y-%m-%d %H:%M"),
                'Title': truncate_for_csv(title), 'Company': truncate_for_csv(company),
                'Status': status, 'Job Link': link,
            })
    except Exception as e:
        logger.error("Failed to record this Naukri application!", exc_info=e)


def login_naukri() -> bool:
    '''Logs in to Naukri.com. Returns False (and logs why) instead of raising, so a bad
    login is reported cleanly rather than crashing the run.'''
    print_lg("Logging in to Naukri.com...")
    driver.get("https://www.naukri.com/nlogin/login")
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "usernameField")))
    except TimeoutException:
        logger.error("Naukri's login page didn't load as expected. Naukri may have changed its login page.")
        return False
    driver.find_element(By.ID, "usernameField").send_keys(naukri_username)
    password_field = driver.find_element(By.ID, "passwordField")
    password_field.send_keys(naukri_password)
    password_field.send_keys(Keys.ENTER)
    buffer(5)
    if "login" in driver.current_url.lower():
        logger.error("Naukri login didn't go through - check naukri_username/naukri_password in the Naukri tab.")
        return False
    print_lg("Logged in to Naukri.")
    return True


def build_search_url(keyword: str, page: int) -> str:
    slug = keyword.strip().lower().replace(' ', '-')
    if search_location:
        location_slug = search_location.strip().lower().replace(' ', '-')
        base = f"https://www.naukri.com/{slug}-jobs-in-{location_slug}"
    else:
        base = f"https://www.naukri.com/{slug}-jobs"
    return base if page == 1 else f"{base}-{page}"


def collect_job_cards() -> list[dict]:
    '''Each visible job card as {title, company, link}. Tries Naukri's current card class
    first, then an older one, so a template swap degrades instead of returning nothing.'''
    jobs = []
    cards = driver.find_elements(By.XPATH, "//div[contains(@class,'srp-jobtuple-wrapper')]")
    if not cards:
        cards = driver.find_elements(By.XPATH, "//div[contains(@class,'cust-job-tuple')]")
    for card in cards:
        try:
            title_el = card.find_element(By.XPATH, ".//a[contains(@class,'title')]")
            link = title_el.get_attribute("href")
            title = title_el.text.strip()
        except (NoSuchElementException, StaleElementReferenceException):
            continue
        if not link: continue
        company = ""
        try:
            company = card.find_element(By.XPATH, ".//a[contains(@class,'comp-name')]").text.strip()
        except (NoSuchElementException, StaleElementReferenceException):
            pass
        jobs.append({"title": title, "company": company, "link": link})
    return jobs


def quota_exceeded() -> bool:
    return bool(driver.find_elements(By.XPATH, "//*[contains(translate(normalize-space(.),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'daily quota')]"))


# Tried in order; whichever matches first is clicked. Naukri currently favours
# "Apply on company site" - plain "Apply" is the fallback for jobs still on Naukri's own form.
apply_button_xpaths = [
    "//button[@id='company-site-button']",
    "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
    "'apply on company site')]",
    "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply')]",
]


def apply_to_current_job() -> str:
    '''
    Clicks Apply on the open job page. Returns the status to record:
    - "Applied (Naukri form)" - Naukri's own short form, filled and submitted here.
    - "External - apply manually: <link>" - a new tab opened to the company's own site;
      that tab is closed and the link saved, since the bot can't fill in a site it's
      never seen before.
    - "Failed - ..." / "QUOTA_EXCEEDED" otherwise.
    '''
    buffer(3)
    if quota_exceeded():
        return "QUOTA_EXCEEDED"
    main_tab = driver.current_window_handle
    clicked = False
    for xp in apply_button_xpaths:
        try:
            WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, xp))).click()
            clicked = True
            break
        except (TimeoutException, NoSuchElementException):
            continue
    if not clicked:
        return "Failed - no Apply button found"
    buffer(2)

    if len(driver.window_handles) > 1:
        for handle in driver.window_handles:
            if handle == main_tab: continue
            driver.switch_to.window(handle)
            company_link = driver.current_url
            driver.close()
            driver.switch_to.window(main_tab)
            return f"External - apply manually: {company_link}"

    # Still on Naukri: its own short form, when it appears, asks only for first/last name.
    try:
        field = driver.find_element(By.ID, "CUSTOM-FIRSTNAME")
        field.clear(); field.send_keys(first_name)
    except NoSuchElementException:
        pass
    try:
        field = driver.find_element(By.ID, "CUSTOM-LASTNAME")
        field.clear(); field.send_keys(last_name)
    except NoSuchElementException:
        pass
    try:
        driver.find_element(By.XPATH, "//*[normalize-space(.)='Submit and Apply']").click()
        buffer(2)
        return "Applied (Naukri form)"
    except NoSuchElementException:
        pass

    return "Applied (clicked Apply)"


def run() -> None:
    if not naukri_username or not naukri_password:
        print_lg("naukri_username / naukri_password are not set (Naukri tab in the control panel) - skipping Naukri.")
        return
    try:
        if not login_naukri():
            return
    except (NoSuchWindowException, WebDriverException) as e:
        logger.error("Browser closed or became invalid while logging in to Naukri.", exc_info=e)
        return

    recorded_links = get_recorded_naukri_links()
    applied_count = 0

    for keyword in search_terms:
        if applied_count >= naukri_max_applications: break
        for page in range(1, naukri_pages_per_keyword + 1):
            if applied_count >= naukri_max_applications: break
            url = build_search_url(keyword, page)
            print_lg(f'\n>>>> Naukri: searching "{keyword}" (page {page}) <<<<\n')
            try:
                driver.get(url)
            except (NoSuchWindowException, WebDriverException) as e:
                logger.error("Browser closed or became invalid. Stopping Naukri run.", exc_info=e)
                return
            buffer(3)

            try:
                jobs = collect_job_cards()
            except (NoSuchWindowException, WebDriverException) as e:
                logger.error("Browser closed or became invalid. Stopping Naukri run.", exc_info=e)
                return
            print_lg(f"Found {len(jobs)} job cards.")

            for job in jobs:
                if applied_count >= naukri_max_applications: break
                if job["link"] in recorded_links: continue
                print_lg(f'Visiting "{job["title"]} | {job["company"] or "Unknown company"}"')
                try:
                    driver.get(job["link"])
                    status = apply_to_current_job()
                except (NoSuchWindowException, WebDriverException) as e:
                    logger.error("Browser closed or became invalid. Stopping Naukri run.", exc_info=e)
                    return
                except Exception as e:
                    logger.warning("Failed on this job, skipping it. %s", type(e).__name__)
                    critical_error_log("In Naukri apply", e)
                    status = f"Failed - {type(e).__name__}"

                if status == "QUOTA_EXCEEDED":
                    print_lg("Naukri's daily application quota is reached. Stopping.")
                    return

                record_naukri(job["title"], job["company"], status, job["link"])
                recorded_links.add(job["link"])
                if status.startswith("Applied"): applied_count += 1
                print_lg(f"-> {status}")

    print_lg(f"\nNaukri run finished. {applied_count} applications submitted this run. "
              f"See {naukri_file_name} for the full list, including company-site links to finish by hand.\n")


if __name__ == "__main__":
    run()
