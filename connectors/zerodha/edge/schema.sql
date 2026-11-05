-- One row: the encrypted Zerodha session for the day. RLS on with no policies, so only the
-- edge function (service role) can read or write it — the public anon key cannot.
create table if not exists public.kite_session (
  id int primary key default 1 check (id = 1),
  ciphertext text not null,
  login_time text,
  updated_at timestamptz not null default now()
);
alter table public.kite_session enable row level security;
revoke all on public.kite_session from anon, authenticated;
