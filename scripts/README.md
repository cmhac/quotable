# Scripts

## `build_trigrams.py`

Builds `quotable/text/trigram_counts.json`, the English character-trigram counts
the text-layer check (spec 001) compares page text against. Maintainers run it; the library
never touches the network.

```
uv run python scripts/build_trigrams.py                       # downloads the books
uv run python scripts/build_trigrams.py --corpus-dir DIR      # or reads DIR/pg<id>.txt
```

Corpus: ten public-domain books from Project Gutenberg
(`https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt`), only the text between the
`*** START OF` and `*** END OF` markers. The list, with ids and titles, is `BOOKS` in the script
and is also written into the data file. Licence: public domain in the United States; the
Project Gutenberg licence header and footer are excluded from the counts.

The output is deterministic for the same texts. Re-run it only when changing the corpus.
