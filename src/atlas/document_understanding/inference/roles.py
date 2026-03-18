from __future__ import annotations

from atlas.document_understanding.inference.early_meta import detect_early_meta_signals


ROLE_TITLE = "title"
ROLE_AUTHOR = "author"
ROLE_HEADING = "heading"
ROLE_BODY = "body"
ROLE_REFERENCE = "reference"
ROLE_CAPTION = "caption"
ROLE_HEADER = "header"
ROLE_FOOTER = "footer"
ROLE_NOISE = "noise"


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _function_word_count(text: str) -> int:
    low = " ".join((text or "").strip().split()).lower()
    if not low:
        return 0

    function_words = {
        "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "for", "to",
        "from", "with", "by", "as", "that", "this", "these", "those", "is", "are",
        "was", "were", "be", "being", "been", "it", "its", "their", "his", "her",
        "they", "we", "our", "also", "about", "into", "than", "then", "which",
        "who", "while", "because", "under", "over", "after", "before", "between",
        "through", "during", "around", "just", "some", "more",
    }
    return sum(1 for token in low.split() if token in function_words)


def _looks_sentence_like(text: str) -> bool:
    value = " ".join((text or "").strip().split())
    if not value:
        return False

    wc = _word_count(value)
    if wc >= 12:
        return True
    if value.endswith((".", "!", "?")) and wc >= 6:
        return True
    if "," in value and wc >= 6:
        return True
    return False


def _looks_like_author_line(text: str) -> bool:
    value = " ".join((text or "").strip().split())
    if not value:
        return False

    low = value.lower()

    blocked = (
        "doi:",
        "doi.org",
        "vol.",
        "volume",
        "issue",
        "issn",
        "figure ",
        "table ",
        "copyright",
        "©",
        "abstract",
        "keywords",
        "references",
        "bibliography",
        "journal",
    )
    if any(marker in low for marker in blocked):
        return False

    if "@" in value:
        return False

    words = [w.strip(",;:.()[]") for w in value.replace("&", " ").replace(" and ", " ").split()]
    words = [w for w in words if w]

    if not (2 <= len(words) <= 8):
        return False

    alpha_words = [w for w in words if any(ch.isalpha() for ch in w)]
    if len(alpha_words) < 2:
        return False

    titlecase_like = 0
    for word in alpha_words:
        if len(word) == 1 and word.isupper():
            titlecase_like += 1
            continue
        if word[:1].isupper():
            titlecase_like += 1

    return titlecase_like >= max(2, len(alpha_words) - 1)


def _is_referenceish_text(text: str) -> bool:
    low = " ".join((text or "").strip().split()).lower()
    if not low:
        return False

    markers = (
        "(eds",
        "(ed.",
        "journal",
        "press",
        "university press",
        "council for british archaeology",
        "vol.",
        "pp.",
        "doi:",
        "retrieved",
        "available at",
        "bibliography",
        "references",
        "va ",
    )
    if any(marker in low for marker in markers):
        return True

    if low.count("(") >= 1 and low.count(")") >= 1 and any(ch.isdigit() for ch in low):
        return True

    return False


def _looks_caption(text: str) -> bool:
    low = text.lower().strip()
    return low.startswith("figure ") or low.startswith("fig. ") or low.startswith("table ")


def _looks_journal_header(text: str) -> bool:
    low = " ".join((text or "").strip().split()).lower()
    if not low:
        return False

    if "doi:" in low or "doi.org" in low:
        return True

    if any(marker in low for marker in ("journal", "vol.", "volume", "issue", "issn", "pp.")):
        return True

    if "vernacular architecture" in low:
        return True

    return False


def _looks_strong_title_line(text: str) -> bool:
    value = " ".join((text or "").strip().split())
    if not value:
        return False

    wc = _word_count(value)
    if wc < 2 or wc > 18:
        return False

    low = value.lower()
    blocked = (
        "doi:",
        "doi.org",
        "journal",
        "vol.",
        "volume",
        "issue",
        "issn",
        "isbn",
        "abstract",
        "keywords",
        "references",
        "bibliography",
        "figure ",
        "table ",
        "copyright",
        "©",
    )
    if any(marker in low for marker in blocked):
        return False

    if _looks_sentence_like(value):
        return False

    if value.endswith(":"):
        return False

    if _caps_ratio(value) >= 0.72 and wc >= 2:
        return True

    if wc <= 10 and value.istitle():
        return True

    return False


