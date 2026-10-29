-- Clean PostgreSQL 18 business baseline; contains no application data.
-- Run atomically with scripts/init_db.py on an empty database.
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE TABLE public.claims (
    id text NOT NULL,
    video_id text NOT NULL,
    extraction_run_id text,
    object_name text NOT NULL,
    stance text NOT NULL,
    author_stance text,
    content_type text,
    source_quotes jsonb,
    process_stage text NOT NULL,
    original_conclusion text NOT NULL,
    conditions text NOT NULL,
    price_info text NOT NULL,
    source_video_url text NOT NULL,
    created_at bigint NOT NULL,
    space_tags jsonb,
    topic_tags jsonb,
    original_reasons jsonb,
    alternatives jsonb,
    deleted_at integer,
    deleted_by text,
    delete_reason text,
    CONSTRAINT claims_process_stage_valid CHECK ((process_stage = ANY (ARRAY['准备阶段'::text, '收房验房'::text, '设计规划'::text, '拆改阶段'::text, '水电阶段'::text, '防水阶段'::text, '瓦工阶段'::text, '木工阶段'::text, '油工阶段'::text, '主材安装'::text, '定制柜安装'::text, '厨卫安装'::text, '灯具开关五金'::text, '家电家具软装'::text, '开荒保洁'::text, '通风除醛'::text, '入住验收'::text, '待人工分类'::text]))),
    CONSTRAINT claims_stance_valid CHECK ((stance = ANY (ARRAY['明确推荐'::text, '明确不推荐'::text, '有条件'::text, '价格建议'::text, '未明确'::text])))
);
CREATE TABLE public.extraction_runs (
    id text NOT NULL,
    video_id text NOT NULL,
    model text NOT NULL,
    prompt_version text NOT NULL,
    input_hash text NOT NULL,
    prompt_text text NOT NULL,
    status text NOT NULL,
    error_message text,
    created_at bigint NOT NULL,
    raw_response_json jsonb
);
CREATE TABLE public.sources (
    id text NOT NULL,
    platform text NOT NULL,
    name text NOT NULL,
    profile_url text,
    priority text DEFAULT 'P1'::text,
    status text DEFAULT 'active'::text,
    notes text DEFAULT ''::text,
    created_at bigint NOT NULL,
    CONSTRAINT sources_status_valid CHECK (((status IS NULL) OR (status = ANY (ARRAY['active'::text, 'inactive'::text]))))
);
CREATE TABLE public.videos (
    id text NOT NULL,
    source_id text,
    platform text NOT NULL,
    creator text NOT NULL,
    title text NOT NULL,
    source_url text NOT NULL,
    share_url text,
    share_text text,
    published_at text,
    transcript_text text,
    transcript_source text,
    transcript_job jsonb,
    ad_review jsonb,
    ad_review_override jsonb,
    transcript_created_at bigint,
    retry_count integer DEFAULT 0,
    last_retry_at bigint,
    last_error text,
    status text DEFAULT 'created'::text,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    published_at_ts timestamp with time zone,
    has_transcript boolean DEFAULT false,
    transcript_length integer DEFAULT 0,
    deleted_at integer,
    deleted_by text,
    delete_reason text,
    CONSTRAINT videos_status_valid CHECK (((status IS NULL) OR (status = ANY (ARRAY['created'::text, 'transcript_pending'::text, 'transcript_saved'::text, 'claims_extracted'::text, 'claims_filtered'::text, 'transcript_failed'::text]))))
);
ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.extraction_runs
    ADD CONSTRAINT extraction_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.videos
    ADD CONSTRAINT videos_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.videos
    ADD CONSTRAINT videos_source_url_key UNIQUE (source_url);
