-- Inventário Rotativo | sessão administrativa
-- Aplicado em produção em 2026-10-04.

create table if not exists public.inventario_auth_sessions (
  token uuid primary key,
  user_id text not null,
  username text not null,
  full_name text,
  role text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);

alter table public.inventario_auth_sessions enable row level security;
revoke all on table public.inventario_auth_sessions from public, anon, authenticated;
grant select, insert, delete on table public.inventario_auth_sessions to service_role;

create index if not exists inventario_auth_sessions_expires_idx
  on public.inventario_auth_sessions(expires_at);
