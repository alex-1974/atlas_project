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
