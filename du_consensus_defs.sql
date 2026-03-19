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
CREATE TABLE public.du_block_phase (
    block_id uuid NOT NULL,
    phase text NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);
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
CREATE TABLE public.du_block_zone_memberships (
    block_id uuid NOT NULL,
    zone_type text NOT NULL,
    membership real NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);
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
CREATE TABLE public.du_document_type_scores (
    document_id uuid NOT NULL,
    doc_type text NOT NULL,
    score double precision NOT NULL,
    weight double precision NOT NULL,
    rank integer NOT NULL,
    source text
);
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
