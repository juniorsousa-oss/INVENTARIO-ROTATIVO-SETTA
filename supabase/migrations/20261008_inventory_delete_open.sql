-- Inventário Rotativo | exclusão segura de inventários em andamento
-- A exclusão remove o documento e suas contagens; preserva somente trilha mínima da exclusão.

create table if not exists public.inventario_deleted_documents (
  documento text primary key,
  deleted_at timestamptz not null default now(),
  deleted_by text not null
);
alter table public.inventario_deleted_documents enable row level security;
revoke all on public.inventario_deleted_documents from public, anon, authenticated;
grant select, insert on public.inventario_deleted_documents to service_role;

create or replace function public.inventario_delete_open_document(p_documento text, p_deleted_by text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_document jsonb;
  v_count integer;
begin
  if coalesce(btrim(p_documento),'')='' then
    raise exception 'DOCUMENTO_OBRIGATORIO';
  end if;
  if coalesce(btrim(p_deleted_by),'')='' then
    raise exception 'USUARIO_OBRIGATORIO';
  end if;
  perform pg_advisory_xact_lock(hashtext('inventario_rotativo:close'));
  select payload->p_documento into v_document
    from public.inventario_operacional_state
    where app_key='inventario_rotativo' and state_key='inventories'
    for update;
  if v_document is null then
    raise exception 'INVENTARIO_NAO_ENCONTRADO';
  end if;
  if coalesce(v_document->>'status','')='FECHADO' then
    raise exception 'INVENTARIO_FECHADO_NAO_PODE_EXCLUIR';
  end if;
  v_count:=case when jsonb_typeof(v_document->'rows')='array'
      then jsonb_array_length(v_document->'rows') else 0 end;
  insert into public.inventario_deleted_documents(documento,deleted_by)
    values (p_documento,p_deleted_by);
  update public.inventario_operacional_state
    set payload=payload-p_documento,updated_at=now()
    where app_key='inventario_rotativo' and state_key='inventories';
  return jsonb_build_object('ok',true,'documento',p_documento,'positions_discarded',v_count);
end;
$$;
revoke all on function public.inventario_delete_open_document(text,text) from public, anon, authenticated;
grant execute on function public.inventario_delete_open_document(text,text) to service_role;

-- Impede que uma sessão antiga recrie um inventário já descartado.
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

  -- Serialize mudanças do mesmo inventário com exclusões/encerramentos.
  perform pg_advisory_xact_lock(hashtext('inventario_rotativo:close'));
  if exists(select 1 from public.inventario_deleted_documents where documento=p_documento) then
    raise exception 'INVENTARIO_EXCLUIDO';
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

-- Também bloqueia eventual encerramento disparado por uma sessão desatualizada.
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
  if exists(select 1 from public.inventario_deleted_documents where documento=p_documento) then
    raise exception 'INVENTARIO_EXCLUIDO';
  end if;

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

revoke all on function public.inventario_close_atomic(text,jsonb,text[],jsonb) from public, anon, authenticated;
grant execute on function public.inventario_close_atomic(text,jsonb,text[],jsonb) to service_role;
