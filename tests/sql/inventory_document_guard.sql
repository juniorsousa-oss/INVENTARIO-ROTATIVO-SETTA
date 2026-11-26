-- Somente em banco vazio de teste, após as migrations (banco temporário).
do $test$
declare
 k constant text := 'TESTE-LOTE-A';
 k2 constant text := 'TESTE-LOTE-B';
 base jsonb := '{"documento":"TESTE-LOTE-A","status":"EM CONTAGEM","rows":[{"id":"1","contagens":[]},{"id":"2","contagens":[]}]}'::jsonb;
 initial_b jsonb := '{"documento":"TESTE-LOTE-B","status":"EM CONTAGEM","rows":[]}'::jsonb;
 a jsonb;
 stale_b jsonb;
 combined jsonb;
 b_results jsonb;
 ready jsonb;
 closed jsonb;
 reopened jsonb;
 stored jsonb;
 cycles jsonb;
 reports jsonb;
 answer jsonb;
begin
 if has_function_privilege('anon','public.inventario_upsert_document(text,jsonb)','EXECUTE')
    or has_function_privilege('authenticated','public.inventario_guard_document(text,jsonb,jsonb)','EXECUTE') then
  raise exception 'TESTE_CONCESSOES_INCORRETAS';
 end if;
 begin
  perform public.inventario_upsert_document(k,base);
  raise exception 'TESTE_CLIENTE_ANTIGO_ACEITO';
 exception when raise_exception then
  if sqlerrm <> 'INVENTARIO_CLIENTE_DESATUALIZADO' then raise; end if;
 end;
 answer:=public.inventario_upsert_document(k,base||'{"_setta_expected_document":null}'::jsonb);
 if answer->>'protected' is distinct from 'true' then raise exception 'TESTE_SEM_CONFIRMACAO'; end if;
 perform public.inventario_upsert_document(k2,initial_b||'{"_setta_expected_document":null}'::jsonb);
 a:=jsonb_set(base,'{rows,0,contagens}','[{"quantidade":7}]',false);
 stale_b:=jsonb_set(base,'{rows,1,contagens}','[{"quantidade":8}]',false);
 perform public.inventario_upsert_document(k,a||jsonb_build_object('_setta_expected_document',base));
 answer:=public.inventario_upsert_document(k,a||jsonb_build_object('_setta_expected_document',base));
 if answer->>'unchanged' is distinct from 'true' then raise exception 'TESTE_RETRY_NAO_IDEMPOTENTE'; end if;
 begin
  perform public.inventario_upsert_document(k,stale_b||jsonb_build_object('_setta_expected_document',base));
  raise exception 'TESTE_GRAVACAO_DESATUALIZADA_ACEITA';
 exception when raise_exception then
  if sqlerrm <> 'INVENTARIO_CONFLITO_DE_VERSAO' then raise; end if;
 end;
 select payload into stored from public.inventario_operacional_state
  where app_key='inventario_rotativo' and state_key='inventories';
 if stored->k is distinct from a then raise exception 'TESTE_PERDEU_PRIMEIRA_CONTAGEM'; end if;

 -- Um lote distinto não entra em conflito por usar o mesmo campo JSON global.
 b_results:=initial_b||'{"status":"AGUARDANDO ANÁLISE"}'::jsonb;
 perform public.inventario_upsert_document(k2,b_results||jsonb_build_object('_setta_expected_document',initial_b));
 combined:=jsonb_set(a,'{rows,1,contagens}','[{"quantidade":8}]',false);
 ready:=combined||'{"status":"AGUARDANDO DECISÃO"}'::jsonb;
 perform public.inventario_upsert_document(k,ready||jsonb_build_object('_setta_expected_document',a));
 closed:=ready||'{"status":"FECHADO","ciclo_marcado":true}'::jsonb;
 begin
  perform public.inventario_close_atomic(k,closed||jsonb_build_object('_setta_expected_document',a),
   array['123'],'{"rel":"errado"}');
  raise exception 'TESTE_FECHAMENTO_DESATUALIZADO_ACEITO';
 exception when raise_exception then
  if sqlerrm <> 'INVENTARIO_CONFLITO_DE_VERSAO' then raise; end if;
 end;
 perform public.inventario_close_atomic(k,closed||jsonb_build_object('_setta_expected_document',ready),
  array['123','123'],'{"rel":"ok"}');
 answer:=public.inventario_close_atomic(k,closed||jsonb_build_object('_setta_expected_document',ready),
  array['123'],'{"rel":"duplicado"}');
 if answer->>'unchanged' is distinct from 'true' then raise exception 'TESTE_FECHAMENTO_NAO_IDEMPOTENTE'; end if;
 reopened:=closed||'{"status":"AGUARDANDO DECISÃO"}'::jsonb;
 perform public.inventario_upsert_document(k,reopened||jsonb_build_object('_setta_expected_document',closed));
 perform public.inventario_close_atomic(k,closed||jsonb_build_object('_setta_expected_document',reopened),array['123']);
 select payload into cycles from public.inventario_operacional_state where app_key='inventario_rotativo' and state_key='cycles';
 select payload into reports from public.inventario_operacional_state where app_key='inventario_rotativo' and state_key='reports';
 select payload into stored from public.inventario_operacional_state where app_key='inventario_rotativo' and state_key='inventories';
 if cycles->>'123' is distinct from '1' or reports->>'rel' is distinct from 'ok'
    or stored->k is distinct from closed or stored->k2 is distinct from b_results then
  raise exception 'TESTE_ESTADO_FINAL_DIVERGENTE';
 end if;
 insert into public.inventario_deleted_documents(documento,deleted_by) values(k,'fixture');
 begin
  perform public.inventario_upsert_document(k,reopened||jsonb_build_object('_setta_expected_document',closed));
  raise exception 'TESTE_DOCUMENTO_EXCLUIDO_ACEITO';
 exception when raise_exception then
  if sqlerrm <> 'INVENTARIO_EXCLUIDO' then raise; end if;
 end;
end
$test$;
