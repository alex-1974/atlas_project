from atlas.structure.evidence import compute_block_evidence_dict


def test_toc_signals_are_exposed():
    text = "Contents\n1 Introduction ........ 3\n2 Methods ........ 7\n3 Results ........ 12"
    ev = compute_block_evidence_dict(text)
    assert ev["contains_contents_marker"] is True
    assert ev["toc_like"] > 0.4
    assert ev["leader_dot_ratio"] > 0.2
    assert ev["line_end_digit_ratio"] > 0.2


def test_author_and_affiliation_signals_are_exposed():
    text = "Jane Doe, John Smith\nDepartment of History\nUniversity of Vienna\njane@example.org"
    ev = compute_block_evidence_dict(text)
    assert ev["contains_email"] is True
    assert ev["contains_affiliation_keyword"] is True
    assert ev["author_like"] > 0.2
    assert ev["affiliation_like"] > 0.2


def test_parenthetical_citation_signal_is_exposed():
    text = "This claim has been discussed repeatedly (Smith 1999; Müller 2004) in the literature."
    ev = compute_block_evidence_dict(text)
    assert ev["contains_parenthetical_citation"] is True
    assert ev["parenthetical_citation_count"] >= 1
    assert ev["parenthetical_citation_like"] > 0.2
