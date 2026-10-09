-- Perfis locais distintos para solicitação e conferência das devoluções.
alter table public.inventario_acessos_especiais
 drop constraint if exists inventario_acessos_especiais_perfil_check;
alter table public.inventario_acessos_especiais
 add constraint inventario_acessos_especiais_perfil_check
 check (perfil in ('PRODUCAO','ALMOXARIFADO'));
