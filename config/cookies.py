"""Static cookie management for API authentication.

Note: In production, implement proper session management.
These cookies are for development/testing purposes.
"""

import os
from typing import Dict

# Default cookies - update these with valid session cookies
DEFAULT_COOKIES = """
_fbp=fb.1.1770879458768.8455121605649369;
DEVICEINFO=844C8DDCD52ADB58A94139DF996F19CD2915ADF24FE3DA911FB2687AC2670F2247C6952DA5B23F319D95ACB43F847EAD62BAEA5099221ECE7BBE9824FE3AFF6EF19B1C44C6CC7EEF3775C331E516BA0FB328096732050B575728AB;
chatbot=true;
merchantType=PayUbiz;
user_uuid=11ee-e131-564fca32-a991-0a36b7d4b7a7;
coherenceToken=072e40a0902ca1a2ed93b7b48fbf88d4abcf396fbc174f26833df044691b1988;
PHPSESSID=bmvj293h6unkjj24mnqvaublen;
connect.sid=s%3Af08bVuU3xs1NvDRXqh2Xr1zypgmdpuSm.63dDMcBgPuFWj0lOgBzbuMSGbP32KgmQXB%2BUnVjjDRY
""".strip()


def parse_cookie_string(cookie_string: str) -> Dict[str, str]:
    """Parse a cookie string into a dictionary."""
    cookies = {}
    for item in cookie_string.replace("\n", "").split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def get_cookies() -> Dict[str, str]:
    """Get cookies for API requests.
    
    Priority:
    1. Environment variable HEALTHCHECK_COOKIES
    2. Default cookies defined above
    """
    cookie_string = os.getenv("HEALTHCHECK_COOKIES", DEFAULT_COOKIES)
    return parse_cookie_string(cookie_string)


def get_cookie_header() -> str:
    """Get cookies formatted as a header string."""
    cookies = get_cookies()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())
