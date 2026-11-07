from src.retrieval.coverage import coverage, no_match


def row(title):
    return {"domain": "0000", "title": title, "body": "", "notes": "", "table_code": None}


def test_a_top_result_without_the_topic_words_is_no_match():
    assert no_match("harga bitcoin harga bitcoin", row("Indeks Harga Perdagangan Besar (IHPB) Seksi Bijih Besi"))
    assert no_match("jumlah pondok pesantren banten jumlah pondok pesantren menurut Kabupaten/Kota", row("Jumlah Puskesmas Menurut Kabupaten/Kota di Provinsi Banten"))


def test_a_top_result_with_the_topic_words_is_a_match():
    assert not no_match("inflasi riau Inflasi Provinsi", row("Laju Inflasi Riau Kelompok Pengeluaran"))
    assert coverage("produksi rumput laut", row("Produksi Rumput Laut (Ton)")) == 1.0


def test_generic_and_region_words_do_not_count_as_topic():
    assert coverage("jumlah menurut provinsi di jawa barat", row("Apa saja")) is None  # nothing but generic and region words: no verdict
    assert not no_match("jumlah menurut provinsi", row("Apa saja"))


def test_half_the_topic_words_is_enough():
    assert not no_match("jumlah kasus korupsi", row("Jumlah Kasus Pidana"))  # 1 of 2: 0.5 >= 0.3


def test_the_floor_sits_between_a_quarter_and_a_third_of_the_topic_words():
    assert no_match("alfa bravo charlie delta", row("Alfa"))  # 1 of 4 = 0.25
    assert not no_match("alfa bravo charlie", row("Alfa"))  # 1 of 3 = 0.33
