'''
Settings for the Naukri.com bot (runNaukriBot.py). Separate from LinkedIn's config/*.py
files since Naukri has its own login and its own daily application quota.

Job search terms and location are NOT duplicated here - they come from
config/search.py's `search_terms` and `search_location`, so you only fill those in once.
'''


###################################################### CONFIGURE YOUR NAUKRI ACCOUNT HERE ######################################################

# Login credentials for Naukri.com
naukri_username = ""        # Your Naukri email, in quotes
naukri_password = ""        # Your Naukri password, in quotes

# Most jobs to apply to (or list) in one run. Naukri enforces its own daily quota on top
# of this - the bot stops on its own when Naukri says the quota is reached.
naukri_max_applications = 50        # Any number > 0, don't put in quotes

# How many result pages to read per search term.
naukri_pages_per_keyword = 2        # Any number > 0, don't put in quotes


############################################################################################################

# --- Load user settings saved by the local control panel (user_config.json).
# --- No-op if that file is absent: values fall back to the defaults above.
from config import _overrides as _o
_o.apply(__name__, globals())
############################################################################################################
