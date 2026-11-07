"""Does the best result contain the words of the question? When it contains almost none, BPS probably has no data on the
topic: the other results are then just the nearest tables ("harga bitcoin" -> producer price indexes), and a cutoff on score
cannot tell, because every score is as weak as the first."""

from src.retrieval.bm25 import bm25_text, tokenize
from src.retrieval.regions import domains, find_regions, strip_regions

# words that name the kind of table, not the topic, or fill the question
GENERIC = set("jumlah menurut kabupaten kota provinsi persentase data tahun per banyaknya rata indonesia statistik di dan yang untuk ke dari pada apa siapa berapa hari ini harga".split())
# on the 88 golden questions the right top result has at least 0.4 (median 0.83); the wrong top results of unanswerable
# questions have 0.0-0.2
MIN_COVERAGE = 0.3


def coverage(text, hit):
    """Share of the topic words in `text` that the title, summary and notes of `hit` contain; None if the text has none."""
    regions = find_regions(text)
    region_words = {w for d in regions for w in tokenize(domains()[d]["name"])}
    words = {t for t in tokenize(strip_regions(text, regions)) if t not in GENERIC and len(t) > 2} - region_words
    if not words:
        return None
    have = set(tokenize(bm25_text(hit)))
    return sum(w in have for w in words) / len(words)


def no_match(text, hit):
    share = coverage(text, hit)
    return share is not None and share < MIN_COVERAGE