CREATE INDEX idx_claims_active_search_trgm ON public.claims USING gin ((((((((COALESCE(object_name, ''::text) || ' '::text) || COALESCE(original_conclusion, ''::text)) || ' '::text) || COALESCE(conditions, ''::text)) || ' '::text) || COALESCE((original_reasons)::text, ''::text))) public.gin_trgm_ops) WHERE (deleted_at IS NULL);
CREATE INDEX idx_claims_active_stage_order ON public.claims USING btree (deleted_at, process_stage, created_at DESC, id DESC);
CREATE INDEX idx_claims_active_stage_order_partial ON public.claims USING btree (process_stage, created_at DESC, id DESC) WHERE (deleted_at IS NULL);
CREATE INDEX idx_claims_active_video_id ON public.claims USING btree (deleted_at, video_id);
CREATE INDEX idx_claims_active_video_id_partial ON public.claims USING btree (video_id) WHERE (deleted_at IS NULL);
CREATE INDEX idx_claims_page_order ON public.claims USING btree (created_at DESC, id DESC);
CREATE INDEX idx_claims_process_stage ON public.claims USING btree (process_stage);
CREATE INDEX idx_claims_search_trgm ON public.claims USING gin ((((((((COALESCE(object_name, ''::text) || ' '::text) || COALESCE(original_conclusion, ''::text)) || ' '::text) || COALESCE(conditions, ''::text)) || ' '::text) || COALESCE((original_reasons)::text, ''::text))) public.gin_trgm_ops);
CREATE INDEX idx_claims_space_tags_gin ON public.claims USING gin (space_tags);
CREATE INDEX idx_claims_topic_tags_gin ON public.claims USING gin (topic_tags);
CREATE INDEX idx_claims_video_id ON public.claims USING btree (video_id);
CREATE INDEX idx_extraction_runs_video_id ON public.extraction_runs USING btree (video_id);
CREATE INDEX idx_videos_active_page_order ON public.videos USING btree (deleted_at, published_at_ts DESC, created_at DESC, id DESC);
CREATE INDEX idx_videos_active_page_order_partial ON public.videos USING btree (published_at_ts DESC, created_at DESC, id DESC) WHERE (deleted_at IS NULL);
CREATE INDEX idx_videos_active_progress_order ON public.videos USING btree (deleted_at, status, has_transcript, published_at_ts DESC, created_at DESC, id DESC);
CREATE INDEX idx_videos_active_progress_order_partial ON public.videos USING btree (status, has_transcript, published_at_ts DESC, created_at DESC, id DESC) WHERE (deleted_at IS NULL);
CREATE INDEX idx_videos_active_search_trgm ON public.videos USING gin ((((((COALESCE(title, ''::text) || ' '::text) || COALESCE(creator, ''::text)) || ' '::text) || COALESCE(platform, ''::text))) public.gin_trgm_ops) WHERE (deleted_at IS NULL);
CREATE INDEX idx_videos_page_order ON public.videos USING btree (published_at_ts DESC, created_at DESC, id DESC);
CREATE INDEX idx_videos_progress_order ON public.videos USING btree (status, has_transcript, published_at_ts DESC, created_at DESC, id DESC);
CREATE INDEX idx_videos_published_at ON public.videos USING btree (published_at);
CREATE INDEX idx_videos_published_at_ts ON public.videos USING btree (published_at_ts DESC);
CREATE INDEX idx_videos_search_trgm ON public.videos USING gin ((((((COALESCE(title, ''::text) || ' '::text) || COALESCE(creator, ''::text)) || ' '::text) || COALESCE(platform, ''::text))) public.gin_trgm_ops);
CREATE INDEX idx_videos_source_id ON public.videos USING btree (source_id);
CREATE INDEX idx_videos_status ON public.videos USING btree (status);
ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_extraction_run_id_fkey FOREIGN KEY (extraction_run_id) REFERENCES public.extraction_runs(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_video_id_fkey FOREIGN KEY (video_id) REFERENCES public.videos(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.extraction_runs
    ADD CONSTRAINT extraction_runs_video_id_fkey FOREIGN KEY (video_id) REFERENCES public.videos(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.videos
    ADD CONSTRAINT videos_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);
