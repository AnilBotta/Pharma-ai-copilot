-- 0023 — The Manager Agent gets a memory.
--
-- WHY THE TRANSCRIPT LIVES HERE AND NOT IN THE BROWSER
--
-- The obvious implementation of a chat is to keep the messages in React state
-- and post the whole conversation back each turn. It works, and it is wrong
-- here for two reasons.
--
-- The first is ordinary: a director who closes the tab loses the thread, and
-- the questions asked of this agent - what is blocking Gate 1, why was that
-- approval withdrawn - are exactly the ones somebody wants to refer back to.
--
-- The second matters more. This agent will, in a later migration, be able to
-- propose an approval. A proposal has to be traceable to the exchange that
-- produced it: what was asked, what the agent read, what it concluded. A
-- transcript held in a browser tab is not a record. An action whose reasoning
-- cannot be reconstructed afterwards is precisely what the audit trail in 0011
-- exists to prevent, and it would be odd to spend six migrations on that and
-- then let the agent act on evidence nobody kept.
--
-- WHAT IS DELIBERATELY NOT HERE
--
-- No `status` on a conversation, no `is_complete`. A conversation is a list of
-- messages; whether it is "finished" is not a fact about it.

-- --------------------------------------------------- manager_conversations ---

create table public.manager_conversations (
  id uuid primary key default gen_random_uuid(),

  --: Conversations are private to one person. Not project-scoped: a portfolio
  --: question spans programmes, and a director asking "where are we" is not
  --: asking about one project.
  user_id uuid not null references auth.users(id) on delete cascade,

  --: Derived from the opening question, not asked for. A titling prompt would
  --: be a second model call to name something the first message already says.
  title text not null default 'New conversation',

  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  archived_at timestamptz
);

create index manager_conversations_user_idx
  on public.manager_conversations (user_id, updated_at desc)
  where archived_at is null;

-- -------------------------------------------------------- manager_messages ---

create table public.manager_messages (
  id bigint generated always as identity primary key,

  conversation_id uuid not null
    references public.manager_conversations(id) on delete cascade,

  --: `tool` rows record what the agent read. They are what make an answer
  --: checkable after the fact: not "it said Gate 1 was blocked" but "it read
  --: get_gate(<id>) and this is what came back".
  role text not null check (role in ('user', 'assistant', 'tool')),

  content text,

  tool_name      text,
  tool_arguments jsonb,
  tool_result    jsonb,

  --: True when a limit stopped the turn. Stored rather than inferred, so the
  --: UI can say the answer is incomplete every time it is redisplayed and not
  --: only in the session that produced it.
  truncated        boolean not null default false,
  truncated_reason text,

  input_tokens       integer not null default 0,
  output_tokens      integer not null default 0,
  estimated_cost_usd numeric(12,6),

  created_at timestamptz not null default now()
);

create index manager_messages_conversation_idx
  on public.manager_messages (conversation_id, id);

-- A tool row without a tool name, or a user turn carrying one, means the
-- writer has confused two things. Cheap to assert, and the alternative is
-- discovering it in a transcript six weeks later.
alter table public.manager_messages
  add constraint tool_rows_name_their_tool check (
    (role = 'tool' and tool_name is not null)
    or (role <> 'tool' and tool_name is null)
  );

-- ------------------------------------------------------------- keep updated ---

create or replace function private.touch_manager_conversation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.manager_conversations
     set updated_at = now()
   where id = new.conversation_id;
  return new;
end;
$$;

create trigger manager_messages_touch_conversation
  after insert on public.manager_messages
  for each row execute function private.touch_manager_conversation();

-- ------------------------------------------------------------------ policies ---

alter table public.manager_conversations enable row level security;
alter table public.manager_messages      enable row level security;

create policy manager_conversations_own on public.manager_conversations
  for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy manager_messages_own on public.manager_messages
  for all to authenticated
  using (
    exists (
      select 1 from public.manager_conversations c
       where c.id = conversation_id
         and c.user_id = (select auth.uid())
    )
  )
  with check (
    exists (
      select 1 from public.manager_conversations c
       where c.id = conversation_id
         and c.user_id = (select auth.uid())
    )
  );

comment on table public.manager_conversations is
  'Manager Agent chat threads, private to one user. Kept server-side because a '
  'later migration lets this agent propose accountable acts, and a proposal '
  'must be traceable to the exchange that produced it.';
