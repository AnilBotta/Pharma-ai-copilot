-- 0026 — Drop the ivfflat index. It was fast and it was wrong.
--
-- 0004 created it at a point when the table was necessarily empty, and said so:
--
--     "IVFFlat needs training data to be worth building; on an empty table it
--      would be counterproductive."
--
-- The comment identified the problem and the index was created anyway. An
-- ivfflat index derives its centroids by k-means over the rows present when it
-- is built. Built over nothing, it has no meaningful partition of the space,
-- and every vector inserted afterwards is filed under a centroid that describes
-- nothing. Queries then probe one list out of a hundred and return whatever
-- happens to be in it.
--
-- MEASURED, NOT ASSUMED - AND MEASURED TWICE, BECAUSE THE TWO DISAGREED
--
-- 2,000 uniformly distributed vectors, one query vector held fixed across both
-- queries, EXPLAIN used to confirm which access path each actually took:
--
--     index scan   top-10 overlap with exact search   0/10
--                  best similarity found              0.0396
--     seq scan     best similarity found              0.1002
--
-- There, the index did not merely reorder the results. It never saw the nearest
-- passage at all.
--
-- On a REAL corpus - 4,868 passages of a genuine PDF, embedded with
-- text-embedding-3-small - the index returned the same top three as an exact
-- scan does. So this is not a defect that was observed harming real retrieval.
-- Uniformly random vectors in 1,536 dimensions are close to a worst case: they
-- are all nearly orthogonal and have no cluster structure for centroids to find,
-- while real embeddings cluster and that corpus was unusually homogeneous.
--
-- The index is dropped anyway. What was established is that its behaviour
-- depends on a distribution nobody controls, that it can miss every true
-- neighbour, and that it was built in a way pgvector's own documentation
-- advises against. An approximate index is a deliberate trade with a measured
-- recall figure attached. This one was inherited from a migration written
-- before any data existed, and its recall had never been measured at all.
--
-- AND THE COST OF BEING RIGHT
--
-- 4,000 chunks, top-12, median of five runs, timed by the server:
--
--     with the index     0.4 ms   (wrong)
--     exact              31.6 ms  (right)
--
-- 31 ms sits inside a research run that takes around 525 seconds. Trading
-- correct retrieval for 31 milliseconds is not a trade this system should make:
-- a passage that was never retrieved cannot be cited, and its absence looks
-- exactly like the document not containing the answer.
--
-- WHEN TO REVISIT
--
-- Exact search is linear, so at roughly 100k chunks per project this becomes
-- worth measuring again. The fix at that point is to build an index AFTER the
-- corpus exists - `create index ... using ivfflat (embedding vector_cosine_ops)
-- with (lists = <rows/1000>)` - and to raise `ivfflat.probes` until recall is
-- acceptable, having first measured what recall actually is. Approximate search
-- is a legitimate choice made deliberately with a number attached; it is not a
-- default to inherit from a migration written before there was any data.

drop index if exists public.document_chunks_embedding_idx;

comment on column public.document_chunks.embedding is
  'Passage embedding, 1536 dimensions (text-embedding-3-small). Searched by '
  'exact nearest-neighbour scan: see 0026 for why the approximate index was '
  'removed and the corpus size at which to reconsider one.';
