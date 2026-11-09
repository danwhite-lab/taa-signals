-- Apply after the existing user_settings and portfolio setup.
create table if not exists public.my_funds (
  user_id uuid not null references auth.users(id) on delete cascade,
  id uuid not null,
  listing_key text not null,
  verified jsonb not null,
  signature text not null,
  archived boolean not null default false,
  primary key (user_id, id),
  unique (user_id, listing_key)
);
alter table public.my_funds enable row level security;
revoke all on table public.my_funds from anon, authenticated;
grant select, insert on table public.my_funds to authenticated;
grant update (archived) on table public.my_funds to authenticated;
drop policy if exists "Read own funds" on public.my_funds;
create policy "Read own funds" on public.my_funds for select to authenticated using ((select auth.uid()) = user_id);
drop policy if exists "Insert own funds" on public.my_funds;
create policy "Insert own funds" on public.my_funds for insert to authenticated with check ((select auth.uid()) = user_id);
drop policy if exists "Archive own funds" on public.my_funds;
create policy "Archive own funds" on public.my_funds for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
