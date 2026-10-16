from quotable.ngrams import letter_runs, load_counts, trigrams


def test_letter_runs_keep_two_or_more_letters_and_fold_accents():
    assert letter_runs("Hernández 4$44 J, ab-cd 12ef") == ["hernandez", "ab", "cd", "ef"]


def test_trigrams_pad_so_every_letter_is_scored():
    assert trigrams("ab") == ["^^a", "^ab", "ab$"]


def test_reference_counts_look_like_english():
    counts = load_counts()
    assert counts["^^t"] > counts["^^x"]
    assert counts["the"] > 100 * counts.get("qzx", 1)
    assert all(len(key) == 3 for key in counts)
