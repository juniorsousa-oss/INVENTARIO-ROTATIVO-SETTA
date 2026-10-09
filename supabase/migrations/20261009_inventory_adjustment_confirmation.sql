-- Inventário SETTA: conciliação da execução de ajustes autorizados no Protheus.
-- Registros concluídos continuam no histórico geral, sem reaparecer nas cargas pendentes.
create or replace function public.inventario_registrar_ajuste(
 p_documento text, p_item_id text, p_realizado boolean, p_actor text, p_observacao text default ''
)
returns jsonb language plpgsql security definer set search_path=public as $$
declare
 v_payload jsonb;
 v_doc jsonb;
 v_item jsonb;
 v_rows jsonb;
 v_status text;
 v_event jsonb;
 v_now timestamptz:=now();
begin
 if btrim(coalesce(p_documento,''))='' or btrim(coalesce(p_item_id,''))='' then
  raise exception 'DOCUMENTO_E_ITEM_OBRIGATORIOS';
 end if;
 if btrim(coalesce(p_actor,''))='' or p_realizado is null then
  raise exception 'RESPONSAVEL_E_STATUS_OBRIGATORIOS';
 end if;
 perform pg_advisory_xact_lock(hashtext('inventario_rotativo:close'));
 select payload into v_payload
 from public.inventario_operacional_state
 where app_key='inventario_rotativo' and state_key='inventories'
 for update;
 v_doc:=v_payload->p_documento;
 if v_doc is null then raise exception 'INVENTARIO_NAO_ENCONTRADO'; end if;
 if v_doc->>'status'<>'FECHADO' then raise exception 'INVENTARIO_NAO_FECHADO'; end if;
 select item into v_item from jsonb_array_elements(v_doc->'rows') as item
 where item->>'id'=p_item_id limit 1;
 if v_item is null then raise exception 'ITEM_NAO_ENCONTRADO'; end if;
 if coalesce((v_item->>'ajuste_autorizado')::boolean,false)=false then
  raise exception 'ITEM_NAO_POSSUI_AJUSTE_AUTORIZADO';
 end if;
 v_status:=case when p_realizado then 'REALIZADO' else 'NAO_REALIZADO' end;
 v_event:=jsonb_build_object(
  'status',v_status,'registrado_em',v_now,'registrado_por',p_actor,
  'observacao',btrim(coalesce(p_observacao,''))
 );
 select jsonb_agg(
  case when row_item->>'id'=p_item_id then
   row_item || jsonb_build_object(
    'ajuste_realizado',p_realizado,'ajuste_status',v_status,
    'ajuste_validado_em',v_now,'ajuste_validado_por',p_actor,
    'ajuste_observacao',btrim(coalesce(p_observacao,'')),
    'ajuste_historico',
    coalesce(case when jsonb_typeof(row_item->'ajuste_historico')='array'
            then row_item->'ajuste_historico' end,'[]'::jsonb)
    || jsonb_build_array(v_event))
  else row_item end
  order by ord
 ) into v_rows
 from jsonb_array_elements(v_doc->'rows') with ordinality as r(row_item,ord);
 v_doc:=jsonb_set(v_doc,'{rows}',v_rows,true);
 update public.inventario_operacional_state
 set payload=jsonb_set(payload,ARRAY[p_documento],v_doc,true),updated_at=now()
 where app_key='inventario_rotativo' and state_key='inventories';
 return jsonb_build_object('ok',true,'documento',p_documento,'item_id',p_item_id,'status',v_status,'document',v_doc);
end;
$$;
revoke all on function public.inventario_registrar_ajuste(text,text,boolean,text,text) from public,anon,authenticated;
grant execute on function public.inventario_registrar_ajuste(text,text,boolean,text,text) to service_role;
