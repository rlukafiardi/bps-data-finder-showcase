from src.ingestion.build_catalog import built_link


def test_press_release_links_end_with_a_slug_and_publications_do_not():
    pr = {"type": "pressrelease", "domain": "5100", "source_id": "169528", "date": "2026-08-03", "title": "Perkembangan Pariwisata Provinsi Bali Juni 2026"}
    assert built_link(pr, "https://bali.bps.go.id") == "https://bali.bps.go.id/id/pressrelease/2026/08/03/169528/perkembangan-pariwisata-provinsi-bali-juni-2026.html"
    pub = {"type": "publication", "domain": "5100", "source_id": "ea58ebd2581661824f50facd", "date": "2026-10-23", "title": "Laporan Bulanan"}
    assert built_link(pub, "https://bali.bps.go.id") == "https://bali.bps.go.id/id/publication/2026/10/23/ea58ebd2581661824f50facd"
