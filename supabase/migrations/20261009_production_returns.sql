-- Gestão de Estoque SETTA: retornos de produção e perfil de acesso restrito.
-- Usuários OperaHub continuam centralizados; somente o perfil especial é mapeado aqui.
create table if not exists public.inventario_acessos_especiais (
 user_id uuid primary key,
 perfil text not null check (perfil in ('PRODUCAO')),
 criado_em timestamptz not null default now(),
 criado_por text
);
alter table public.inventario_acessos_especiais enable row level security;
revoke all on table public.inventario_acessos_especiais from public,anon,authenticated;
grant select,insert,update,delete on table public.inventario_acessos_especiais to service_role;

create table if not exists public.inventario_retornos_producao (
 id uuid primary key default gen_random_uuid(),
 codigo text not null,
 descricao text not null default '',
 quantidade numeric(18,3) not null check (quantidade>0),
 psy text not null,
 observacao_producao text not null default '',
 status text not null default 'PENDENTE'
   check(status in ('PENDENTE','RECEBIDO','CONCLUIDO','RECUSADO')),
 criado_por_id text not null,
 criado_por text not null,
 criado_em timestamptz not null default now(),
 recebido_por text,
 recebido_em timestamptz,
 concluido_por text,
 concluido_em timestamptz,
 referencia_protheus text,
 observacao_almox text not null default '',
 historico jsonb not null default '[]'::jsonb
);
create index if not exists idx_inventario_retornos_status_data
 on public.inventario_retornos_producao(status,criado_em desc);
create index if not exists idx_inventario_retornos_ator
 on public.inventario_retornos_producao(criado_por_id,criado_em desc);
alter table public.inventario_retornos_producao enable row level security;
revoke all on table public.inventario_retornos_producao from public,anon,authenticated;
grant select,insert,update on table public.inventario_retornos_producao to service_role;

create or replace function public.inventario_retorno_mudar_status(
 p_id uuid,p_novo_status text,p_responsavel text,
 p_observacao text default '',p_referencia_protheus text default ''
)
returns jsonb language plpgsql security definer set search_path=public as $$
declare
 atual public.inventario_retornos_producao%rowtype;
 novo text:=upper(btrim(coalesce(p_novo_status,'')));
 obs text:=btrim(coalesce(p_observacao,''));
 referencia text:=btrim(coalesce(p_referencia_protheus,''));
 evento jsonb;
 outrow public.inventario_retornos_producao%rowtype;
begin
 if nullif(btrim(coalesce(p_responsavel,'')),'') is null then raise exception 'RESPONSAVEL_OBRIGATORIO'; end if;
 select * into atual from public.inventario_retornos_producao where id=p_id for update;
 if not found then raise exception 'RETORNO_NAO_ENCONTRADO'; end if;
 if atual.status='PENDENTE' and novo not in ('RECEBIDO','RECUSADO') then
  raise exception 'TRANSICAO_INVALIDA';
 elsif atual.status='RECEBIDO' and novo<>'CONCLUIDO' then
  raise exception 'TRANSICAO_INVALIDA';
 elsif atual.status in ('CONCLUIDO','RECUSADO') then
  raise exception 'RETORNO_JA_ENCERRADO';
 end if;
 if novo='RECUSADO' and obs='' then raise exception 'MOTIVO_RECUSA_OBRIGATORIO'; end if;
 if novo='CONCLUIDO' and referencia='' then raise exception 'REFERENCIA_PROTHEUS_OBRIGATORIA'; end if;
 evento:=jsonb_build_object('status',novo,'quando',now(),'responsavel',p_responsavel,'observacao',obs,'referencia',referencia);
 update public.inventario_retornos_producao set
  status=novo,
  observacao_almox=case when obs<>'' then obs else observacao_almox end,
  recebido_por=case when novo='RECEBIDO' then p_responsavel else recebido_por end,
  recebido_em=case when novo='RECEBIDO' then now() else recebido_em end,
  concluido_por=case when novo in ('CONCLUIDO','RECUSADO') then p_responsavel else concluido_por end,
  concluido_em=case when novo in ('CONCLUIDO','RECUSADO') then now() else concluido_em end,
  referencia_protheus=case when novo='CONCLUIDO' then referencia else referencia_protheus end,
  historico=coalesce(historico,'[]'::jsonb)||jsonb_build_array(evento)
 where id=p_id returning * into outrow;
 return to_jsonb(outrow);
end;
$$;
revoke all on function public.inventario_retorno_mudar_status(uuid,text,text,text,text) from public,anon,authenticated;
grant execute on function public.inventario_retorno_mudar_status(uuid,text,text,text,text) to service_role;
