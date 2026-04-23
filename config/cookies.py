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
_hjSessionUser_2667858=eyJpZCI6IjFlMWFlNzNmLTA1MGYtNWE0My05NTRmLTEyM2JmMDk5ZjljMSIsImNyZWF0ZWQiOjE3NzA5NTk1MzIyMDQsImV4aXN0aW5nIjp0cnVlfQ==;
_ga_NZHTQZ0XP8=GS2.2.s1772434895$o1$g1$t1772434959$j60$l0$h0;
USERTXNINFO=69b7cff25eecb5.08831439;
chatbot=true;
merchantType=PayUbiz;
_ga_NQZZGM9VX7=GS2.1.s1776155258$o5$g1$t1776155437$j60$l0$h0;
_gid=GA1.2.360053729.1776664788;
_clck=11xbbcp%5E2%5Eg5e%5E0%5E2234;
_gcl_au=1.1.463689637.1770879458.715718427.1776775636.1776775637;
user_uuid=11ee-e131-564fca32-a991-0a36b7d4b7a7;
product=PAYUBIZ;
dashboardPreference=one_dashboard;
product_account_type=PayUbizAccount;
148947_allowed_idle_time_in_seconds=10800;
13225316_allowed_idle_time_in_seconds=10800;
mid=148947;
merchantAccessToken=a59de421570ad142bceb63c0cf290441b1d27b2880f497ce35183d7a44bec8c6;
product_account_uuid=11ed-239d-2cd2aff6-9f22-02e708f88ebc;
merchant_account_uuid=11ed-239d-2cd6b0f6-9f22-02e708f88ebc;
WZRK_G=fd814e8a70ec4ea0897472af0095e090;
_uetsid=23b199d03c7e11f19bc30f32d2cd5dce;
_uetvid=1d85abe058a511f0b8066f248edbcc23;
_clsk=5rlm5a%5E1776777995123%5E26%5E1%5Ea.clarity.ms%2Fcollect;
session_timeout=%222026-04-21T16%3A30%3A15.644Z%22;
test_product_account_uuid=11ee-e132-30ec0d7c-beb7-026e3e71538e;
test_mid=8246679;
testAccessToken=ce1c9e2c3f193378ff378928da226575d446b643139b4c67e0a5d08a8fe66649;
coherenceToken=a89f70b5f9a41ab5a1204fbd1b0a361475a7d4aafadce40a0dab6228d5f43d5c;
PHPSESSID=ebt41k2loofa6ga9d2iitqo0lj;
_hp2_id.3342147043=%7B%22userId%22%3A%221374859576338569%22%2C%22pageviewId%22%3A%224566058231050233%22%2C%22sessionId%22%3A%22403411236510719%22%2C%22identity%22%3Anull%2C%22trackerVersion%22%3A%224.0%22%7D;
_ga_6FW4JBDXF1=GS2.1.s1776835872$o228$g0$t1776835873$j59$l0$h0;
_ga=GA1.2.1360893627.1770878363;
_ga_7CG3P7JYWT=GS2.1.s1776835872$o213$g1$t1776835877$j55$l0$h0;
connect.sid=s%3AMJvmNzioktVtXW5TtLH1pI7pbRD3UrPQ.gBvUarUPRfqai90GHnsNpUI3vOu3xQMvx2%2FONVqqB3w
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
