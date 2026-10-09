-- Encaminhamento transacional de inconsistências do Inventário para Materiais com Problema em Entregas.
-- O projeto (PSY) e o material precisam existir no cache de MRP, evitando vincular OP incorreta.
create or replace function public.inventario_encaminhar_problema_entregas(
 p_report_id text,p_actor text
)
returns jsonb language plpgsql security definer set search_path=public as $$
declare
 v_payload jsonb;
 v_report jsonb;
 v_projeto text;
 v_codigo text;
 v_produto text;
 v_qtd integer;
 v_result jsonb;
 v_time timestamptz:=now();
begin
 if btrim(coalesce(p_report_id,''))='' or btrim(coalesce(p_actor,''))='' then
  raise exception 'REFERENCIA_E_RESPONSAVEL_OBRIGATORIOS';
 end if;
 perform pg_advisory_xact_lock(hashtext('inventario_rotativo:delivery:'||p_report_id));
 select payload into v_payload
 from public.inventario_operacional_state
 where app_key='inventario_rotativo' and state_key='reports'
 for update;
 v_report:=v_payload->p_report_id;
 if v_report is null then raise exception 'INCONSISTENCIA_NAO_ENCONTRADA'; end if;
 if v_report->>'delivery_sync_at' is not null then
  return jsonb_build_object('ok',true,'already_synced',true,'report',v_report);
 end if;
 if coalesce(v_report->>'status','')<>'ABERTO' then raise exception 'INCONSISTENCIA_NAO_ABERTA'; end if;
 v_projeto:=btrim(coalesce(v_report->>'psy',''));
 v_codigo:=btrim(coalesce(v_report->>'codigo',''));
 if v_projeto='' or v_codigo='' then raise exception 'PSY_E_CODIGO_OBRIGATORIOS'; end if;
 select count(distinct produto), min(produto) into v_qtd,v_produto
 from public.entrega_mrp_itens_cache
 where projeto=v_projeto
 and coalesce(nullif(ltrim(produto,'0'),''),'0')=coalesce(nullif(ltrim(v_codigo,'0'),''),'0');
 if v_qtd=0 then raise exception 'MATERIAL_NAO_LOCALIZADO_NA_PSY_NO_MRP'; end if;
 if v_qtd>1 then raise exception 'MATERIAL_AMBIGUO_NA_PSY'; end if;
 select public.entrega_registrar_mrp_operacao_lote(
  jsonb_build_array(jsonb_build_object('projeto',v_projeto,'produto',v_produto)),
  'Com problema',
  left('INVENTÁRIO ROTATIVO | '||p_report_id||' | '||
    coalesce(v_report->>'endereco','')||' | '||coalesce(v_report->>'observacao',''),1000),
  p_actor
 ) into v_result;
 v_report:=v_report || jsonb_build_object(
  'delivery_sync_at',v_time,'delivery_sync_by',p_actor,
  'delivery_status','COM PROBLEMA','delivery_produto',v_produto
 );
 update public.inventario_operacional_state
 set payload=jsonb_set(payload,ARRAY[p_report_id],v_report,true),updated_at=now()
 where app_key='inventario_rotativo' and state_key='reports';
 return jsonb_build_object('ok',true,'already_synced',false,'report',v_report,'delivery_result',v_result);
end;
$$;
revoke all on function public.inventario_encaminhar_problema_entregas(text,text) from public,anon,authenticated;
grant execute on function public.inventario_encaminhar_problema_entregas(text,text) to service_role;
