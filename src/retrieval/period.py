"""Month, quarter and year in a question or a title, and how well two of them agree.

A title that names the asked period is boosted and one that names a different period is demoted; a title
without a period (most tables) is left alone. Years that are not periods (base years such as "Seri 2010"
or "2018=100", census names such as "SP2020") are ignored.
"""

import re

MONTHS = {
    "januari": 1, "january": 1, "jan": 1, "februari": 2, "february": 2, "feb": 2, "maret": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "mei": 5, "may": 5, "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7,
    "agustus": 8, "august": 8, "agu": 8, "agt": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "october": 10, "okt": 10, "oct": 10, "november": 11, "nov": 11, "desember": 12, "december": 12,
    "des": 12, "dec": 12,
}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
BOOST = {"months": (1.3, 0.7), "quarters": (1.3, 0.7), "years": (1.15, 0.75)}  # (agrees, differs)

MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
NOT_A_PERIOD = re.compile(r"\b(?:tahun dasar|seri|konstan|base year)\s*[\[(]?\d{4}|\b\d{4}\s*=\s*100|\b(?:sp|supas)\s?\d{4}|\bsensus penduduk\s*\d{4}", re.I)
# lookarounds instead of \b: BPS titles sometimes glue them ("Desember2024")
WORD = rf"(?<![a-z])({MONTH})(?![a-z])"
MONTH_RANGE = re.compile(rf"{WORD}\s*[-–—/]\s*{WORD}", re.I)
QUARTER = re.compile(r"(?<![a-z])(?:triwulan|tw|kuartal|quarter|q)\s*\.?\s*(iv|iii|ii|i|[1-4])(?![a-z0-9])", re.I)
YEAR_RANGE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-–—/]\s*((?:19|20)\d{2})(?!\d)")
YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
MAX_YEAR_SPAN = 60


def periods(text):
    """{"months", "quarters", "years"}: sets of what the text names."""
    text = NOT_A_PERIOD.sub(" ", text.lower())
    found = {"months": set(), "quarters": set(), "years": set()}
    for a, b in MONTH_RANGE.findall(text):
        found["months"].update(range(MONTHS[a], MONTHS[b] + 1))
    text = MONTH_RANGE.sub(" ", text)
    found["months"].update(MONTHS[w] for w in re.findall(WORD, text))
    found["quarters"].update(int(q) if q.isdigit() else ROMAN[q] for q in QUARTER.findall(text))
    for a, b in YEAR_RANGE.findall(text):
        if 0 <= int(b) - int(a) <= MAX_YEAR_SPAN:
            found["years"].update(range(int(a), int(b) + 1))
    found["years"].update(int(y) for y in YEAR.findall(YEAR_RANGE.sub(" ", text)))
    return found


def of_row(row):
    """Periods a catalog row covers: its title, or for Dalam Angka tables the years BPS has them for."""
    found = periods(row["title"])
    if row["type"] == "simdasi" and row["years"] is not None:
        found["years"] = {int(y) for y in row["years"]}
    return found


def latest_year(row):
    """Newest year a catalog row covers, or None when its title names no year (most dynamic tables)."""
    years = of_row(row)["years"]
    return max(years) if years else None


def factor(asked, found):
    """Score multiplier: for each of month, quarter and year that both name, boost if they share one."""
    result = 1.0
    for key, (agrees, differs) in BOOST.items():
        if asked[key] and found[key]:
            result *= agrees if asked[key] & found[key] else differs
    return result
