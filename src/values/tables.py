"""Values of one catalog table, copied from the BPS API without changes: no number is computed or
rounded here. All three table types come back in one shape:

    {"title", "unit", "period", "periods", "columns", "rows": [{"label", "values", "highlight"}],
     "note", "source", "updated", "fetched_at"}
"""

import re

from lxml import html as lxml_html

from src.ingestion.build_catalog import clean
from src.retrieval.regions import domains, normalize
from src.values.bps import BpsError, get

PERIODS_SHOWN = 10  # the API lists periods newest first, 10 per page
NO_UNIT = {"", "tidak ada satuan", "tidak ada", "tanpa satuan"}


def column_label(turvar, turtahun, year):
    """Sub-variable plus sub-period; id 0 means none ("Tidak ada", or "Tahun" for yearly data). BPS sends the id as a
    number or a string, and labels with stray spaces."""
    parts = [" ".join(x["label"].split()) for x in (turvar, turtahun) if str(x["val"]) != "0"]
    return " ".join(parts) or year


def var_table(domain, var_id, period=None):
    periods = get(f"/api/list/model/th/domain/{domain}/key/{{key}}", {"var": var_id})[0]["data"]
    if len(periods) != 2:
        raise BpsError("no periods")
    periods = periods[1]
    chosen = next((p for p in periods if str(p["th_id"]) == period), None) if period else periods[0]
    if chosen is None:
        raise ValueError("unknown period")
    d, fetched_at = get(f"/api/list/model/data/domain/{domain}/var/{var_id}/th/{chosen['th_id']}/key/{{key}}")
    if d.get("data-availability") != "available":
        raise BpsError("no data")
    var, year = d["var"][0], d["tahun"][0]
    columns = [(tv, tt) for tv in d["turvar"] for tt in d["turtahun"]]
    rows = [
        {
            "label": vv["label"],
            # key = vervar + var + turvar + tahun + turtahun, each as its API id
            "values": [d["datacontent"].get(f"{vv['val']}{var['val']}{tv['val']}{year['val']}{tt['val']}") for tv, tt in columns],
        }
        for vv in d["vervar"]
    ]
    keep = [i for i in range(len(columns)) if any(r["values"][i] is not None for r in rows)]  # sub-periods with no data
    return {
        "title": var["label"],
        "unit": None if normalize(var["unit"] or "") in NO_UNIT else var["unit"],
        "period": chosen["th"],
        "periods": [{"id": str(p["th_id"]), "label": p["th"]} for p in periods[:PERIODS_SHOWN]],
        "columns": [column_label(tv, tt, chosen["th"]) for tv, tt in (columns[i] for i in keep)],
        "rows": [{"label": r["label"], "values": [None if r["values"][i] is None else str(r["values"][i]) for i in keep]} for r in rows],
        "note": clean(var.get("note")) or None,
        "source": None,
        "updated": d.get("last_update"),
        "fetched_at": fetched_at,
    }


def simdasi_table(domain, table_id, years, period=None):
    year = int(period) if period else max(years)
    if year not in years:
        raise ValueError("unknown period")
    d, fetched_at = get(
        f"/api/interoperabilitas/datasource/simdasi/id/25/wilayah/{domain}000/tahun/{year}/id_tabel/{table_id}/key/{{key}}"
    )
    d = d["data"][1]
    if not d.get("data"):
        raise BpsError("no data")
    names = {k: clean(" ".join(filter(None, (c["nama_variabel"], c.get("satuan"))))) for k, c in d["kolom"].items()}
    return {
        "title": clean(d["judul_tabel"]),
        "unit": None,  # units are part of the column names
        "period": str(year),
        "periods": [{"id": str(y), "label": str(y)} for y in sorted(years, reverse=True)[:PERIODS_SHOWN]],
        "columns": list(names.values()),
        "rows": [{"label": clean(r["label"]), "values": [r["variables"].get(k, {}).get("value") for k in names]} for r in d["data"]],  # a row only lists the columns it has a value for
        "note": clean(d.get("catatan")) or None,
        "source": clean(d.get("sumber")) or None,
        "updated": d.get("table_created"),
        "fetched_at": fetched_at,
    }


