-- Atomic, user-scoped portfolio saves. Applied as save_private_portfolio.
create or replace function public.save_private_portfolio(
  p_payload jsonb,
  p_id uuid default null,
  p_expected_updated_at timestamptz default null,
  p_make_default boolean default false
) returns jsonb language plpgsql security invoker set search_path = ''
as $$
declare
  v_user uuid := auth.uid();
  v_row public.portfolios;
  v_name text := btrim(p_payload->>'name');
begin
  if v_user is null then raise exception 'Sign in before saving a portfolio'; end if;
  if v_name is null or char_length(v_name) not between 1 and 80 then
    raise exception 'Enter a portfolio name between 1 and 80 characters';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_user::text, 0));
  if p_id is not null then
    select * into v_row from public.portfolios where id = p_id and user_id = v_user for update;
    if not found then raise exception 'Portfolio not found in this account'; end if;
    if p_expected_updated_at is not null and v_row.updated_at <> p_expected_updated_at then
      raise exception 'Portfolio changed on another device. Load it again before saving';
    end if;
    update public.portfolios set name = v_name,
      payload = jsonb_set(p_payload, '{name}', to_jsonb(v_name)),
      updated_at = clock_timestamp()
      where id = p_id and user_id = v_user returning * into v_row;
  else
    insert into public.portfolios(user_id,name,payload)
      values(v_user,v_name,jsonb_set(p_payload, '{name}',to_jsonb(v_name)))
      returning * into v_row;
  end if;
  if p_make_default then
    update public.portfolios set is_default = false where user_id = v_user and id <> v_row.id and is_default;
    update public.portfolios set is_default = true where id = v_row.id and user_id = v_user returning * into v_row;
  end if;
  return to_jsonb(v_row);
end;
$$;
revoke all on function public.save_private_portfolio(jsonb,uuid,timestamptz,boolean) from public, anon;
grant execute on function public.save_private_portfolio(jsonb,uuid,timestamptz,boolean) to authenticated;
