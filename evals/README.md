# Golden set

`golden_set.csv`: one row per question, with every equally valid answer.

- `question`: as you would type it, Bahasa or English, with acronyms if you'd use them.
- `targets`: `type:domain:id`, several separated by `|`. Types: `var` (dynamic table), `statictable`,
  `simdasi` (Dalam Angka table; id = table code like `4.1.3`), `publication`, `pressrelease`.
  Domain is the 4-digit BPS code of the site the table sits on (`0000` national, `3200` Jawa Barat,
  `3273` Kota Bandung); a national table "menurut Kabupaten/Kota" is a valid target for a kab/kota question.
  The id is in the BPS link: var / static table id after base64-decoding the link token, pub_id, brs_id.
- `source`: `claude` (written from a need), `claude-seeded` (written from a random catalog item),
  `claude-ladder` (kab/kota without its own table), `claude-period` (month / quarter / year in the question), or
  `owner` / `user` for real searches. Generated questions were labelled with keyword filters plus pooled
  judging, but are still easier than real ones: add real questions when they become available (e.g. from
  app logs) and report them separately.

    uv run python -m evals.run_eval