def html_grid(table_html):
    """Cell texts of an HTML table as rows of equal width; merged cells repeat across their span."""
    grid, spans = [], {}  # spans: column -> (text, rows it still covers)
    for tr in lxml_html.fromstring(table_html).iter("tr"):
        cells, row, col = iter(tr.xpath("./td|./th")), [], 0
        while True:
            if col in spans:
                text, left = spans.pop(col)
                row.append(text)
                if left > 1:
                    spans[col] = (text, left - 1)
                col += 1
                continue
            td = next(cells, None)
            if td is None:
                break
            text = " ".join(td.text_content().split())
            for _ in range(int(td.get("colspan", 1))):
                row.append(text)
                if int(td.get("rowspan", 1)) > 1:
                    spans[col] = (text, int(td.get("rowspan")) - 1)
                col += 1
        grid.append(row)
    width = max(map(len, grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def is_note(row):
    """A title or footnote: one long text, alone or spread over several cells."""
    texts = {c for c in row if c}
    return len(texts) == 1 and len(next(iter(texts))) > 20


def is_banner(row):
    """A header line spread over several columns: a label, then one long text repeated ("Tabel | Judul | Judul | Judul").
    Above the header these carry the title (also in English) and the column group, which the title already says."""
    rest = {c for c in row[1:] if c}
    return len(rest) == 1 and len(next(iter(rest))) > 20 and sum(1 for c in row[1:] if c) >= 2


def is_numbering(row):
    """BPS's column-number row: [1] [2] [3] ..., no data."""
    cells = [c for c in row if c]
    return bool(cells) and all(re.fullmatch(r"[\[(]\d+[\])]", c) for c in cells)


def static_table(domain, table_id):
    """Static tables are Excel exports: title rows, a header row, the data, then footnotes. Rows above the
    header (titles, banners spanning the columns) are dropped, footnotes become the note, the [1] [2] numbering
    row is dropped, and the first other row is the header. Tables with a two-level header show their second header
    row as a first data row."""
    d, fetched_at = get(f"/api/view/domain/{domain}/model/statictable/lang/ind/id/{table_id}/key/{{key}}")
    grid = [row for row in html_grid(d["data"]["table"]) if any(row)]
    start = next((i for i, row in enumerate(grid) if not is_note(row) and not is_banner(row)), len(grid))
    notes = [next(c for c in row if c) for row in grid[start:] if is_note(row)]
    grid = [row for row in grid[start:] if not is_note(row) and not is_numbering(row)]
    if len(grid) < 2:
        raise BpsError("no table")
    used = [i for i in range(len(grid[0])) if any(row[i] for row in grid)]  # Excel pads with empty columns
    return {
        "title": clean(d["data"]["title"]),
        "unit": None,
        "period": None,
        "periods": [],
        "columns": [grid[0][i] for i in used[1:]],
        "rows": [{"label": row[used[0]], "values": [row[i] or None for i in used[1:]]} for row in grid[1:]],
        "note": " ".join(dict.fromkeys(notes)) or None,
        "source": None,
        "updated": d["data"]["updt_date"],
        "fetched_at": fetched_at,
    }


def mark_regions(table, region_ids):
    """Set `highlight` on the rows that are one of the regions the visitor asked about."""
    names = set()
    for d in region_ids:
        info = domains()[d]
        names.add(normalize(info["name"]))
        if info["level"] in ("prov", "national"):
            names.update(info["aliases"])  # "provinsi jawa barat", "jabar", ...
        if info["level"] == "kab":
            names.add(normalize(info["name"].removeprefix("Kabupaten ")))  # province tables label it "Bogor"
    for row in table["rows"]:
        row["highlight"] = re.sub(r"^\d+\.?\s*", "", normalize(row["label"])) in names  # "23. Kota Bandung"
    return table
