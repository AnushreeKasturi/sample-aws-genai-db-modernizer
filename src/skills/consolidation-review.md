# Consolidation Review

The one instruction for reviewing the reality check's consolidation moves. `/reality-check` (Claude Code) and the Bedrock consolidation validator (`src/agents/referee/consolidation_validator.py`) both read this file, so a moved query gets the same instruction in either mode.

## Instruction

The deterministic reality check moved some queries from one engine to another so the customer runs fewer engines. The same scorer that routes every query chose each move. For each moved query, decide whether the target engine can serve it.

Flag a query only when the target engine cannot serve its access pattern without a full scan, a client-side join, or a feature the engine lacks (see Engine Capabilities). Otherwise keep the move. A flag takes the query off its target: finalize sends it to an Aurora engine when one is in the architecture, and otherwise back to the engine it came from, which can bring that engine back for the customer to run. So a flag needs a concrete capability gap you can name, not a preference for the engine the query came from.

Judge every move the same way, whichever engine it leaves or joins, and decide from the query's SQL and signals. An empty list is the right answer when every moved query fits its target; a long list is the right answer when many don't.

DocumentDB facts below assume the target the analysis uses: DocumentDB 8.0 on an instance-based cluster, with the 8.0.2+ operators available.

## Flag When

- The query joins three or more tables with aggregation, and the target has no server-side join (DynamoDB).
- The query has a correlated subquery or `EXISTS` against another table, and the target cannot evaluate it server-side (DynamoDB).
- The query groups across several tables, and the target has no server-side cross-collection aggregation (DynamoDB).
- The query searches text (`LIKE '%...%'`, `MATCH ... AGAINST`, regex, `tsvector`, similarity), and the target has no text index or search operator for it (DynamoDB; DocumentDB when the search needs fuzzy matching or language analyzers).
- The query filters on attributes with no known key, so the target would scan (DynamoDB).
- The query is a transactional write that exceeds the target's transaction limits, or the target has no transactions (OpenSearch; DynamoDB above 100 actions or 4 MB).
- The query is the write path of record, or needs to read its own writes immediately, and the target is OpenSearch.

## Do Not Flag

- Key lookups, range reads on a sort key and single-item writes on a key-value or document target.
- Queries that only need denormalization, a new index, a GSI or an embedded document on the target: that work is expected and schema design does it.
- Low-frequency administrative queries that any engine can serve.
- A query whose only issue is that the source engine would also serve it.

## Engine Capabilities

### dynamodb

DynamoDB, a key-value and document store; access patterns are defined up front.

- Serves: single-item lookups by primary key, range queries on a sort key, denormalized aggregates through a GSI, key-value CRUD, session and metadata lookups, transactions of up to 100 actions or 4 MB.
- Cannot serve: ad-hoc queries, multi-table JOINs (needs denormalization), full-text search, aggregation across partitions, queries without a known partition key (full scan), transactions over 100 actions or 4 MB.

### documentdb

Amazon DocumentDB, a MongoDB-compatible document database.

- Serves: flexible schemas, nested document queries, aggregation pipelines, `$lookup` joins, multi-document ACID transactions (one-minute limit), basic `$regex` matching, basic English text indexes; on 8.0 instance-based clusters also `$graphLookup`, `$facet`, `$setWindowFields` and correlated `$lookup`.
- Cannot serve: full-text search that needs fuzzy matching or language analyzers (text indexes score by term frequency with field weights only, English only, one per collection), LAG/LEAD and NTILE window functions (no operator on any version), write throughput beyond one writer instance (instance-based clusters; elastic clusters shard writes but drop transactions and most 8.0 operators).

### opensearch

Amazon OpenSearch Service, a search and analytics engine.

- Serves: full-text search, fuzzy matching, aggregations and analytics, time series, geospatial queries, faceted search.
- Cannot serve: ACID transactions, strong read-after-write consistency, the primary write path (it is not a source of truth), complex relational queries, frequent single-document updates (reindexing cost).

### elasticache

Amazon ElastiCache, in-memory data structures.

- Never a consolidation target: it owns no query. Hot reads keep their owner engine and are fronted by the cache (the cache overlay, `cache_engine`). Flag any query moved to it.

### aurora_postgresql

Amazon Aurora PostgreSQL, a relational database.

- Serves: multi-table JOINs, complex GROUP BY, correlated and `EXISTS` subqueries, ACID transactions, ad-hoc queries, window functions, `pg_trgm` similarity search.
- Cannot serve: write throughput beyond one writer instance (Aurora PostgreSQL Limitless Database shards writes, a separate deployment model), storage beyond the cluster volume limit (128 TiB, or 256 TiB on recent versions), single-digit-millisecond lookups at millions of requests per second.

### aurora_mysql

Amazon Aurora MySQL, a relational database.

- Serves: multi-table JOINs, complex GROUP BY, correlated and `EXISTS` subqueries, ACID transactions, ad-hoc queries, window functions, `FULLTEXT` search.
- Cannot serve: write throughput beyond one writer instance, storage beyond the cluster volume limit (128 TiB, or 256 TiB on recent versions), single-digit-millisecond lookups at millions of requests per second.