def _looks_heading_candidate(
    text: str,
    heading_like: float,
    body_like: float,
    reference_like: float,
) -> bool:
    value = " ".join((text or "").strip().split())
    if not value:
        return False

    wc = _word_count(value)
    func_wc = _function_word_count(value)
    caps = _caps_ratio(value)
    sentence_like = _looks_sentence_like(value)
    referenceish = _is_referenceish_text(value)

    if referenceish:
        return False

    if sentence_like:
        return False

    if wc > 18:
        return False

    # extra negative for this exact recurring false-heading pattern family
    low = value.lower()
    if any(
        phrase in low
        for phrase in (
            "this gets some backing",
            "striking results can be given here",
            "one-bay open hall",
            "buildings dated, all but two",
            "it can hardly be",
        )
    ):
        return False

    if value.endswith(":") and wc <= 14 and body_like <= 0.55:
        return True

    if caps >= 0.70 and wc <= 14 and body_like <= 0.55:
        return True

    if heading_like < 0.72:
        return False

    if body_like > 0.34:
        return False

    if reference_like > 0.40:
        return False

    if func_wc >= 3:
        return False

    if "," in value and wc >= 5:
        return False

    if "." in value and not value.endswith(":"):
        return False

    return True


def _choose_role(
    title_like: float,
    heading_like: float,
    body_like: float,
    reference_like: float,
    caption_like: float,
    noise_like: float,
    repeated_header_footer_hint: bool,
    is_first_on_page: bool,
    is_last_on_page: bool,
) -> str:
    if repeated_header_footer_hint and is_first_on_page:
        return ROLE_HEADER
    if repeated_header_footer_hint and is_last_on_page:
        return ROLE_FOOTER

    scores = {
        ROLE_TITLE: title_like,
        ROLE_HEADING: heading_like,
        ROLE_BODY: body_like,
        ROLE_REFERENCE: reference_like,
        ROLE_CAPTION: caption_like,
        ROLE_NOISE: noise_like,
    }
    return max(scores.items(), key=lambda item: item[1])[0]


def _get_by_block_id(mapping: dict, raw_block_id):
    if raw_block_id in mapping:
        return mapping[raw_block_id]
    sid = str(raw_block_id)
    if sid in mapping:
        return mapping[sid]
    return {}


