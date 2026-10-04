-- Inventário Rotativo | persistência atômica e numeração segura
-- Aplicado em produção em 2026-10-04.

create table if not exists public.inventario_document_counter (
  date_key date primary key,
  last_number integer not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.inventario_document_counter enable row level security;
revoke all on table public.inventario_document_counter from public, anon, authenticated;
grant select, insert, update on table public.inventario_document_counter to service_role;

create or replace function public.inventario_next_document()
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_date date := timezone('America/Sao_Paulo', now())::date;
  v_prefix text := to_char(timezone('America/Sao_Paulo', now()), 'DDMMYYYY');
  v_existing integer := 0;
  v_number integer;
begin
  select coalesce(max(((regexp_match(k, '-([0-9]+)$'))[1])::integer), 0)
    into v_existing
  from public.inventario_operacional_state s,
       lateral jsonb_object_keys(
         case when jsonb_typeof(s.payload)='object' then s.payload else '{}'::jsonb end
       ) as k
  where s.app_key='inventario_rotativo'
    and s.state_key='inventories'
    and k like v_prefix || '-%';

  insert into public.inventario_document_counter(date_key,last_number,updated_at)
  values (v_date,v_existing+1,now())
  on conflict (date_key) do update
    set last_number=greatest(public.inventario_document_counter.last_number,v_existing)+1,
        updated_at=now()
  returning last_number into v_number;

  return v_prefix || '-' || lpad(v_number::text,3,'0');
end;
$$;

revoke all on function public.inventario_next_document() from public, anon, authenticated;
grant execute on function public.inventario_next_document() to service_role;

create or replace function public.inventario_upsert_document(
  p_documento text,
  p_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated timestamptz;
begin
  if coalesce(trim(p_documento),'')='' then
    raise exception 'DOCUMENTO_OBRIGATORIO';
  end if;

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values (
    'inventario_rotativo',
    'inventories',
    jsonb_build_object(p_documento,coalesce(p_payload,'{}'::jsonb)),
    now()
  )
  on conflict (app_key,state_key) do update
  set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)
              || jsonb_build_object(p_documento,coalesce(p_payload,'{}'::jsonb)),
      updated_at=now()
  returning updated_at into v_updated;

  return jsonb_build_object('ok',true,'updated_at',v_updated,'documento',p_documento);
end;
$$;

revoke all on function public.inventario_upsert_document(text,jsonb) from public, anon, authenticated;
grant execute on function public.inventario_upsert_document(text,jsonb) to service_role;

create or replace function public.inventario_upsert_report(
  p_report_id text,
  p_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated timestamptz;
begin
  if coalesce(trim(p_report_id),'')='' then
    raise exception 'REPORT_ID_OBRIGATORIO';
  end if;

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values (
    'inventario_rotativo',
    'reports',
    jsonb_build_object(p_report_id,coalesce(p_payload,'{}'::jsonb)),
    now()
  )
  on conflict (app_key,state_key) do update
  set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)
              || jsonb_build_object(p_report_id,coalesce(p_payload,'{}'::jsonb)),
      updated_at=now()
  returning updated_at into v_updated;

  return jsonb_build_object('ok',true,'updated_at',v_updated,'report_id',p_report_id);
end;
$$;

revoke all on function public.inventario_upsert_report(text,jsonb) from public, anon, authenticated;
grant execute on function public.inventario_upsert_report(text,jsonb) to service_role;

create or replace function public.inventario_merge_cycles(p_values jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated timestamptz;
begin
  if p_values is null or jsonb_typeof(p_values)<>'object' then
    raise exception 'CYCLES_OBJECT_REQUIRED';
  end if;

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values ('inventario_rotativo','cycles',p_values,now())
  on conflict (app_key,state_key) do update
  set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)||p_values,
      updated_at=now()
  returning updated_at into v_updated;

  return jsonb_build_object('ok',true,'updated_at',v_updated);
end;
$$;

revoke all on function public.inventario_merge_cycles(jsonb) from public, anon, authenticated;
grant execute on function public.inventario_merge_cycles(jsonb) to service_role;

create or replace function public.inventario_close_atomic(
  p_documento text,
  p_document jsonb,
  p_cycle_codes text[],
  p_reports jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_code text;
  v_cycles jsonb;
  v_reports jsonb := coalesce(p_reports,'{}'::jsonb);
  v_count integer;
begin
  if coalesce(trim(p_documento),'')='' then
    raise exception 'DOCUMENTO_OBRIGATORIO';
  end if;

  perform pg_advisory_xact_lock(hashtext('inventario_rotativo:close'));

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values (
    'inventario_rotativo',
    'inventories',
    jsonb_build_object(p_documento,coalesce(p_document,'{}'::jsonb)),
    now()
  )
  on conflict (app_key,state_key) do update
  set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)
              || jsonb_build_object(p_documento,coalesce(p_document,'{}'::jsonb)),
      updated_at=now();

  select coalesce(payload,'{}'::jsonb)
    into v_cycles
  from public.inventario_operacional_state
  where app_key='inventario_rotativo' and state_key='cycles'
  for update;

  if v_cycles is null then v_cycles:='{}'::jsonb; end if;

  foreach v_code in array coalesce(p_cycle_codes,array[]::text[]) loop
    v_count:=coalesce((v_cycles->>v_code)::integer,0)+1;
    v_cycles:=jsonb_set(v_cycles,array[v_code],to_jsonb(v_count),true);
  end loop;

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values ('inventario_rotativo','cycles',v_cycles,now())
  on conflict (app_key,state_key) do update
  set payload=excluded.payload,updated_at=excluded.updated_at;

  if jsonb_typeof(v_reports)='object' and v_reports<>'{}'::jsonb then
    insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
    values ('inventario_rotativo','reports',v_reports,now())
    on conflict (app_key,state_key) do update
    set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)||v_reports,
        updated_at=now();
  end if;

  return jsonb_build_object(
    'ok',true,
    'documento',p_documento,
    'cycle_codes',coalesce(array_length(p_cycle_codes,1),0)
  );
end;
$$;

revoke all on function public.inventario_close_atomic(text,jsonb,text[],jsonb)
  from public, anon, authenticated;
grant execute on function public.inventario_close_atomic(text,jsonb,text[],jsonb)
  to service_role;
