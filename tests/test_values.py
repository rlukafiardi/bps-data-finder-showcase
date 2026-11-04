import time

import httpx
import pytest

from src.values import bps, tables

EXCEL_TABLE = """<table>
<tr><td colspan=4>Jumlah Penduduk Miskin Menurut Kabupaten/Kota di Jawa Barat, 2002-2003</td></tr>
<tr><td></td><td></td><td></td><td></td></tr>
<tr><td>Wilayah</td><td>2002</td><td>2003</td><td></td></tr>
<tr><td>[1]</td><td>[2]</td><td>[3]</td><td></td></tr>
<tr><td>1. Bogor</td><td>4.938,3</td><td>-</td><td></td></tr>
<tr><td>23. Kota Bandung</td><td>5,00</td><td>4,5</td><td></td></tr>
<tr><td colspan=4>Sumber: BPS, Susenas, dengan catatan yang cukup panjang</td></tr>
</table>"""


def test_html_grid_repeats_merged_cells():
    grid = tables.html_grid("<table><tr><td rowspan=2>A</td><td colspan=2>B</td></tr><tr><td>c</td><td>d</td></tr></table>")
    assert grid == [["A", "B", "B"], ["A", "c", "d"]]


def test_static_table_title_header_data_and_footnote(monkeypatch):
    payload = {"data": {"table": EXCEL_TABLE, "title": "Jumlah Penduduk Miskin", "updt_date": "2018-04-27"}}
    monkeypatch.setattr(tables, "get", lambda path, params=None: (payload, 0.0))
    t = tables.static_table("3200", "121")
    assert t["columns"] == ["2002", "2003"]  # title row and empty column dropped
    assert [r["label"] for r in t["rows"]] == ["1. Bogor", "23. Kota Bandung"]  # the [1] [2] numbering row is dropped
    assert t["rows"][0]["values"] == ["4.938,3", "-"]  # text exactly as BPS wrote it
    assert t["note"] == "Sumber: BPS, Susenas, dengan catatan yang cukup panjang"


def test_mark_regions_matches_numbered_and_bare_names():
    t = {"rows": [{"label": "1. Bogor"}, {"label": "23. Kota Bandung"}, {"label": "Provinsi Jawa Barat"}, {"label": "Bandung"}]}
    marked = tables.mark_regions(t, ["3201", "3273", "3200"])  # Kabupaten Bogor, Kota Bandung, Jawa Barat
    assert [r["highlight"] for r in marked["rows"]] == [True, True, True, False]  # bare "Bandung" is the kabupaten


def test_var_table_value_key_and_empty_column(monkeypatch):
    periods = {"data": [{}, [{"th_id": 126, "th": "2026"}, {"th_id": 125, "th": "2025"}]]}
    data = {
        "data-availability": "available", "last_update": "2026-05-06",
        "var": [{"val": 543, "label": "TPT", "unit": "Persen", "note": "<p>Sumber: Sakernas</p>"}],
        "turvar": [{"val": "0", "label": "Tidak ada"}], "tahun": [{"val": 126, "label": "2026"}],
        "turtahun": [{"val": 189, "label": "Februari"}, {"val": 190, "label": "Agustus"}],
        "vervar": [{"val": 1100, "label": "ACEH"}, {"val": 1200, "label": "SUMATERA UTARA"}],
        "datacontent": {"11005430126189": 5.88, "12005430126189": 5.01},  # Agustus has no data
    }
    monkeypatch.setattr(tables, "get", lambda path, params=None: ((data if "/model/data/" in path else periods), 0.0))
    t = tables.var_table("0000", "543")
    assert t["period"] == "2026" and t["columns"] == ["Februari"]
    assert [(r["label"], r["values"]) for r in t["rows"]] == [("ACEH", ["5.88"]), ("SUMATERA UTARA", ["5.01"])]
    assert t["note"] == "Sumber: Sakernas"


def test_var_table_unknown_period(monkeypatch):
    monkeypatch.setattr(tables, "get", lambda path, params=None: ({"data": [{}, [{"th_id": 126, "th": "2026"}]]}, 0.0))
    with pytest.raises(ValueError):
        tables.var_table("0000", "543", period="1")


def test_bps_client_busy_cache_and_key_never_in_error(monkeypatch):
    monkeypatch.setenv("BPS_API_KEY", "secretkey123")
    monkeypatch.setattr(bps, "cache", {})
    monkeypatch.setattr(bps, "next_slot", time.monotonic() + 100)
    with pytest.raises(bps.Busy):
        bps.get("/x/key/{key}")

    monkeypatch.setattr(bps, "next_slot", 0.0)
    monkeypatch.setattr(bps, "SLOT_S", 0.0)

    def fail(url, **kw):
        raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(bps.httpx, "get", fail)
    with pytest.raises(bps.BpsError) as e:
        bps.get("/x/key/{key}")
    assert "secretkey123" not in str(e.value) and e.value.__cause__ is None and e.value.__suppress_context__

    calls = []
    monkeypatch.setattr(bps.httpx, "get", lambda url, **kw: calls.append(url) or httpx.Response(200, json={"ok": 1}))
    first = bps.get("/y/key/{key}")
    assert bps.get("/y/key/{key}") == first and len(calls) == 1  # second call served from cache


def test_simdasi_table_row_without_some_columns(monkeypatch):
    payload = {"data": [{}, {
        "judul_tabel": "Penduduk Miskin", "table_created": "2026-02-20", "catatan": "&lt;p&gt;Catatan&lt;/p&gt;", "sumber": "&lt;p&gt;BPS&lt;/p&gt;",
        "kolom": {"a": {"nama_variabel": "Jumlah", "satuan": "ribu jiwa"}, "b": {"nama_variabel": "Persentase", "satuan": None}},
        "data": [{"label": "Bogor", "variables": {"a": {"value": "1.234,5"}}},
                 {"label": "Jawa Barat", "variables": {"a": {"value": "4.000"}, "b": {"value": "7,1"}}}],
    }]}
    monkeypatch.setattr(tables, "get", lambda path, params=None: (payload, 0.0))
    t = tables.simdasi_table("3200", "id", [2024, 2025])
    assert t["period"] == "2025" and t["columns"] == ["Jumlah ribu jiwa", "Persentase"]
    assert [r["values"] for r in t["rows"]] == [["1.234,5", None], ["4.000", "7,1"]]
    assert t["note"] == "Catatan" and t["source"] == "BPS"
    with pytest.raises(ValueError):
        tables.simdasi_table("3200", "id", [2024, 2025], period="2019")


def test_var_table_yearly_columns_without_tahun_and_no_unit(monkeypatch):
    # Jumlah Akomodasi Hotel Bintang, DI Yogyakarta 2025 (var 3400:75), two of its rows; values as BPS returns them
    periods = {"data": [{}, [{"th_id": 125, "th": "2025"}]]}
    data = {
        "data-availability": "available",
        "var": [{"val": 75, "label": "Jumlah Akomodasi Hotel Bintang", "unit": "Tidak Ada Satuan", "note": ""}],
        "turvar": [{"val": 164, "label": "Akomodasi "}, {"val": 165, "label": "Kamar"}, {"val": 166, "label": "Tempat Tidur "}],
        "tahun": [{"val": 125, "label": "2025"}], "turtahun": [{"val": 0, "label": "Tahun"}],
        "vervar": [{"val": 3400, "label": "D.I. Yogyakarta"}, {"val": 3401, "label": "Kulonprogo"}],
        "datacontent": {"3400751641250": 222, "3400751651250": 21, "3400751661250": 32,
                        "3401751641250": 6, "3401751651250": 723, "3401751661250": 1},
    }
    monkeypatch.setattr(tables, "get", lambda path, params=None: ((data if "/model/data/" in path else periods), 0.0))
    t = tables.var_table("3400", "75")
    assert t["columns"] == ["Akomodasi", "Kamar", "Tempat Tidur"]
    assert t["unit"] is None
    assert [r["values"] for r in t["rows"]] == [["222", "21", "32"], ["6", "723", "1"]]  # as given, odd as they look


def test_column_label_falls_back_to_the_year():
    assert tables.column_label({"val": "0", "label": "Tidak ada"}, {"val": 0, "label": "Tahun"}, "2025") == "2025"
    assert tables.column_label({"val": "0", "label": "Tidak ada"}, {"val": 189, "label": "Februari"}, "2026") == "Februari"
