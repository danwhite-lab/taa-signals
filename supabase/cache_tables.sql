-- REVIEW AND RUN MANUALLY in the project's SQL editor. Never run automatically.
-- Only new server caches; existing portfolios/user_settings/RPC stay unchanged.
begin;
create table public.price_cache (
  symbol text not null,
  source text not null,
  as_of timestamptz not null,
  rows jsonb not null check (jsonb_typeof(rows) = 'array'),
  updated_at timestamptz not null default now(),
  primary key (symbol, source)
);
create table public.results_cache (
  cache_key text primary key,
  result jsonb not null,
  created_at timestamptz not null default now()
);
alter table public.price_cache enable row level security;
alter table public.results_cache enable row level security;
-- No browser policies: caches are server-only even if default grants differ.
revoke all on public.price_cache, public.results_cache from public, anon, authenticated;
grant select, insert, update, delete on public.price_cache, public.results_cache to service_role;
commit;
