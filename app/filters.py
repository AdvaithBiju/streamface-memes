"""Caption checks for viewer-supplied text."""
import re

from better_profanity import profanity

profanity.load_censor_words()

# Viewers shouldn't be able to put links or @-pings on the stream.
LINK_RE = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|net|org|gg|tv|io|ly|me|xyz)\b)", re.I)
ALLOWED_CHARS_RE = re.compile(r"[^\w\s.,!?'\"&%#:;()\-+/|*~]", re.UNICODE)


class CaptionError(ValueError):
    pass


def clean_caption(text: str, max_length: int) -> str:
    """Normalise a viewer caption or raise CaptionError explaining why it's refused."""
    text = " ".join((text or "").split())  # collapse whitespace/newlines
    # Check before stripping characters, which would otherwise remove the '@' or '://'.
    if "@" in text:
        raise CaptionError("no @mentions in captions")
    if LINK_RE.search(text):
        raise CaptionError("links aren't allowed in captions")
    text = ALLOWED_CHARS_RE.sub("", text).strip()
    if len(text) > max_length:
        raise CaptionError(f"caption is too long (max {max_length} characters)")
    if profanity.contains_profanity(text):
        raise CaptionError("caption didn't pass the language filter")
    return text
