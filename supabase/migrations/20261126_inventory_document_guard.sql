-- Compare a fotografia lida pelo operador com a versão atual do documento.
-- As assinaturas das RPCs não mudam; a Edge Function encaminha o JSON como está.
-- Sessões antigas sem o envelope são bloqueadas, nunca sobrescrevem um lote.
create or replace function public.inventario_guard_document(
  p_documento text, p_current jsonb, p_payload jsonb
) returns jsonb
language plpgsql set search_path = pg_catalog as $$
declare
  v_candidate jsonb;
  v_expected jsonb;
begin
  if jsonb_typeof(p_payload) is distinct from 'object'
      or not (p_payload ? '_setta_expected_document') then
    raise exception 'INVENTARIO_CLIENTE_DESATUALIZADO';
  end if;
  v_expected:=nullif(p_payload->'_setta_expected_document','null'::jsonb);
  v_candidate:=p_payload-'_setta_expected_document';
  if v_candidate->>'documento' is distinct from p_documento
      or jsonb_typeof(v_candidate->'rows') is distinct from 'array'
      or (v_expected is not null and jsonb_typeof(v_expected) is distinct from 'object') then
    raise exception 'INVENTARIO_DOCUMENTO_INVALIDO';
  end if;
  -- Se a resposta se perdeu após o commit, repetir a MESMA escrita é seguro.
  if p_current is distinct from v_candidate and p_current is distinct from v_expected then
    raise exception 'INVENTARIO_CONFLITO_DE_VERSAO';
  end if;
  return v_candidate;
end;
$$;

revoke all on function public.inventario_guard_document(text,jsonb,jsonb) from public, anon, authenticated;

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
  v_current jsonb;
  v_candidate jsonb;
begin
  if coalesce(trim(p_documento),'')='' then
    raise exception 'DOCUMENTO_OBRIGATORIO';
  end if;

  -- Serialize mudanças do mesmo inventário com exclusões/encerramentos.
  perform pg_advisory_xact_lock(hashtext('inventario_rotativo:close'));
  if exists(select 1 from public.inventario_deleted_documents where documento=p_documento) then
    raise exception 'INVENTARIO_EXCLUIDO';
  end if;


  select payload->p_documento into v_current
    from public.inventario_operacional_state
    where app_key='inventario_rotativo' and state_key='inventories'
    for update;
  v_candidate:=public.inventario_guard_document(p_documento,v_current,p_payload);
  if v_current is not distinct from v_candidate then
    return jsonb_build_object('ok',true,'protected',true,'unchanged',true,'documento',p_documento);
  end if;

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values (
    'inventario_rotativo',
    'inventories',
    jsonb_build_object(p_documento,v_candidate),
    now()
  )
  on conflict (app_key,state_key) do update
  set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)
              || jsonb_build_object(p_documento,v_candidate),
      updated_at=now()
  returning updated_at into v_updated;

  return jsonb_build_object('ok',true,'protected',true,'updated_at',v_updated,'documento',p_documento);
end;
$$;

revoke all on function public.inventario_upsert_document(text,jsonb) from public, anon, authenticated;
grant execute on function public.inventario_upsert_document(text,jsonb) to service_role;

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
  v_current jsonb;
  v_candidate jsonb;
  v_cycle_codes text[];
begin
  if coalesce(trim(p_documento),'')='' then
    raise exception 'DOCUMENTO_OBRIGATORIO';
  end if;

  perform pg_advisory_xact_lock(hashtext('inventario_rotativo:close'));
  if exists(select 1 from public.inventario_deleted_documents where documento=p_documento) then
    raise exception 'INVENTARIO_EXCLUIDO';
  end if;


  select payload->p_documento into v_current
    from public.inventario_operacional_state
    where app_key='inventario_rotativo' and state_key='inventories'
    for update;
  v_candidate:=public.inventario_guard_document(p_documento,v_current,p_document);
  if v_candidate->>'status' is distinct from 'FECHADO' then
    raise exception 'INVENTARIO_NAO_PODE_SER_ENCERRADO';
  end if;
  if v_current is not distinct from v_candidate then
    return jsonb_build_object('ok',true,'protected',true,'unchanged',true,'documento',p_documento);
  end if;

  if v_current is null or v_current->>'status' not in ('AGUARDANDO ANÁLISE','AGUARDANDO DECISÃO')
      or v_current->>'status' is null then
    raise exception 'INVENTARIO_NAO_PODE_SER_ENCERRADO';
  end if;
  -- Uma reabertura do mesmo lote não conta um segundo ciclo.
  v_cycle_codes:=case when v_current->>'ciclo_marcado'='true' then array[]::text[]
    else array(select distinct code from unnest(coalesce(p_cycle_codes,array[]::text[])) as code where code is not null) end;

  insert into public.inventario_operacional_state(app_key,state_key,payload,updated_at)
  values (
    'inventario_rotativo',
    'inventories',
    jsonb_build_object(p_documento,v_candidate),
    now()
  )
  on conflict (app_key,state_key) do update
  set payload=coalesce(public.inventario_operacional_state.payload,'{}'::jsonb)
              || jsonb_build_object(p_documento,v_candidate),
      updated_at=now();

  select coalesce(payload,'{}'::jsonb)
    into v_cycles
  from public.inventario_operacional_state
  where app_key='inventario_rotativo' and state_key='cycles'
  for update;

  if v_cycles is null then v_cycles:='{}'::jsonb; end if;

  foreach v_code in array v_cycle_codes loop
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
    'protected',true,
    'documento',p_documento,
    'cycle_codes',coalesce(array_length(v_cycle_codes,1),0)
  );
end;
$$;

revoke all on function public.inventario_close_atomic(text,jsonb,text[],jsonb) from public, anon, authenticated;
grant execute on function public.inventario_close_atomic(text,jsonb,text[],jsonb) to service_role;
