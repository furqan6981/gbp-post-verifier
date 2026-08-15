"""Google UI discovery hints.

Keep UI-specific values in this module. The checker tries every strategy and
logs failures, so a Google UI change can usually be handled by editing only
this file.
"""

UPDATES_LABELS = (
    "Updates",
    "Posts",
    "From the owner",
    "View all updates",
    "View previous updates",
)

POST_CARD_SELECTORS = (
    "[aria-label='Latest from the owner'] [data-post-id]",
    "[data-post-id]",
    "article",
    "[role='article']",
    "[data-attrid*='post']",
    "[data-attrid*='update']",
    "[aria-label*='post' i]",
    "[aria-label*='update' i]",
)

PROFILE_CONTAINER_SELECTORS = (
    "[data-attrid='kc:/local:one line summary']",
    "[data-attrid*='local']",
    "[role='main']",
    "#search",
)

LOGIN_TEXT = (
    "Sign in",
    "Choose an account",
    "Verify it’s you",
    "Verify it's you",
)

SECURITY_CHALLENGE_TEXT = (
    "captcha",
    "unusual traffic",
    "verify you are human",
    "not a robot",
)