def compute_roles(repo, document_id: str) -> None:
    print(f"compute_roles entered {document_id}")

    signals = repo.fetch_block_signals(document_id)
    print(f"signals type: {type(signals)}")
    print(f"signals len: {len(signals)}")
    print(f"roles signals: {len(signals)}")

    blocks = repo.fetch_blocks(document_id)

    topo_map: dict[object, dict] = {}
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                block_id,
                is_first_on_page,
                is_last_on_page,
                repeated_header_footer_hint,
                early_block_rank,
                before_first_running_text,
                after_toc_candidate
            from du_block_topology
            where block_id in (
                select block_id
                from du_blocks
                where document_id = %s
            )
            """,
            (document_id,),
        )
        cols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            data = dict(zip(cols, row))
            topo_map[data["block_id"]] = data
            topo_map[str(data["block_id"])] = data

    early_meta = detect_early_meta_signals(blocks, limit=10)
    strong_journal_header = bool(early_meta["strong_journal_header"])
    very_strong_journal_header = bool(early_meta["very_strong_journal_header"])
    strong_thesis_header = bool(early_meta["strong_thesis_header"])

    rows: list[dict] = []

    for block in blocks:
        raw_block_id = block.get("block_id")
        text = (block.get("text") or "").strip()
        low = text.lower()

        sig = _get_by_block_id(signals, raw_block_id) or {}
        topo = _get_by_block_id(topo_map, raw_block_id) or {}

        title_like = float(sig.get("title_like") or 0.0)
        heading_like = float(sig.get("heading_like") or 0.0)
        body_like = float(sig.get("running_text_like") or 0.0)
        reference_like = float(sig.get("reference_like") or 0.0)
        caption_like = float(sig.get("caption_like") or 0.0)
        noise_like = float(sig.get("noise_like") or 0.0)
        author_like = float(sig.get("author_like") or 0.0)

        is_first_on_page = bool(topo.get("is_first_on_page") or False)
        is_last_on_page = bool(topo.get("is_last_on_page") or False)
        repeated_header_footer_hint = bool(topo.get("repeated_header_footer_hint") or False)
        early_block_rank = int(topo.get("early_block_rank") or 999999)
        after_toc_candidate = bool(topo.get("after_toc_candidate") or False)

        word_count = _word_count(text)
        sentence_like = _looks_sentence_like(text)
        referenceish_text = _is_referenceish_text(text)

        is_very_early = early_block_rank <= 8
        is_early_title_window = early_block_rank <= 12

        is_doi_meta = "doi:" in low or "doi.org" in low
        is_journal_meta = _looks_journal_header(text)
        is_copyrightish = "©" in text or "copyright" in low
        is_abstract_marker = low in {"abstract"} or low.startswith("abstract ")
        is_keywords_marker = low in {"keywords"} or low.startswith("keywords")
        is_reference_heading = low in {"references", "bibliography"} or low.startswith("references ")
        is_captionish_text = low.startswith("figure ") or low.startswith("fig. ") or low.startswith("table ")

        role = None

        if repeated_header_footer_hint and is_first_on_page:
            role = ROLE_HEADER
        elif repeated_header_footer_hint and is_last_on_page:
            role = ROLE_FOOTER

        elif is_very_early and is_doi_meta:
            reference_like = 0.0
            body_like = min(body_like, 0.15)
            title_like = min(title_like, 0.10)
            heading_like = min(heading_like, 0.10)
            role = ROLE_HEADER

        elif is_very_early and is_journal_meta and (strong_journal_header or very_strong_journal_header):
            reference_like = 0.0
            body_like = min(body_like, 0.15)
            title_like = min(title_like, 0.10)
            heading_like = min(heading_like, 0.10)
            role = ROLE_HEADER

        elif is_very_early and is_copyrightish and (strong_journal_header or very_strong_journal_header):
            reference_like = 0.0
            body_like = min(body_like, 0.20)
            role = ROLE_HEADER

        elif is_very_early and strong_thesis_header:
            thesis_metaish = any(
                marker in low
                for marker in (
                    "university",
                    "faculty",
                    "department",
                    "submitted to",
                    "for the degree of",
                    "doctoral thesis",
                    "dissertation",
                    "master thesis",
                    "masterarbeit",
                    "doktorarbeit",
                    "habilitationsschrift",
                    "zur erlangung",
                )
            )
            if thesis_metaish:
                reference_like = 0.0
                body_like = min(body_like, 0.20)
                if author_like >= 0.55 or _looks_like_author_line(text):
                    role = ROLE_AUTHOR
                else:
                    role = ROLE_HEADER

        if role is None and caption_like >= 0.55:
            if caption_like >= max(title_like, heading_like, body_like, reference_like):
                role = ROLE_CAPTION

        if role is None and is_captionish_text and word_count <= 40:
            role = ROLE_CAPTION

        if role is None and is_reference_heading:
            role = ROLE_HEADING

        if role is None and (is_abstract_marker or is_keywords_marker):
            role = ROLE_HEADING

        if role is None and is_early_title_window:
            if _looks_strong_title_line(text):
                role = ROLE_TITLE

        if role is None and is_early_title_window:
            if (
                (author_like >= 0.58 or _looks_like_author_line(text))
                and not is_doi_meta
                and not is_journal_meta
                and not is_reference_heading
                and not referenceish_text
                and not _looks_strong_title_line(text)
            ):
                role = ROLE_AUTHOR

        if role is None:
            if is_very_early and (very_strong_journal_header or strong_journal_header):
                if is_doi_meta or is_journal_meta:
                    reference_like = 0.0

        if role is None and reference_like >= 0.62:
            if (
                not is_doi_meta
                and not (is_very_early and is_journal_meta)
                and (referenceish_text or after_toc_candidate or reference_like > body_like + 0.18)
            ):
                role = ROLE_REFERENCE

        if role is None:
            if _looks_heading_candidate(
                text=text,
                heading_like=heading_like,
                body_like=body_like,
                reference_like=reference_like,
            ):
                role = ROLE_HEADING

        if role is None:
            if sentence_like:
                role = ROLE_BODY
            elif body_like >= max(title_like, heading_like, reference_like, caption_like, noise_like):
                role = ROLE_BODY
            elif word_count >= 14:
                role = ROLE_BODY

        if role is None:
            if not is_early_title_window:
                title_like = min(title_like, 0.15)

            if sentence_like:
                heading_like = min(heading_like, 0.15)

            chosen = _choose_role(
                title_like=title_like,
                heading_like=heading_like,
                body_like=body_like,
                reference_like=reference_like,
                caption_like=caption_like,
                noise_like=noise_like,
                repeated_header_footer_hint=repeated_header_footer_hint,
                is_first_on_page=is_first_on_page,
                is_last_on_page=is_last_on_page,
            )

            if chosen == ROLE_TITLE and not is_early_title_window:
                role = ROLE_BODY
            elif chosen == ROLE_HEADING and sentence_like:
                role = ROLE_BODY
            else:
                role = chosen

        row = {
            "block_id": raw_block_id,
            "role": role,
            "title_score": title_like,
            "heading_score": heading_like,
            "body_score": body_like,
            "reference_score": reference_like,
            "caption_score": caption_like,
            "noise_score": noise_like,
        }
        rows.append(row)

    print(f"roles rows: {len(rows)}")
    print(f"roles sample: {rows[:3]}")
    repo.store_block_roles(document_id, rows)
