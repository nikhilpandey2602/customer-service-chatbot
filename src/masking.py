import logging
import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{35}")
# A run of digits with spaces or dashes. Not preceded by a letter, digit or dash,
# so order IDs like ORD-1234567890 are left alone.
_NUMBER_RE = re.compile(r"(?<![\w-])\+?\d[\d \-]{8,20}\d(?!\w)")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _mask_number(match):
    text = match.group(0)
    if _DATE_RE.search(text):
        return text
    digits = re.sub(r"\D", "", text)
    if 13 <= len(digits) <= 19:
        return "[CARD]"
    if 10 <= len(digits) <= 12:
        return "[PHONE]"
    return text


def mask_text(text):
    """Hide emails, phone numbers, card numbers and API keys before text is logged."""
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _API_KEY_RE.sub("[API_KEY]", text)
    return _NUMBER_RE.sub(_mask_number, text)


class MaskingFilter(logging.Filter):
    def filter(self, record):
        record.msg = mask_text(record.getMessage())
        record.args = ()
        return True


def get_logger(name, stream=None):
    """A logger that masks sensitive data in every message it writes."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, MaskingFilter) for f in logger.filters):
        logger.addFilter(MaskingFilter())
    handler = logging.StreamHandler(stream)
    handler.addFilter(MaskingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger