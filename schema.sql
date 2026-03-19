--
-- PostgreSQL database dump
--

\restrict ufpfFcejJh4pNwS87Gj5b9Ch4vS8SQeV66UXdDGyzKeSEd2wsmzBppo5cBRLp8t

-- Dumped from database version 17.9 (Ubuntu 17.9-0ubuntu0.25.10.1)
-- Dumped by pg_dump version 17.9 (Ubuntu 17.9-0ubuntu0.25.10.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: authors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.authors (
    author_id uuid NOT NULL,
    display_name text NOT NULL,
    normalized_name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: document_authors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_authors (
    document_author_id uuid NOT NULL,
    document_id uuid NOT NULL,
    author_id uuid NOT NULL,
    author_position integer,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: document_identifiers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_identifiers (
    identifier_id uuid NOT NULL,
    document_id uuid NOT NULL,
    identifier_type text NOT NULL,
    identifier_value text NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: document_regions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_regions (
    region_id bigint NOT NULL,
    document_id uuid NOT NULL,
    region_index integer NOT NULL,
    region_type text NOT NULL,
    start_char integer NOT NULL,
    end_char integer NOT NULL,
    text text NOT NULL,
    confidence double precision DEFAULT 0.0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: document_regions_region_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_regions_region_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_regions_region_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_regions_region_id_seq OWNED BY public.document_regions.region_id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    document_id uuid NOT NULL,
    file_hash text NOT NULL,
    file_path text NOT NULL,
    relative_path text NOT NULL,
    file_name text NOT NULL,
    file_size bigint,
    top_category text,
    is_review_bucket boolean DEFAULT false NOT NULL,
    is_duplicate_bucket boolean DEFAULT false NOT NULL,
    page_count integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    title text,
    title_source text,
    text_quality text,
    has_text_layer boolean,
    needs_ocr boolean DEFAULT false NOT NULL,
    doc_state text,
    du_document_type text,
    du_document_type_secondary text,
    du_document_type_margin real,
    du_document_type_confidence real,
    du_document_type_ambiguous boolean DEFAULT false NOT NULL
);


--
-- Name: du_block_columns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_columns (
    block_id uuid NOT NULL,
    column_index integer NOT NULL
);


--
-- Name: du_block_context; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_context (
    block_id uuid NOT NULL,
    doc_y_ratio real,
    page_y_ratio real,
    front_matter_score real,
    body_score real,
    back_matter_score real,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_block_geometry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_geometry (
    block_id uuid NOT NULL,
    width real,
    height real,
    center_x real,
    center_y real,
    whitespace_before real,
    whitespace_after real,
    indent_left real,
    indent_right real,
    centeredness real,
    column_hint real,
    near_page_top real,
    near_page_bottom real,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    width_ratio real,
    height_ratio real,
    page_y_ratio real,
    doc_y_ratio real,
    left_margin real,
    right_margin real,
    full_width_like boolean DEFAULT false NOT NULL,
    narrow_width_like boolean DEFAULT false NOT NULL
);


--
-- Name: du_block_layout_features; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_layout_features (
    block_id uuid NOT NULL,
    size_ratio double precision,
    is_all_caps boolean,
    word_count integer,
    ends_with_period boolean,
    starts_with_number boolean,
    starts_with_bullet boolean,
    line_width_ratio double precision,
    is_short_line boolean
);


--
-- Name: TABLE du_block_layout_features; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.du_block_layout_features IS 'Language-independent layout features derived from block text';


--
-- Name: COLUMN du_block_layout_features.size_ratio; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.du_block_layout_features.size_ratio IS 'Relative block size proxy compared to document median';


--
-- Name: COLUMN du_block_layout_features.is_all_caps; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.du_block_layout_features.is_all_caps IS 'True if block text is fully uppercase';


--
-- Name: COLUMN du_block_layout_features.word_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.du_block_layout_features.word_count IS 'Token count in block';


--
-- Name: COLUMN du_block_layout_features.line_width_ratio; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.du_block_layout_features.line_width_ratio IS 'Approximate line width normalized to typical text width';


--
-- Name: du_block_page_furniture_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_page_furniture_signals (
    block_id uuid NOT NULL,
    is_top_band boolean DEFAULT false NOT NULL,
    is_bottom_band boolean DEFAULT false NOT NULL,
    page_number_like boolean DEFAULT false NOT NULL,
    running_header_like boolean DEFAULT false NOT NULL,
    running_footer_like boolean DEFAULT false NOT NULL,
    repeated_across_pages boolean DEFAULT false NOT NULL,
    repeated_same_parity boolean DEFAULT false NOT NULL,
    first_page_meta_like boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: du_block_phase; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_phase (
    block_id uuid NOT NULL,
    phase text NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_block_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_roles (
    block_id uuid NOT NULL,
    role text NOT NULL,
    title_score real,
    heading_score real,
    body_score real,
    reference_score real,
    caption_score real,
    noise_score real,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_block_semantic_micro; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_semantic_micro (
    block_id uuid NOT NULL,
    is_abstract_marker boolean,
    is_keywords_marker boolean,
    is_references_marker boolean,
    is_figure_marker boolean,
    is_table_marker boolean,
    is_appendix_marker boolean,
    contains_doi boolean,
    contains_year boolean,
    contains_citation_bracket boolean,
    contains_citation_author_year boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_block_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_signals (
    block_id uuid NOT NULL,
    title_like real,
    author_like real,
    affiliation_like real,
    date_like real,
    running_text_like real,
    heading_like real,
    list_like real,
    toc_like real,
    reference_like real,
    bibliographic_entry_like real,
    caption_like real,
    marker_like real,
    parenthetical_citation_like real,
    journal_meta_like real,
    artifact_like real,
    noise_like real,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    map_label_like real
);


--
-- Name: du_block_spacing_rhythm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_spacing_rhythm (
    block_id uuid NOT NULL,
    line_gap_before real,
    line_gap_after real,
    paragraph_gap_before real,
    paragraph_gap_after real,
    indent_left real,
    indent_right real,
    alignment_left real,
    alignment_center real,
    alignment_right real,
    same_column_continuation_like real,
    new_region_break_like real,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: du_block_surface_features; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_surface_features (
    block_id uuid NOT NULL,
    char_count integer,
    word_count integer,
    sentence_count integer,
    line_count integer,
    mean_line_length real,
    line_width_ratio real,
    capitalization_ratio real,
    punctuation_density real,
    digit_density real,
    ends_with_period boolean,
    ends_with_colon boolean,
    starts_with_number boolean,
    starts_with_bullet boolean,
    contains_parentheses boolean,
    contains_brackets boolean,
    contains_url boolean,
    contains_email boolean,
    contains_doi boolean,
    contains_year boolean,
    is_all_caps boolean,
    is_short_line boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_block_topology; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_topology (
    block_id uuid NOT NULL,
    prev_block_index integer,
    next_block_index integer,
    cluster_id integer,
    early_block_rank integer,
    is_first_on_page boolean DEFAULT false NOT NULL,
    is_last_on_page boolean DEFAULT false NOT NULL,
    before_first_running_text boolean DEFAULT false NOT NULL,
    after_toc_candidate boolean DEFAULT false NOT NULL,
    repeated_header_footer_hint boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_block_topology_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_topology_signals (
    block_id uuid NOT NULL,
    same_page_prev boolean DEFAULT false NOT NULL,
    same_page_next boolean DEFAULT false NOT NULL,
    page_transition_before boolean DEFAULT false NOT NULL,
    page_transition_after boolean DEFAULT false NOT NULL,
    same_column_prev_like real,
    same_column_next_like real,
    column_index_candidate integer,
    odd_even_page text,
    early_on_page_score real,
    late_on_page_score real,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: du_block_typography; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_typography (
    block_id uuid NOT NULL,
    font_name text,
    font_family text,
    font_size real,
    font_ratio real,
    bold boolean,
    italic boolean,
    small_caps boolean,
    all_caps boolean,
    largest_on_page boolean,
    larger_than_prev boolean,
    larger_than_next boolean,
    font_name_change_prev boolean,
    font_name_change_next boolean,
    font_size_change_prev boolean,
    font_size_change_next boolean,
    is_document_font_mode boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    font_family_normalized text,
    dominant_font_share real,
    font_size_delta_prev real,
    font_size_delta_next real
);


--
-- Name: du_block_zone_memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_block_zone_memberships (
    block_id uuid NOT NULL,
    zone_type text NOT NULL,
    membership real NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_blocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_blocks (
    block_id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    page_index integer,
    block_index integer NOT NULL,
    start_char integer,
    end_char integer,
    text text NOT NULL,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    page_y0 real,
    page_y1 real,
    doc_y0 real,
    doc_y1 real,
    text_source text,
    geometry_source text,
    text_confidence real,
    geometry_confidence real,
    reading_order_confidence real,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_document_context; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_document_context (
    document_id uuid NOT NULL,
    source_kind text NOT NULL,
    text_source text NOT NULL,
    geometry_source text NOT NULL,
    reading_order_source text NOT NULL,
    has_native_text boolean DEFAULT false NOT NULL,
    has_reliable_geometry boolean DEFAULT false NOT NULL,
    has_reliable_reading_order boolean DEFAULT false NOT NULL,
    text_confidence real,
    geometry_confidence real,
    reading_order_confidence real,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_document_type_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_document_type_scores (
    document_id uuid NOT NULL,
    doc_type text NOT NULL,
    score double precision NOT NULL,
    weight double precision NOT NULL,
    rank integer NOT NULL,
    source text
);


--
-- Name: du_layout_clusters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_layout_clusters (
    cluster_id bigint NOT NULL,
    document_id uuid NOT NULL,
    page_index integer NOT NULL,
    cluster_kind text NOT NULL,
    start_block_index integer NOT NULL,
    end_block_index integer NOT NULL,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    block_count integer NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_layout_clusters_cluster_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.du_layout_clusters_cluster_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: du_layout_clusters_cluster_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.du_layout_clusters_cluster_id_seq OWNED BY public.du_layout_clusters.cluster_id;


--
-- Name: du_layout_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_layout_lines (
    layout_line_id uuid NOT NULL,
    document_id uuid NOT NULL,
    page_index integer NOT NULL,
    block_no integer NOT NULL,
    line_no integer NOT NULL,
    reading_order integer NOT NULL,
    text text NOT NULL,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    page_width real,
    page_height real,
    font_name text,
    font_size real,
    font_flags integer,
    is_bold boolean DEFAULT false NOT NULL,
    is_italic boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: du_layout_spans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_layout_spans (
    layout_span_id uuid NOT NULL,
    document_id uuid NOT NULL,
    page_index integer NOT NULL,
    block_no integer NOT NULL,
    line_no integer NOT NULL,
    span_no integer NOT NULL,
    reading_order integer NOT NULL,
    text text NOT NULL,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    page_width real,
    page_height real,
    font_name text,
    font_size real,
    font_flags integer,
    is_bold boolean DEFAULT false NOT NULL,
    is_italic boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: du_pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_pages (
    page_id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    page_index integer NOT NULL,
    width real,
    height real,
    image_based boolean,
    native_text_present boolean,
    page_confidence real,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_section_tree; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_section_tree (
    document_id uuid NOT NULL,
    section_node_id integer NOT NULL,
    parent_section_node_id integer,
    heading_block_id uuid,
    start_block_index integer NOT NULL,
    end_block_index integer NOT NULL,
    page_start integer,
    page_end integer,
    level integer NOT NULL,
    role text DEFAULT 'heading'::text NOT NULL,
    section_number text,
    title text NOT NULL,
    title_normalized text,
    is_numbered boolean DEFAULT false NOT NULL,
    confidence real,
    source text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT du_section_tree_block_range_chk CHECK ((start_block_index <= end_block_index)),
    CONSTRAINT du_section_tree_level_chk CHECK ((level >= 1)),
    CONSTRAINT du_section_tree_page_range_chk CHECK (((page_start IS NULL) OR (page_end IS NULL) OR (page_start <= page_end)))
);


--
-- Name: du_semantic_zones; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_semantic_zones (
    semantic_zone_id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    zone_type text NOT NULL,
    start_block_index integer NOT NULL,
    end_block_index integer NOT NULL,
    page_start integer,
    page_end integer,
    confidence real,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: du_zone_hypotheses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.du_zone_hypotheses (
    zone_hypothesis_id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    zone_type text NOT NULL,
    start_block_index integer NOT NULL,
    end_block_index integer NOT NULL,
    page_start integer,
    page_end integer,
    score real NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: extracted_texts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extracted_texts (
    extraction_id uuid NOT NULL,
    document_id uuid NOT NULL,
    extractor text NOT NULL,
    text_full text,
    text_length integer,
    nul_bytes_removed integer DEFAULT 0 NOT NULL,
    extract_status text DEFAULT 'ok'::text NOT NULL,
    extract_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pdf_metadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pdf_metadata (
    metadata_id uuid NOT NULL,
    document_id uuid NOT NULL,
    title text,
    author text,
    subject text,
    keywords text,
    creator text,
    producer text,
    creation_date text,
    mod_date text,
    raw_json jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    migration_name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: text_segments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.text_segments (
    segment_id uuid NOT NULL,
    document_id uuid NOT NULL,
    segment_index integer NOT NULL,
    segment_type text NOT NULL,
    text text NOT NULL,
    char_length integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    page_index integer,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    page_width real,
    page_height real
);


--
-- Name: document_regions region_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_regions ALTER COLUMN region_id SET DEFAULT nextval('public.document_regions_region_id_seq'::regclass);


--
-- Name: du_layout_clusters cluster_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_clusters ALTER COLUMN cluster_id SET DEFAULT nextval('public.du_layout_clusters_cluster_id_seq'::regclass);


--
-- Name: authors authors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authors
    ADD CONSTRAINT authors_pkey PRIMARY KEY (author_id);


--
-- Name: document_authors document_authors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_authors
    ADD CONSTRAINT document_authors_pkey PRIMARY KEY (document_author_id);


--
-- Name: document_identifiers document_identifiers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_identifiers
    ADD CONSTRAINT document_identifiers_pkey PRIMARY KEY (identifier_id);


--
-- Name: document_regions document_regions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_regions
    ADD CONSTRAINT document_regions_pkey PRIMARY KEY (region_id);


--
-- Name: documents documents_file_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_file_hash_key UNIQUE (file_hash);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (document_id);


--
-- Name: du_block_columns du_block_columns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_columns
    ADD CONSTRAINT du_block_columns_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_context du_block_context_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_context
    ADD CONSTRAINT du_block_context_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_geometry du_block_geometry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_geometry
    ADD CONSTRAINT du_block_geometry_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_layout_features du_block_layout_features_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_layout_features
    ADD CONSTRAINT du_block_layout_features_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_page_furniture_signals du_block_page_furniture_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_page_furniture_signals
    ADD CONSTRAINT du_block_page_furniture_signals_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_phase du_block_phase_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_phase
    ADD CONSTRAINT du_block_phase_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_roles du_block_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_roles
    ADD CONSTRAINT du_block_roles_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_semantic_micro du_block_semantic_micro_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_semantic_micro
    ADD CONSTRAINT du_block_semantic_micro_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_signals du_block_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_signals
    ADD CONSTRAINT du_block_signals_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_spacing_rhythm du_block_spacing_rhythm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_spacing_rhythm
    ADD CONSTRAINT du_block_spacing_rhythm_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_surface_features du_block_surface_features_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_surface_features
    ADD CONSTRAINT du_block_surface_features_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_topology du_block_topology_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_topology
    ADD CONSTRAINT du_block_topology_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_topology_signals du_block_topology_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_topology_signals
    ADD CONSTRAINT du_block_topology_signals_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_typography du_block_typography_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_typography
    ADD CONSTRAINT du_block_typography_pkey PRIMARY KEY (block_id);


--
-- Name: du_block_zone_memberships du_block_zone_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_zone_memberships
    ADD CONSTRAINT du_block_zone_memberships_pkey PRIMARY KEY (block_id, zone_type, source);


--
-- Name: du_blocks du_blocks_document_id_block_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_blocks
    ADD CONSTRAINT du_blocks_document_id_block_index_key UNIQUE (document_id, block_index);


--
-- Name: du_blocks du_blocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_blocks
    ADD CONSTRAINT du_blocks_pkey PRIMARY KEY (block_id);


--
-- Name: du_document_context du_document_context_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_document_context
    ADD CONSTRAINT du_document_context_pkey PRIMARY KEY (document_id);


--
-- Name: du_document_type_scores du_document_type_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_document_type_scores
    ADD CONSTRAINT du_document_type_scores_pkey PRIMARY KEY (document_id, doc_type);


--
-- Name: du_layout_clusters du_layout_clusters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_clusters
    ADD CONSTRAINT du_layout_clusters_pkey PRIMARY KEY (cluster_id);


--
-- Name: du_layout_lines du_layout_lines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_lines
    ADD CONSTRAINT du_layout_lines_pkey PRIMARY KEY (layout_line_id);


--
-- Name: du_layout_spans du_layout_spans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_spans
    ADD CONSTRAINT du_layout_spans_pkey PRIMARY KEY (layout_span_id);


--
-- Name: du_pages du_pages_document_id_page_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_pages
    ADD CONSTRAINT du_pages_document_id_page_index_key UNIQUE (document_id, page_index);


--
-- Name: du_pages du_pages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_pages
    ADD CONSTRAINT du_pages_pkey PRIMARY KEY (page_id);


--
-- Name: du_section_tree du_section_tree_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_section_tree
    ADD CONSTRAINT du_section_tree_pkey PRIMARY KEY (document_id, section_node_id);


--
-- Name: du_semantic_zones du_semantic_zones_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_semantic_zones
    ADD CONSTRAINT du_semantic_zones_pkey PRIMARY KEY (semantic_zone_id);


--
-- Name: du_zone_hypotheses du_zone_hypotheses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_zone_hypotheses
    ADD CONSTRAINT du_zone_hypotheses_pkey PRIMARY KEY (zone_hypothesis_id);


--
-- Name: extracted_texts extracted_texts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_texts
    ADD CONSTRAINT extracted_texts_pkey PRIMARY KEY (extraction_id);


--
-- Name: pdf_metadata pdf_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pdf_metadata
    ADD CONSTRAINT pdf_metadata_pkey PRIMARY KEY (metadata_id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (migration_name);


--
-- Name: text_segments text_segments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.text_segments
    ADD CONSTRAINT text_segments_pkey PRIMARY KEY (segment_id);


--
-- Name: idx_authors_normalized_name_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_authors_normalized_name_unique ON public.authors USING btree (normalized_name);


--
-- Name: idx_document_authors_author_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_authors_author_id ON public.document_authors USING btree (author_id);


--
-- Name: idx_document_authors_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_authors_document_id ON public.document_authors USING btree (document_id);


--
-- Name: idx_document_authors_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_document_authors_unique ON public.document_authors USING btree (document_id, author_id);


--
-- Name: idx_document_identifiers_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_identifiers_document_id ON public.document_identifiers USING btree (document_id);


--
-- Name: idx_document_identifiers_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_identifiers_type ON public.document_identifiers USING btree (identifier_type);


--
-- Name: idx_document_identifiers_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_document_identifiers_unique ON public.document_identifiers USING btree (document_id, identifier_type, identifier_value);


--
-- Name: idx_document_regions_doc_region_index; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_document_regions_doc_region_index ON public.document_regions USING btree (document_id, region_index);


--
-- Name: idx_document_regions_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_regions_document_id ON public.document_regions USING btree (document_id);


--
-- Name: idx_document_regions_region_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_regions_region_type ON public.document_regions USING btree (region_type);


--
-- Name: idx_documents_file_hash_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_documents_file_hash_unique ON public.documents USING btree (file_hash);


--
-- Name: idx_du_block_page_furniture_signals_flags; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_block_page_furniture_signals_flags ON public.du_block_page_furniture_signals USING btree (is_top_band, is_bottom_band, running_header_like, running_footer_like);


--
-- Name: idx_du_block_spacing_rhythm_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_block_spacing_rhythm_updated_at ON public.du_block_spacing_rhythm USING btree (updated_at);


--
-- Name: idx_du_block_topology_signals_odd_even; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_block_topology_signals_odd_even ON public.du_block_topology_signals USING btree (odd_even_page);


--
-- Name: idx_du_layout_caps; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_caps ON public.du_block_layout_features USING btree (is_all_caps);


--
-- Name: idx_du_layout_clusters_doc_page; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_clusters_doc_page ON public.du_layout_clusters USING btree (document_id, page_index);


--
-- Name: idx_du_layout_lines_doc_page_block_line; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_lines_doc_page_block_line ON public.du_layout_lines USING btree (document_id, page_index, block_no, line_no);


--
-- Name: idx_du_layout_lines_doc_page_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_lines_doc_page_order ON public.du_layout_lines USING btree (document_id, page_index, reading_order);


--
-- Name: idx_du_layout_numbered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_numbered ON public.du_block_layout_features USING btree (starts_with_number);


--
-- Name: idx_du_layout_short; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_short ON public.du_block_layout_features USING btree (is_short_line);


--
-- Name: idx_du_layout_spans_doc_page_block_line; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_spans_doc_page_block_line ON public.du_layout_spans USING btree (document_id, page_index, block_no, line_no, span_no);


--
-- Name: idx_du_layout_spans_doc_page_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_spans_doc_page_order ON public.du_layout_spans USING btree (document_id, page_index, reading_order);


--
-- Name: idx_du_layout_word_count; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_layout_word_count ON public.du_block_layout_features USING btree (word_count);


--
-- Name: idx_du_section_tree_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_section_tree_doc ON public.du_section_tree USING btree (document_id);


--
-- Name: idx_du_section_tree_doc_end; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_section_tree_doc_end ON public.du_section_tree USING btree (document_id, end_block_index);


--
-- Name: idx_du_section_tree_doc_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_section_tree_doc_level ON public.du_section_tree USING btree (document_id, level);


--
-- Name: idx_du_section_tree_doc_pages; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_section_tree_doc_pages ON public.du_section_tree USING btree (document_id, page_start, page_end);


--
-- Name: idx_du_section_tree_doc_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_section_tree_doc_parent ON public.du_section_tree USING btree (document_id, parent_section_node_id);


--
-- Name: idx_du_section_tree_doc_start; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_du_section_tree_doc_start ON public.du_section_tree USING btree (document_id, start_block_index);


--
-- Name: idx_text_segments_doc_type_page; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_text_segments_doc_type_page ON public.text_segments USING btree (document_id, segment_type, page_index, segment_index);


--
-- Name: idx_text_segments_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_text_segments_document_id ON public.text_segments USING btree (document_id);


--
-- Name: idx_text_segments_document_page; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_text_segments_document_page ON public.text_segments USING btree (document_id, page_index, segment_index);


--
-- Name: idx_text_segments_segment_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_text_segments_segment_type ON public.text_segments USING btree (segment_type);


--
-- Name: uq_du_section_tree_doc_heading_block; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_du_section_tree_doc_heading_block ON public.du_section_tree USING btree (document_id, heading_block_id) WHERE (heading_block_id IS NOT NULL);


--
-- Name: document_authors document_authors_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_authors
    ADD CONSTRAINT document_authors_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.authors(author_id) ON DELETE CASCADE;


--
-- Name: document_authors document_authors_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_authors
    ADD CONSTRAINT document_authors_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: document_identifiers document_identifiers_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_identifiers
    ADD CONSTRAINT document_identifiers_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: document_regions document_regions_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_regions
    ADD CONSTRAINT document_regions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_block_context du_block_context_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_context
    ADD CONSTRAINT du_block_context_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_geometry du_block_geometry_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_geometry
    ADD CONSTRAINT du_block_geometry_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_layout_features du_block_layout_features_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_layout_features
    ADD CONSTRAINT du_block_layout_features_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id);


--
-- Name: du_block_page_furniture_signals du_block_page_furniture_signals_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_page_furniture_signals
    ADD CONSTRAINT du_block_page_furniture_signals_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_phase du_block_phase_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_phase
    ADD CONSTRAINT du_block_phase_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_roles du_block_roles_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_roles
    ADD CONSTRAINT du_block_roles_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_semantic_micro du_block_semantic_micro_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_semantic_micro
    ADD CONSTRAINT du_block_semantic_micro_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_signals du_block_signals_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_signals
    ADD CONSTRAINT du_block_signals_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_spacing_rhythm du_block_spacing_rhythm_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_spacing_rhythm
    ADD CONSTRAINT du_block_spacing_rhythm_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_surface_features du_block_surface_features_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_surface_features
    ADD CONSTRAINT du_block_surface_features_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_topology du_block_topology_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_topology
    ADD CONSTRAINT du_block_topology_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_topology_signals du_block_topology_signals_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_topology_signals
    ADD CONSTRAINT du_block_topology_signals_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_typography du_block_typography_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_typography
    ADD CONSTRAINT du_block_typography_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_block_zone_memberships du_block_zone_memberships_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_block_zone_memberships
    ADD CONSTRAINT du_block_zone_memberships_block_id_fkey FOREIGN KEY (block_id) REFERENCES public.du_blocks(block_id) ON DELETE CASCADE;


--
-- Name: du_blocks du_blocks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_blocks
    ADD CONSTRAINT du_blocks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_document_context du_document_context_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_document_context
    ADD CONSTRAINT du_document_context_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_layout_clusters du_layout_clusters_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_clusters
    ADD CONSTRAINT du_layout_clusters_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_layout_lines du_layout_lines_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_lines
    ADD CONSTRAINT du_layout_lines_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_layout_spans du_layout_spans_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_layout_spans
    ADD CONSTRAINT du_layout_spans_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_pages du_pages_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_pages
    ADD CONSTRAINT du_pages_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_section_tree du_section_tree_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_section_tree
    ADD CONSTRAINT du_section_tree_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_section_tree du_section_tree_heading_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_section_tree
    ADD CONSTRAINT du_section_tree_heading_block_id_fkey FOREIGN KEY (heading_block_id) REFERENCES public.du_blocks(block_id) ON DELETE SET NULL;


--
-- Name: du_section_tree du_section_tree_parent_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_section_tree
    ADD CONSTRAINT du_section_tree_parent_fk FOREIGN KEY (document_id, parent_section_node_id) REFERENCES public.du_section_tree(document_id, section_node_id) ON DELETE CASCADE;


--
-- Name: du_semantic_zones du_semantic_zones_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_semantic_zones
    ADD CONSTRAINT du_semantic_zones_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: du_zone_hypotheses du_zone_hypotheses_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.du_zone_hypotheses
    ADD CONSTRAINT du_zone_hypotheses_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: extracted_texts extracted_texts_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extracted_texts
    ADD CONSTRAINT extracted_texts_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: pdf_metadata pdf_metadata_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pdf_metadata
    ADD CONSTRAINT pdf_metadata_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- Name: text_segments text_segments_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.text_segments
    ADD CONSTRAINT text_segments_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(document_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict ufpfFcejJh4pNwS87Gj5b9Ch4vS8SQeV66UXdDGyzKeSEd2wsmzBppo5cBRLp8t

