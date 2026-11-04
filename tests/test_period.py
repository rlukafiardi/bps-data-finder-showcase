from src.retrieval.period import factor, latest_year, of_row, periods


def named(text):
    found = periods(text)
    return found["months"], found["quarters"], found["years"]


def test_month_quarter_year_in_titles_and_questions():
    assert named("Berita Resmi Statistik Provinsi DKI Jakarta Januari 2025") == ({1}, set(), {2025})
    assert named("Pertumbuhan Ekonomi Provinsi Riau Triwulan II-2025") == (set(), {2}, {2025})
    assert named("inflasi riau triwulan 4 2025") == (set(), {4}, {2025})
    assert named("Riau economic growth Q2 2025") == (set(), {2}, {2025})
    assert named("tw 1 2026")[1] == {1} and named("kuartal III 2025")[1] == {3}
    assert named("NTP Agt 2025 dan Mei") == ({8, 5}, set(), {2025})


def test_month_and_year_glued_together():
    assert named("Penumpang penerbangan di Provinsi Aceh pada bulan Desember2024 mencapai 41.810 orang") == ({12}, set(), {2024})


def test_ranges_cover_every_month_and_year_in_between():
    assert named("Perkembangan Pariwisata Januari - Maret 2025") == ({1, 2, 3}, set(), {2025})
    assert named("Inflasi Indonesia Menurut Kelompok Pengeluaran, 2020-2023")[2] == {2020, 2021, 2022, 2023}


def test_years_that_are_not_periods_are_ignored():
    assert named("[Seri 2010] PDRB Menurut Pengeluaran")[2] == set()
    assert named("Inflasi (2018=100) Menurut Kelompok")[2] == set()
    assert named("Inflasi Kota Jambi (tahun dasar 2012)")[2] == set()
    assert named("[Metode Baru] IPM (Hasil Long Form SP2020)")[2] == set()
    assert named("Harga Konstan 2010 September 2025") == ({9}, set(), {2025})


def test_q_to_q_is_not_a_quarter():
    assert named("Inflasi Triwulanan (Q to Q) Provinsi Riau")[1] == set()
    assert named("tumbuh 5,02 persen (Q-to-Q), 4,9 persen (Y-on-Y)")[1] == set()


def test_factor_boosts_agreement_and_demotes_difference():
    asked = periods("BRS DKI Januari 2025")
    same = factor(asked, periods("Berita Resmi Statistik Januari 2025"))
    other_year = factor(asked, periods("Berita Resmi Statistik Januari 2026"))
    other_month = factor(asked, periods("Berita Resmi Statistik Juli 2025"))
    assert same > 1 and other_month < 1 and other_year < 1
    assert same > other_year and same > other_month
    assert factor(asked, periods("Tingkat Pengangguran Terbuka menurut Provinsi")) == 1.0  # no period: leave alone
    assert factor(periods("tingkat pengangguran"), periods("Januari 2025")) == 1.0  # nothing asked


def test_dalam_angka_tables_use_the_years_bps_has_them_for():
    row = {"title": "Luas Daerah Menurut Kecamatan", "type": "simdasi", "years": [2023, 2024, 2025]}
    assert of_row(row)["years"] == {2023, 2024, 2025}
    assert factor(periods("luas daerah 2025"), of_row(row)) > 1 > factor(periods("luas daerah 2019"), of_row(row))


def test_latest_year_of_a_row():
    archive = {"title": "Jumlah Penduduk Miskin Menurut Kabupaten/Kota (Ribu Orang), 2002-2016", "type": "statictable", "years": None}
    assert latest_year(archive) == 2016
    assert latest_year({"title": "Luas Daerah", "type": "simdasi", "years": [2023, 2025]}) == 2025
    assert latest_year({"title": "Jumlah Penduduk Miskin (Ribu Jiwa)", "type": "var", "years": None}) is None
    assert latest_year({"title": "Inflasi (2018=100)", "type": "var", "years": None}) is None
