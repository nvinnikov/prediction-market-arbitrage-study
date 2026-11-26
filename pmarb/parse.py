"""Reading market questions and titles. Most rules here exist because a looser version produced a false fork."""
import re
import unicodedata

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_NUMBER = {m.lower(): i + 1 for i, m in enumerate(MONTHS.split("|"))}
BY_DATE = re.compile(r"\bby (?:the end of )?(%s) (\d{1,2}),? (\d{4})" % MONTHS, re.I)
NUMBER = re.compile(r"(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)\s?([kmbt]?)(?![\w%])", re.I)
LEVEL = re.compile(r"[↑>≥ ]*(\d[\d,]*(?:\.\d+)?)\s?([kmbt]?)\+?", re.I)
SUFFIX = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
UPWARD = re.compile(r"above|over|reach|hit|at least|exceed|higher|more than|greater|\+", re.I)
NOT_UPWARD = re.compile(r"below|under|dip|less|between|fewer|O/U|spread|drop", re.I)
STRIKE_LABEL = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kK]?)")
STRIKE_IN_QUESTION = re.compile(r"\$(\d[\d,]*(?:\.\d+)?)\s*([kK]?)")
STOP_WORDS = set("will the a an of in on by be to for at is and or who what which when vs this that do does it as "
                 "from 2 us winner win next".split())
# Words that make two titles about the same teams or people different questions.
QUALIFIERS = ("halftime|half|first team|jury|1st|2nd|3rd|place|odds leader|seats|direction|game [0-9]|quarter|period|"
              "inning|map|set|leader on|run for|announce|caucus|popular|vote")
SIDE_MARKET = re.compile(r"over|under|spread|o/u|handicap|odd|even|set |map |game |quarter|half|inning")


def by_date(question):
    """(year, month, day) of a 'by <Month> <day>, <year>' deadline, or None. A deadline without a year is not read:
    guessing the year of 'by December 31' once produced a false date ladder."""
    d = BY_DATE.search(question or "")
    return (int(d.group(3)), MONTH_NUMBER[d.group(1).lower()], int(d.group(2))) if d else None


def date_template(question):
    """The question with its deadline replaced, so the markets of one date ladder share a template."""
    return BY_DATE.sub("by DATE", question)


def number_template(question):
    """The question with every number replaced, so the rungs of one level ladder share a template."""
    return NUMBER.sub("NUM", question)


def level(label):
    """Threshold in an outcome label such as '↑ 180,000', '$10B' or '40+'; None for any other label."""
    m = LEVEL.fullmatch((label or "").replace("$", "").strip())
    return float(m.group(1).replace(",", "")) * SUFFIX[m.group(2).lower()] if m else None


def is_upward(question):
    """True for 'above / reach / at least' questions, where a higher level is harder to reach."""
    return bool(UPWARD.search(question)) and not NOT_UPWARD.search(question)


def strike(label, question):
    """Strike of a crypto level market. The outcome label is tried first; in the question only a $-number counts,
    so the dates in 'Will Bitcoin reach $100k November 24-30?' are not taken for the strike."""
    n = STRIKE_LABEL.search(label or "") or STRIKE_IN_QUESTION.search(question or "")
    if not n:
        return None
    return float(n.group(1).replace(",", "")) * (1000 if n.group(2) else 1)


def normalize_name(s):
    """ASCII, lower case, without club prefixes: 'Atlético Madrid FC' and 'Atletico Madrid' become equal."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9% .+-]", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"\b(fc|the|cf|afc)\b", " ", s)).strip(" .")


def title_words(s):
    return set(re.findall("[a-z0-9]+", normalize_name(s))) - STOP_WORDS


def same_event(poly_title, kalshi_title, outcomes, end_gap_days):
    """Whether a Polymarket and a Kalshi event that share outcome names ask the same question.
    Rejects pairs whose qualifiers differ (a match against its halftime market), whose years differ, two-outcome
    pairs that end more than 3 days apart, and pairs whose titles share less than half of their words."""
    a, b = poly_title.lower(), kalshi_title.lower()
    if set(re.findall(QUALIFIERS, a)) != set(re.findall(QUALIFIERS, b)):
        return False
    years_a, years_b = set(re.findall(r"20[2-3]\d", a)), set(re.findall(r"20[2-3]\d", b))
    if years_a and years_b and not years_a & years_b:
        return False
    if outcomes == 2:
        return end_gap_days <= 3
    x, y = title_words(a), title_words(b)
    return len(x & y) / max(1, min(len(x), len(y))) >= .5 and end_gap_days <= 400
