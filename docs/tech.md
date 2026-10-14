# Verified technical facts (SDKs, server, models)

Verified on **2026-10-14** (spec `2026-10-14-infra-and-corpus`, task 1.1). Every row cites a URL or local
introspection output. Anything not verifiable is marked **UNVERIFIED**. Re-verify on any version bump.

Local introspection: scratch venv, Python 3.12.15,
`pip install --no-input ollama==0.6.3 "psycopg[binary]==3.3.6" pgvector==0.5.0`.
Resolved versions: `ollama 0.6.3`, `psycopg 3.3.6`, `psycopg-binary 3.3.6`, `pgvector 0.5.0`,
`httpx 0.28.1`, `pydantic 2.14.1` (transitive; `importlib.metadata.requires("ollama")` =
`['httpx>=0.27', 'pydantic>=2.9']`, so the plan's pin `pydantic==2.13.5` satisfies it).
`pgvector 0.5.0` declares no dependencies (numpy is optional).

## 1. `ollama` Python package 0.6.3

### 1.1 Signatures (`inspect.signature()` output, verbatim)

```
ollama.Client.__init__
(self, host: Optional[str] = None, **kwargs) -> None

ollama.Client.chat
(self, model: str = '', messages: Optional[Sequence[Union[Mapping[str, Any], ollama._types.Message]]] = None, *, tools: Optional[Sequence[Union[Mapping[str, Any], ollama._types.Tool, Callable]]] = None, stream: bool = False, think: Union[bool, str, NoneType] = None, logprobs: Optional[bool] = None, top_logprobs: Optional[int] = None, format: Union[Literal['', 'json'], dict[str, Any], NoneType] = None, options: Union[Mapping[str, Any], ollama._types.Options, NoneType] = None, keep_alive: Union[float, str, NoneType] = None) -> Union[ollama._types.ChatResponse, collections.abc.Iterator[ollama._types.ChatResponse]]

ollama.Client.embed
(self, model: str = '', input: Union[str, Sequence[str]] = '', truncate: Optional[bool] = None, options: Union[Mapping[str, Any], ollama._types.Options, NoneType] = None, keep_alive: Union[float, str, NoneType] = None, dimensions: Optional[int] = None) -> ollama._types.EmbedResponse
```

### 1.2 Facts

| Fact | Source |
|---|---|
| `Client(host=None, **kwargs)`; `kwargs` go to `BaseClient.__init__(client, host=None, *, follow_redirects=True, timeout=None, headers=None, **kwargs)` and then to `httpx.Client`. Default `timeout=None` (no timeout) -> set `timeout=` explicitly. | `ollama/_client.py` lines 83-122 (installed 0.6.3) |
| Host resolution: `host or os.getenv('OLLAMA_HOST')`; `None`/`''` -> `http://127.0.0.1:11434`; bare `host:port` gets `http://`. | `_parse_host` doctests, `ollama/_client.py` line 1393 |
| If env `OLLAMA_API_KEY` is set and no `authorization` header is given, the client sends `Authorization: Bearer <key>`. Leave it unset for local Ollama. | `ollama/_client.py` lines 112-114 |
| The client also exposes `web_search`/`web_fetch`, which call `https://ollama.com/api/...`. Do not use them: data would leave the machine. | `ollama/_client.py` lines 701-720 |
| `chat(..., stream=False)` returns one `ChatResponse`; `stream=True` returns an iterator. | signature above |
| `tools` accepts dicts (JSON schema), `ollama.Tool`, or Python callables. Callables are converted by `convert_function_to_tool` (docstring + type hints); dicts by `Tool.model_validate`. | `_copy_tools`, `ollama/_client.py` line 1378; `ollama/_utils.py` line 56 |
| `options` accepts a dict or `ollama.Options`; it includes `num_ctx`, `num_predict`, `temperature`, `seed`, `top_k`, `top_p`, `stop`, `num_thread`, and others (all `Optional`). | `Options.model_fields` (introspection) |
| Errors: `ollama.ResponseError` with `.status_code` (README example checks `404`), plus `ollama.RequestError`. | https://github.com/ollama/ollama-python/blob/main/README.md; `ollama/_types.py` lines 691, 702 |
| Tool results go back as `{"role": "tool", "tool_name": call.function.name, "content": str(result)}`. Calls are read via `response.message.tool_calls` -> `call.function.name`, `call.function.arguments`. | https://github.com/ollama/ollama/blob/main/docs/capabilities/tool-calling.mdx |

### 1.3 Response classes (`model_fields`, verbatim from introspection)

All response classes subclass `SubscriptableBaseModel(pydantic.BaseModel)`. It defines `__getitem__`,
`__setitem__`, `__contains__` and `get`, so **both attribute access (`r.message.content`) and dict access
(`r["message"]["content"]`, `r.get("eval_count")`) work.** `__getitem__` raises `KeyError` for unknown keys.
The README shows both styles (https://github.com/ollama/ollama-python/blob/main/README.md).

```
BaseGenerateResponse(SubscriptableBaseModel)
   model                Optional[str]  default=None
   created_at           Optional[str]  default=None
   done                 Optional[bool] default=None
   done_reason          Optional[str]  default=None
   total_duration       Optional[int]  default=None
   load_duration        Optional[int]  default=None
   prompt_eval_count    Optional[int]  default=None
   prompt_eval_duration Optional[int]  default=None
   eval_count           Optional[int]  default=None
   eval_duration        Optional[int]  default=None

ChatResponse(BaseGenerateResponse)   + message: Message (required)
                                     + logprobs: Optional[Sequence[Logprob]] = None
EmbedResponse(BaseGenerateResponse)  + embeddings: Sequence[Sequence[float]] (required)

Message(SubscriptableBaseModel)
   role        str (required)
   content     Optional[str] = None
   thinking    Optional[str] = None
   images      Optional[Sequence[Image]] = None
   tool_name   Optional[str] = None
   tool_calls  Optional[Sequence[Message.ToolCall]] = None

Message.ToolCall           function: Message.ToolCall.Function (required)
Message.ToolCall.Function  name: str (required); arguments: Mapping[str, Any] (required)

Tool             type: Optional[str] = 'function'; function: Optional[Tool.Function] = None
Tool.Function    name, description: Optional[str]; parameters: Optional[Tool.Function.Parameters]
Tool.Function.Parameters  type: Optional[Literal['object']] = 'object'; defs (alias '$defs');
                          items; required: Optional[Sequence[str]];
                          properties: Optional[Mapping[str, Property]]
   Property      type: Optional[str | Sequence[str]]; items; description: Optional[str]; enum: Optional[Sequence]
```

Consequences for `LLMClient`:
- Every count and duration is `Optional[int]` and defaults to `None`. Map `None -> 0` (design: "handles missing counts as 0").
- `message.content` is `Optional[str]` and can be `None` or `""` when the model returns only tool calls.
- `message.tool_calls` is `None` when there are no calls. `function.arguments` is a **dict** (`Mapping[str, Any]`), not a JSON string. Checked: `ChatResponse.model_validate({... "arguments": {"q": "x"}})` gives `type(...arguments) == dict`.
- Usage mapping: input tokens = `prompt_eval_count`, output tokens = `eval_count`.

### 1.4 Durations and token counts

| Fact | Source |
|---|---|
| "All durations are returned in nanoseconds" (`total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration`). | https://github.com/ollama/ollama/blob/main/docs/api.md (page notes the API docs are moving to https://docs.ollama.com/api) |
| `/api/chat` final response carries `prompt_eval_count`, `eval_count`, `total_duration` (example: 26 / 282 / 4883583458). | same |
| `/api/embed` response schema: `model`, `embeddings`, `total_duration` (ns), `load_duration` (ns), `prompt_eval_count` = "Number of input tokens processed to generate embeddings". No response field is marked required. | https://docs.ollama.com/api/embed |
| Server code (main branch): `EmbedResponse{..., PromptEvalCount: int(totalTokens)}`, where `totalTokens` is the **sum over all inputs** of the token counts returned by the runner. So embed token counts are reported for batch input too. | https://github.com/ollama/ollama/blob/main/server/routes.go (`EmbedHandler`) |
| The multi-input example in `docs/api.md` shows only `model` + `embeddings`. This conflicts with the server code above; treat the example as abbreviated. | https://github.com/ollama/ollama/blob/main/docs/api.md |

**Embed token fallback (approximate):** `LLMClient.embed()` reports only `EmbedResponse.prompt_eval_count`
(0 if `None`); it does not estimate. `llm.py` exposes `approx_embed_tokens(texts)` = `sum(ceil(len(text) / 4))`,
which Variant B may apply when the count is missing. The 4-chars-per-token ratio is a rough heuristic, **not** a
documented Ollama or bge-m3 value; any such number must be marked approximate (`embed_tokens_approx`).

**Verified at runtime (2026-10-14):** `ollama/ollama:0.40.0` + `bge-m3` reports `prompt_eval_count` on
`/api/embed`: `embed_tokens` = 10 for one short sentence, i.e. greater than 0. Source: `decisions.md`
("2026-10-14 — Group 3 smoke test", spec `2026-10-14-infra-and-corpus`). That check used a single short input;
a multi-input (list) request was not measured separately, so the summed-count behaviour for lists still
rests on the server source above (from `main`, not the `v0.40.0` tag).

**UNVERIFIED:** Whether
`prompt_eval_count` on `/api/chat` drops when the server reuses a cached prompt prefix across agentic-loop
turns. That would understate input tokens. Not documented on the pages read.

## 2. Ollama server (image `ollama/ollama:0.40.0`)

| Fact | Source |
|---|---|
| Index digest `sha256:1bef639749741b375e9a1eb2c1346fb57ce52f5432de1f74846e44ccc18e1687` (amd64 `sha256:2b28812c...2746`, arm64 `sha256:030ae99b...c309`); created 2026-10-06T17:57:19Z. | `docker buildx imagetools inspect ollama/ollama:0.40.0` |
| Image config: `Entrypoint ["/bin/ollama"]`, `Cmd ["serve"]`, `ENV OLLAMA_HOST=0.0.0.0:11434`, `EXPOSE 11434/tcp`, **`Healthcheck: null`** (none built in). Base `ubuntu:24.04` with `ca-certificates libvulkan1 libopenblas0` only. | same inspect; https://raw.githubusercontent.com/ollama/ollama/main/Dockerfile |
| **No `curl`, `wget` or `nc` in the image**; `bash` is at `/usr/bin/bash`. | `docker run --rm --network none --entrypoint sh <image@digest> -c 'command -v curl ...'` -> `curl: MISSING`, `wget: MISSING`, `nc: MISSING` |
| **Healthcheck: `["CMD", "ollama", "list"]`** works. Exit code is 1 when the server is down ("could not connect to ollama server") and 0 once `ollama serve` is up (prints the empty `NAME ID SIZE MODIFIED` table). The CLI uses `OLLAMA_HOST` from the image env (0.0.0.0:11434) to reach the local server. | same container test (exit codes captured) |
| `ollama --version` with no server prints a warning; the client version is `0.40.0`. | same container test |

### 2.1 REST endpoints

| Endpoint | Facts | Source |
|---|---|---|
| `POST /api/chat` | `model` (required), `messages` (`role`, `content`, `thinking`, `images`, `tool_calls`, `tool_name`), `tools`, `think`; advanced: `format`, `options`, `stream`, `keep_alive`. `tool_calls[].function.arguments` is a JSON object in the examples. | https://github.com/ollama/ollama/blob/main/docs/api.md |
| `POST /api/embed` | `model`, `input` (string or array), `truncate` (default `true`; `false` returns an error on overflow), `dimensions`, `keep_alive`, `options`. | https://docs.ollama.com/api/embed |
| `GET /api/tags` | "List models that are available locally"; `{"models": [{name, model, modified_at, size, digest, details{...}}]}`. | https://github.com/ollama/ollama/blob/main/docs/api.md |
| `POST /api/pull` | `model`, `insecure`, `stream`. Streams status objects ending in `success`; with `stream:false` returns `{"status":"success"}`. Cancelled pulls resume. | same |

### 2.2 Environment variables (CPU-only)

| Variable | Default / behaviour | Source |
|---|---|---|
| `OLLAMA_HOST` | Server binds `127.0.0.1:11434` by default; the image sets `0.0.0.0:11434`. Publish the port as `127.0.0.1:11434:11434` in compose. | https://docs.ollama.com/faq; image inspect |
| **Context length** | FAQ: "By default, Ollama uses a context window size of 4096 tokens", which `OLLAMA_CONTEXT_LENGTH` overrides. Context-length page: default is VRAM-based (<24 GiB -> 4k, 24-48 -> 32k, >=48 -> 256k). **Observed in `ollama/ollama:0.40.0` on this CPU-only host:** startup log `OLLAMA_CONTEXT_LENGTH:0` and `msg="vram-based default context" total_vram="0 B" default_num_ctx=4096`. So **the effective default is 4096 tokens**, far below llama3.2's 128K. Set `OLLAMA_CONTEXT_LENGTH` (server-wide) or `options={"num_ctx": N}` per request. Otherwise long RAG prompts are silently truncated. | https://docs.ollama.com/faq; https://docs.ollama.com/context-length; container log |
| Embed truncation | `EmbedHandler` truncates input to `min(opts.NumCtx, model context_length)` (default `truncate=true`). With the 4096 default this caps bge-m3 below its 8192-token maximum unless `num_ctx` is raised. | https://github.com/ollama/ollama/blob/main/server/routes.go |
| `OLLAMA_NUM_PARALLEL` | Default 1 (log: `OLLAMA_NUM_PARALLEL:1`). "Required RAM will scale by `OLLAMA_NUM_PARALLEL` * `OLLAMA_CONTEXT_LENGTH`." | https://docs.ollama.com/faq; container log |
| `OLLAMA_KEEP_ALIVE` | Default 5 minutes (log: `OLLAMA_KEEP_ALIVE:5m0s`). The per-request `keep_alive` overrides it. | same |
| `OLLAMA_MAX_LOADED_MODELS` | "3 * the number of GPUs or 3 for CPU inference". | https://docs.ollama.com/faq |
| `OLLAMA_MAX_QUEUE` | Default 512; returns 503 when full. | same |
| `OLLAMA_FLASH_ATTENTION` / `OLLAMA_KV_CACHE_TYPE` | Flash attention is automatic where supported; KV cache type defaults to `f16` (`q8_0`, `q4_0` only with flash attention). | same |
| CPU memory | On CPU, concurrency memory is system RAM. Observed: `inference compute ... library=cpu total="15.4 GiB"`. `ollama ps` shows "100% CPU" and a CONTEXT column (the allocated context). | https://docs.ollama.com/faq; https://docs.ollama.com/context-length; container log |

## 3. psycopg 3.3.6 + pgvector-python 0.5.0 + pgvector 0.8.7

```
pgvector.psycopg.register_vector
(context: psycopg.Connection[typing.Any], /) -> None
```

| Fact | Source |
|---|---|
| `from pgvector.psycopg import register_vector`; call `register_vector(conn)` once per connection, after the extension exists. Async: `register_vector_async(conn)`. With a pool: `ConnectionPool(..., configure=configure)` where `configure(conn)` calls `register_vector(conn)`. | https://github.com/pgvector/pgvector-python/blob/master/README.md; `pgvector/psycopg/register.py` |
| `register_vector` runs `TypeInfo.fetch(conn, 'vector')` and raises `psycopg.ProgrammingError('vector type not found in the database')` if the extension is missing. It also registers `bit`, plus `halfvec`/`sparsevec` when present. | `pgvector/psycopg/register.py`, `pgvector/psycopg/vector.py` (installed 0.5.0) |
| **Dumpers are registered for `pgvector.Vector` and `numpy.ndarray` only, not plain `list`.** Wrap Python lists: `from pgvector import Vector; Vector([..])`. The README insert example does this. Loaded values come back as `Vector`; use `.to_list()` or `.to_numpy()`. | `pgvector/psycopg/vector.py` (`register_vector_info`), `pgvector/vector.py`; README |
| `CREATE EXTENSION vector;` once per database (Python: `conn.execute('CREATE EXTENSION IF NOT EXISTS vector')`). | https://github.com/pgvector/pgvector/blob/master/README.md; pgvector-python README |
| Column: `embedding vector(N)`, e.g. `CREATE TABLE items (id bigserial PRIMARY KEY, embedding vector(3));` | pgvector README |
| Operators: `<->` L2, `<#>` negative inner product, **`<=>` cosine distance**, `<+>` L1. | pgvector README |
| HNSW: `CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops);` options `m` (default 16), `ef_construction` (default 64); `SET hnsw.ef_search` (default 40). | pgvector README |
| IVFFlat: `CREATE INDEX ON items USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);` `SET ivfflat.probes = 10;` (default 1). For cosine, use `vector_cosine_ops`. | pgvector README |
| Limits: `vector` up to 16,000 dims; indexable up to 2,000 dims (`halfvec` up to 4,000). bge-m3's 1024 dims (section 5) can be indexed. | pgvector README |
| README install line: `git clone --branch v0.8.7`, which matches the image `pgvector/pgvector:0.8.7-pg17-trixie`. Index digest `sha256:7a7e9f22015b67edb4bef5c59daeebcd7e74bfa570df6ce60ae01237c8648a84`. | pgvector README; `docker buildx imagetools inspect pgvector/pgvector:0.8.7-pg17-trixie` |

Query pattern: `conn.execute("SELECT id FROM chunks ORDER BY embedding <=> %s LIMIT %s", (Vector(q), k))`.

## 4. Llama 3.2 (chat model `llama3.2:1b`)

| Fact | Source |
|---|---|
| Ollama tags: `llama3.2:1b` 1.3GB; `llama3.2:3b` (= `latest`) 2.0GB; "128K context window"; capability tag `tools`; "English, German, French, Italian, Portuguese, Hindi, Spanish, and Thai are officially supported." The page states no licence. | https://ollama.com/library/llama3.2 |
| Licence: **"LLAMA 3.2 COMMUNITY LICENSE AGREEMENT"**, "Llama 3.2 Version Release Date: September 25, 2024". | https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE (Meta's repo; linked from the model card https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct) |
| Meta's own site: `https://www.llama.com/llama3_2/license/` -> 301 to `developer.meta.com/ai/llama3_2/license/` -> 302 to `dev.meta.ai/llama/llama3-2/license/`, which returned **404** on 2026-10-14. The licence text was therefore taken from Meta's GitHub repo and HF card above. | WebFetch redirect chain |
| Attribution (1.b.i): when distributing Llama Materials or products using them, "prominently display 'Built with Llama'" on a related website, UI, blog post, about page or product documentation. Notice (1.b.iii): "Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved." -> add both to README/UI. | LICENSE above |
| Section 2: licensees above 700 million monthly active users need a separate licence from Meta. Not relevant to us. | LICENSE above |
| Acceptable Use Policy: https://www.llama.com/llama3_2/use-policy (licence 1.b.iv). Relevant to us: the prohibition on "Generating, promoting, or furthering fraud or the creation or promotion of disinformation"; "Representing that the use of Llama 3.2 or outputs are human-generated" (so the UI must say answers are AI-generated); "Fail to appropriately disclose to end users any known dangers of your AI system" (so disclose hallucination risk). | https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md |
| EU clause (in the AUP, multimodal models only): rights under 1(a) are not granted to EU-domiciled individuals or companies "with respect to any multimodal models included in Llama 3.2"; "This restriction does not apply to end users...". **llama3.2:1b/3b are text-only, so it does not apply.** | USE_POLICY.md above; HF model card |
| HF card: 1B text model context length 128k; release Sept 25, 2024. | https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct |

### 4.1 Tool-call probe, llama3.2:1b (a probe, not a benchmark)

Measured 2026-10-14 on `ollama/ollama:0.40.0`, CPU only, `OLLAMA_CONTEXT_LENGTH=8192`. Source: `decisions.md`
("2026-10-14 — Group 3 smoke test", spec `2026-10-14-infra-and-corpus`).

| Observation | Result |
|---|---|
| Setup | One trivial tool, `get_weather(city)`; 5 requests. |
| Parseable tool call with correct name and city | 5 of 5. |
| Spurious extra argument | 1 of 5 (`properties: '{}'`). |
| Latency of a tool-call request (157 input tokens) | about 2.0-2.5 s warm, 5.0 s for the first call. |

This says nothing about several tools, tool choice among similar tools, multi-step loops or German
questions. Do not read it as evidence that tool use is reliable. **Requirement for Variant A:** model output
is untrusted, so the dispatcher must check the tool name against an allowlist and validate the arguments
against the tool's schema (reject unknown or extra arguments) before executing anything.

## 5. bge-m3 (embedding candidate)

| Fact | Source |
|---|---|
| Ollama: tags `bge-m3:567m` and `bge-m3:latest`, each 1.2GB; "embedding 567m"; "8K context window"; "more than 100 working languages". The page states no licence and no dimension. | https://ollama.com/library/bge-m3 |
| Model card: licence **MIT** (metadata `license: mit`); **dimension 1024**; inputs "up to 8192 tokens"; dense, sparse and multi-vector retrieval (Ollama serves dense embeddings via `/api/embed`). | https://huggingface.co/BAAI/bge-m3 |
| Similarity: the card does not prescribe a metric (its dense example uses a dot product). Using cosine (`<=>`, `vector_cosine_ops`) is our choice, not a documented requirement. Whether Ollama's `/api/embed` output is L2-normalised is **UNVERIFIED**. | same |
| Effective max input through Ollama is limited by `num_ctx` (default 4096, section 2.2), not 8192, unless raised. | section 2.2 sources |

## 6. Summary of UNVERIFIED items

1. ~~Live `prompt_eval_count` for `/api/embed`~~: settled for a single short input on 0.40.0 + bge-m3 (10 tokens, section 1.4). Only the multi-input (list) sum is not measured separately; the fallback in 1.4 stays for missing counts.
2. Whether chat `prompt_eval_count` excludes cached prompt-prefix tokens.
3. Whether Ollama-served bge-m3 vectors are L2-normalised.
4. Meta's llama.com licence page itself (redirects to a 404); the licence text came from Meta's GitHub repo and HF card.

---

# Corpus conversion and test set (spec `2026-10-14-testset`, task 1.1)

Verified on **2026-10-14**. Every row cites a URL or command output. **UNVERIFIED** marks what could not be
checked. Local introspection: scratch venv `venv-pypdf` (Python 3.12.15, `pip install --no-input pypdf==6.19.0`,
no other packages; pip list shows only `pip 25.0.1` and `pypdf 6.19.0`, so pypdf 6.19.0 has no runtime
dependencies for this use).

## 7. pypdf 6.20.1 (pinned version)

### 7.0 Verified on 6.20.1 (2026-10-14)

Scratch venv `venv-pypdf2` (Python 3.12.15, `pip install --no-input pypdf==6.20.1`; `pypdf.__version__` = `6.20.1`).

| Fact | Source |
|---|---|
| 6.20.1 upload time **2026-10-12T16:14:22Z** (wheel), 16:14:24Z (sdist). 6.19.0 upload time **2026-09-16T09:32:04Z** (wheel), 09:32:05Z (sdist). Both match the dates in decisions.md. | `curl -s https://pypi.org/pypi/pypdf/json` (`releases[<v>][*].upload_time_iso_8601`) |
| 6.20.1 is under 7 days old on 2026-10-14; it is used under the security-patch exemption (decisions.md, "pypdf pin moved from 6.19.0 to 6.20.1"). | `dependency-versions.md` |
| Only pip itself and pypdf are installed in the venv (`pip list`: `pip 25.0.1`, `pypdf 6.20.1`). | `pip list` |

Signatures (`inspect.signature()`, verbatim, pypdf 6.20.1, Python 3.12.15). Identical to the 6.19.0 output in 7.3:

```
pypdf.PdfReader.__init__
(self, stream: Union[str, IO[Any], pathlib.Path], strict: bool = False, password: Union[str, bytes, NoneType] = None, *, root_object_recovery_limit: Optional[int] = 10000) -> None

pypdf.PageObject.extract_text
(self, *args: Any, orientations: Union[int, tuple[int, ...]] = (0, 90, 180, 270), space_width: float = 200.0, visitor_operand_before: Optional[Callable[[Any, Any, Any, Any], NoneType]] = None, visitor_operand_after: Optional[Callable[[Any, Any, Any, Any], NoneType]] = None, visitor_text: Optional[Callable[[Any, Any, Any, Any, Any], NoneType]] = None, extraction_mode: Literal['plain', 'layout'] = 'plain', **kwargs: Any) -> str
```

Real-file run (read only, `python -I`, text not pasted): `PdfReader('data/raw/eea-ghg-trends-2024.pdf')` ->
**14 pages**, no hang or error. Extracted characters per page (`len(page.extract_text())`):
`[135, 1287, 3715, 1954, 2703, 1901, 3491, 4047, 3557, 2128, 3141, 1579, 1390, 879]`
(page 0 is 135 chars, as with 6.19.0; the 6.19.0 run in 7.4 also gave 14 pages and 135 for page 0; per-page lengths for the other pages were not recorded then, so equality of output across versions is **UNVERIFIED**).

The sections 7.1 to 7.4 below are the **6.19.0 findings, kept as history** (task 1.1, before the pin moved).

## 7-history. pypdf 6.19.0 (HISTORY: superseded by the 6.20.1 pin)

### 7.1 Release facts

| Fact | Source |
|---|---|
| 6.19.0 exists on PyPI; `requires_python >=3.9`; `yanked: False`, `yanked_reason: None`. Files: `pypdf-6.19.0-py3-none-any.whl` and `pypdf-6.19.0.tar.gz`, both `yanked: False`. | `curl -s https://pypi.org/pypi/pypdf/6.19.0/json` |
| Upload time **2026-09-16T09:32:04Z** (wheel), 09:32:05Z (sdist). That is 28 days before 2026-10-14 and before the 2026-10-07 cut-off, so the 7-day quarantine is met. | same |
| Neighbouring releases (upload, none yanked): 6.18.0 2026-09-07; 6.18.1 2026-09-11; **6.19.0 2026-09-16**; 6.20.0 2026-10-09; 6.20.1 2026-10-12. 6.20.0 and 6.20.1 are younger than 7 days on 2026-10-14. | `curl -s https://pypi.org/pypi/pypdf/json` (`releases[*].upload_time`) |
| PyPI's own `vulnerabilities` list is empty for 6.19.0 (and for the project). It does not list the GitHub advisories below. | PyPI JSON `vulnerabilities: []` |

### 7.2 Security advisories (GitHub, py-pdf/pypdf)

Source: `curl -s 'https://api.github.com/repos/py-pdf/pypdf/security-advisories?per_page=100'` and the advisory
pages `https://github.com/py-pdf/pypdf/security/advisories/<GHSA id>`, 2026-10-14. All pypdf advisories listed
are severity **medium** (resource exhaustion: infinite loop, long runtime or large memory use from crafted PDFs).

**Fixed in 6.19.0 (do not affect 6.19.0):** GHSA-php9-fj8v-98fj / CVE-2026-102998 (appearance streams),
GHSA-w23x-9jrw-r45c / CVE-2026-103000 (alphabetical page labels), GHSA-v247-6f48-mgcj / CVE-2026-102999
(embedded files); all `< 6.19.0`, published 2026-09-16. Earlier ones (6.18.1 and 6.18.0
fixes: GHSA-jw7q-gvrg-4vj3, GHSA-g9cg-prrw-2r8q, GHSA-fp3h-c4fm-7vvf, GHSA-5jq2-8x83-x246) are also below 6.19.0.

**Advisories whose vulnerable range includes 6.19.0 (fixed in a newer release):**

| GHSA | Vulnerable / patched | Published | Impact (advisory text) | Reached by our use? |
|---|---|---|---|---|
| GHSA-39mj-jf6j-2qj3 | `< 6.20.0` / `>= 6.20.0` | 2026-10-12 | Crafted PDF leads to an infinite loop; "requires an incomplete file which ends inside the xref table". No CVE id in the API. | Yes in principle: `PdfReader(path)` parses xref. Only for a truncated PDF. |
| GHSA-7mh2-4gg2-979f | `< 6.20.0` / `>= 6.20.0` | 2026-10-09 | Crafted PDF leads to large memory use; "requires accessing any stream with a large amount of filters or multiple filters". No CVE id. | Yes in principle: text extraction decodes content streams. |
| GHSA-qfv9-64jg-mh7p | `< 6.20.1` / `>= 6.20.1` | 2026-10-12 | Infinite loop; "requires calling `find_outline_item` on a `PdfWriter`". | No: we only read, and never call this. |
| GHSA-9mx8-4j7g-633p | `< 6.20.1` / `>= 6.20.1` | 2026-10-12 | Infinite loop; "requires removing an object from a tree, for example an outline item". | No: we only read. |

(History, written before the decision.) Facts only, no version choice made here. The plan's PDF input is a single known file from the tenant's
source list (`data/raw/eea-ghg-trends-2024.pdf`), not user-uploaded content; the two reader-relevant advisories
need malformed or hostile PDFs. The orchestrator decides (outcome: moved to 6.20.1, decisions.md) whether to keep 6.19.0 or move to 6.20.0/6.20.1
(security patches are exempt from the quarantine per `dependency-versions.md`; 6.20.1 is 2 days old on
2026-10-14). The 2026-10-14 pypdf run on the real EEA file in 7.3 succeeded with 6.19.0 (14 pages, no hang).
Not checked: the advisories' CVSS vectors (the API returned none) and the 6.20.x release notes.

### 7.3 Signatures (`inspect.signature()`, verbatim, pypdf 6.19.0, Python 3.12.15)

```
pypdf.PdfReader.__init__
(self, stream: Union[str, IO[Any], pathlib.Path], strict: bool = False, password: Union[str, bytes, NoneType] = None, *, root_object_recovery_limit: Optional[int] = 10000) -> None

pypdf.PageObject.extract_text
(self, *args: Any, orientations: Union[int, tuple[int, ...]] = (0, 90, 180, 270), space_width: float = 200.0, visitor_operand_before: Optional[Callable[[Any, Any, Any, Any], NoneType]] = None, visitor_operand_after: Optional[Callable[[Any, Any, Any, Any], NoneType]] = None, visitor_text: Optional[Callable[[Any, Any, Any, Any, Any], NoneType]] = None, extraction_mode: Literal['plain', 'layout'] = 'plain', **kwargs: Any) -> str

pypdf.PdfWriter.add_blank_page
(self, width: Optional[float] = None, height: Optional[float] = None) -> pypdf._page.PageObject

pypdf.PdfWriter.write
(self, stream: Union[pathlib.Path, str, IO[Any]]) -> tuple[bool, typing.IO[typing.Any]]
```

### 7.4 Verified usage (run in the scratch venv, `python -I`)

```python
import pypdf
w = pypdf.PdfWriter(); w.add_blank_page(200, 200); w.add_blank_page(200, 200); w.write("blank.pdf")
r = pypdf.PdfReader("blank.pdf")
print(type(r.pages).__name__, len(r.pages))              # _VirtualList 2
print([p.extract_text() for p in r.pages])               # ['', '']   (blank page -> empty string)
print(r.is_encrypted)                                    # False
```

| Fact | Source |
|---|---|
| Page list: `reader.pages` is a `_VirtualList` supporting `len()`, indexing and iteration; `reader.pages[i].extract_text()` returns `str`. | output above |
| A blank page gives `''` (not `None`), so a "chars per page" check can use `len(text)`. | output above |
| Real file check (read only, no fetch): `PdfReader('data/raw/eea-ghg-trends-2024.pdf')` -> 14 pages; page 0 text length 135; page 1 text begins `'Analysis and data Indicators Total net greenhouse gas emission tre…\nNet greenhouse gas (GHG) emissions fell by 31% in the EU-27 between 1990 and 2022,'`. Page 0 is short (135 chars): page chrome and truncated headline rather than body, so judge quality in task 2.1 from the whole file. | scratch venv run, 2026-10-14 |
| Encrypted PDFs: `password` parameter exists; `is_encrypted` is a `bool`. Behaviour on an encrypted file was not tested (UNVERIFIED); the one PDF is unencrypted. | signature; `is_encrypted` False |
| Layout-preserving extraction: `extraction_mode='layout'`. Not tested; `'plain'` is the default and is what the plan uses. | signature |

## 8. Python stdlib `html.parser.HTMLParser` (Python 3.12)

Source: https://docs.python.org/3.12/library/html.parser.html (fetched 2026-10-14) and a run on Python 3.12.15.

```
HTMLParser.__init__ (self, *, convert_charrefs=True, scripting=False)
```

| Hook / option | Documented behaviour | Source |
|---|---|---|
| `handle_starttag(tag, attrs)` | Called for a start tag. `tag` is lower-cased; `attrs` is a list of `(name, value)` pairs, names lower-cased, quotes removed, character and entity references in values replaced. | docs page |
| `handle_endtag(tag)` | Called for an end tag; `tag` lower-cased. The parser "does not check that end tags match start tags or call the end-tag handler for elements which are closed implicitly by closing an outer element." So the converter must keep its own depth counter and cannot rely on a matching end event. | docs page |
| `handle_startendtag(tag, attrs)` | For XHTML-style empty tags (`<img ... />`); default calls `handle_starttag` then `handle_endtag`. | docs page |
| `handle_data(data)` | Text nodes **and the content of `script` and `style`** elements. Skip these by tracking the current tag. | docs page |
| `convert_charrefs=True` (default since 3.5) | "all character references (except the ones in elements like script and style) are automatically converted"; `handle_entityref` / `handle_charref` are then not called. | docs page |
| `convert_charrefs=False` | `handle_entityref(name)` / `handle_charref(name)` are called instead and must be handled, else the references are lost. | docs page; run below |
| `scripting=False` (default; added in 3.12.13) | `noscript` content is parsed normally; `True` returns it as-is. | docs page ("Changed in version 3.12.13") |
| Not documented here | `handle_comment`, `handle_decl`, `handle_pi`, `unknown_decl`, `close()`, `reset()`; read the page if the converter needs them. | - |

Observed on Python 3.12.15 for `<div id="mw-content-text"><p>A &amp; B &#233;<br/>x</p><script>if(a<b){}</script><p>unclosed<td>c</div>`:

```
S div [('id', 'mw-content-text')]   S p []   D 'A & B é'   S br []   E br   D 'x'   E p
S script []   D 'if(a<b){}'   E script   S p []   D 'unclosed'   S td []   D 'c'   E div
```

- Entities arrive already converted inside one `handle_data` call (`'A & B é'`).
- `<br/>` produces both a start and an end event.
- Unclosed `<p>` and `<td>` get no end event; `</div>` closes the outer element only. Confirms the depth-counter advice.
- With `convert_charrefs=False`, `<p>A &amp; B</p>` gave `D 'A '`, `D ' B'` (the `&amp;` was dropped because no `handle_entityref` was defined). Keep the default `True`.

## 9. de.wikipedia article-body container

Checked on the downloaded pinned revisions (read-only; nothing fetched by this task):
`data/raw/dewiki-green-it.html` and `data/raw/dewiki-rechenzentrum.html`, 2026-10-14.

| Fact | Source |
|---|---|
| **VERIFIED:** each file has exactly one `id="mw-content-text"`, on `<div id="mw-content-text" class="mw-body-content">`. Its first child is `<div class="mw-content-ltr mw-parser-output" lang="de" dir="ltr" ...>` holding `<section data-mw-section-id="0" ...>`, i.e. the article text. | `grep -o 'id="mw-content-text"' file \| wc -l` -> 1 for both; text read around the match |
| Revision pins match the meta files: `dewiki-green-it` `wgRevisionId` 267912244 (`?oldid=267912244`), `dewiki-rechenzentrum` 271299132 (`?oldid=271299132`). Licence `CC BY-SA 4.0`, `redistributable: true` (meta.json of Green IT). | `"wgRevisionId"` in HTML; `data/raw/dewiki-*.meta.json` |
| Page chrome outside the body: `<div id="contentSub"`, `<div id="mw-content-subtitle"`, `id="catlinks"` and `class="printfooter"` all occur after (or around) the body container; `catlinks` and `printfooter` come after `mw-content-text` starts. The text between the container start and `id="catlinks"` has **0** `<nav` elements. | scan of both files |
| Inside the body, boxes exist (Rechenzentrum starts with `<div class="hintergrundfarbe1 rahmen ...`, a notice box). Whether such boxes, `<figure>` captions, reference lists and "Einzelnachweise" sections should be kept is a converter decision for 1.3/2.1, **not decided here**. | file read |
| Section count: 11 `<h2` (Green IT) and 15 (Rechenzentrum) in the whole page. Not split into in-body vs chrome. | `grep` counts |

Conclusion for 1.3: for sources with `id="mw-content-text"`, collect text only while inside that container
(depth-counted), and stop at its closing tag. Verified for these two files only; the other 10 sources
were not examined for their body containers (UNVERIFIED).

## 10. Summary of UNVERIFIED items (corpus conversion and test set)

1. Whether 6.20.0/6.20.1 change anything else relevant (release notes not read; signatures and the EEA run are verified on 6.20.1, section 7.0); CVSS vectors of the four open advisories (API returned none); CVE ids for GHSA-39mj / 7mh2 / qfv9 / 9mx8 (none in the API).
2. pypdf behaviour on an encrypted PDF; `extraction_mode='layout'` output.
3. Body containers of the non-Wikipedia sources (OWID, EEA, EC, UBA, Destatis).
4. Whether Wikipedia in-body boxes and reference lists should be kept (design decision).

---

# The assistant: structured output, digests, pgvector, full-text search, psycopg (spec `2026-10-14-assistant`, task 1.1)

Verified on **2026-10-15** against the running stack: `ollama/ollama:0.40.0` (CPU only, `OLLAMA_CONTEXT_LENGTH`
8192, see 17) with `llama3.2:1b` (digest `baf6a787...2878`) and `bge-m3:latest`; `pgvector/pgvector:0.8.7-pg17-trixie`
(PostgreSQL 17.11, `vector` extension 0.8.7); `.venv` with `ollama 0.6.3`, `psycopg 3.3.6`, `pgvector 0.5.0`.
Live results are **single observations** (small `llama3.2:1b`, `temperature=0`, `seed=1` unless stated); they
say nothing about other prompts, models or runs. Scripts were run from the session scratchpad; DB tests ran in
the schema `scratch_research` only (see 18 for its status).

## 11. Ollama structured outputs (`format`) in `ollama.Client.chat` 0.6.3

| Fact | Source |
|---|---|
| Signature (see 1.1): `format: Union[Literal['', 'json'], dict[str, Any], NoneType] = None`. A dict is a JSON schema; `'json'` is plain JSON mode. | `inspect.signature(ollama.Client.chat)` (section 1.1) |
| Docs: pass `format='json'` or a JSON schema (their example: `format=Country.model_json_schema()`), then read `response.message.content` (a string) and validate it, e.g. `Country.model_validate_json(...)`. The page says nothing about combining `format` with `tools`. | https://docs.ollama.com/capabilities/structured-outputs (fetched 2026-10-15) |
| Response is the usual `ChatResponse`; structured JSON arrives as a **string** in `message.content` (type observed: `str`); `message.tool_calls` was `None`. Token counts are the usual `prompt_eval_count` / `eval_count`. | live call below |

Schema used in all calls below:
`{"type":"object","properties":{"answer":{"type":"string"},"citations":{"type":"array","items":{"type":"string"}},"abstain":{"type":"boolean"}},"required":["answer","citations","abstain"]}`
System prompt: `Answer only from the sources. Cite source ids. Set abstain=true if the sources do not contain the answer.`
User message: a `<sources>` block with one `<source id="eea-ghg" title="EEA GHG trends" published="2024">` holding
`Net greenhouse gas emissions fell by 31% in the EU-27 between 1990 and 2022.`, then `Question: ...`.
Options `{"temperature":0,"seed":1}`.

### 11.1 One structured call (single observation)

Question: `By how much did EU-27 emissions fall between 1990 and 2022?`. Raw `message.content`:

```
{"answer": "31", "citations": ["<sources><source id=\"eea-ghg\" title=\"EEA GHG trends\" published=\"2024\">Net greenhouse gas emissions fell by 31% in the EU-27 between 1990 and 2022.</source>"], "abstain": false}
```

`prompt_eval_count=121`, `eval_count=69`, `done_reason=stop`. The first call after a model load took 17.0 s wall time.
**Observed:** the JSON is valid and has the three keys, but `citations` holds a copy of the whole source element
(markup included), **not the id `eea-ghg`**, and `answer` is just `"31"`. The schema constrains the shape, not
the meaning; `citations` values must be checked against the tenant's source ids (design: dropped and counted as
`invalid_citations`).

### 11.2 Three repetitions of the same call (single observation)

Same request, 3 more times: **3 of 3** parsed with `json.loads` and had exactly the keys `answer`, `citations`,
`abstain` with `abstain` a bool and `citations` a list. All three contents were byte-identical to 11.1
(`temperature=0`, fixed seed), `prompt_eval_count=121`, `eval_count=69` each. Total 4 of 4 valid across 11.1 and
11.2. This is not a validity rate; with identical outputs it is effectively one sample.

### 11.3 A question the sources cannot support (single observation)

Question: `What is the capital of Australia and who is its prime minister?` Raw content:

```
{"answer": "Canberra", "citations": ["<sources><source id='eea-ghg' title='EEA GHG trends' published='2024'>Net greenhouse gas emissions fell by 31% in the EU-27 between 1990 and 2022.</source></sources>"], "abstain": false}
```

`prompt_eval_count=116`, `eval_count=72`. **Observed:** the model answered from its own knowledge (and only half
of the question), cited a source that does not support it, and set `abstain=false`. In this one case `abstain`
was **not** filled sensibly. Do not rely on `abstain` from `llama3.2:1b` without measuring it (eval task).

### 11.4 `tools` and `format` in the same request (two single observations)

Tool: one function `search_sources(query: string)`. Same schema, system prompt and options.

| Request | Observed |
|---|---|
| Question answerable from the source text | Accepted (no error). `message.content` = a schema-valid JSON string (`answer "31"`, `abstain false`), `message.tool_calls = None`. `prompt_eval_count=240` (vs 121 without the tool; the tool definition is in the prompt), `eval_count=71`. |
| `Search the sources for data centre energy use.` | Accepted. `message.content = ''` and one **tool call**: `search_sources` with `arguments = {'answer': 'search_sources', 'citations': ['<sources>...'], 'abstain': True}`. `prompt_eval_count=231`, `eval_count=75`. |

**Observed:** the server accepts both parameters, but they interact badly: in the second case the model's tool
call had the **answer schema's keys as arguments** (`answer`, `citations`, `abstain`) instead of the tool's
`query`. So the format constraint shaped the tool-call arguments. Not tested: whether this is deterministic, or
whether other models behave the same. **Design consequence (observation, not a general rule):** do not send
`format` together with `tools`; use `tools` (no `format`) in the loop turns and `format` (no `tools`) on the
final call, as design.md already specifies ("forced final answer call without tools"). `validate_tool_call` must
reject such arguments anyway (extra properties).

## 12. Model digests: `list()`, `show()`, REST

`inspect.signature` (ollama 0.6.3): `Client.list(self) -> ListResponse`; `Client.show(self, model: str) -> ShowResponse`.
`ListResponse.Model.model_fields`: `model, modified_at, digest, size, details`.
`ShowResponse.model_fields`: `modified_at, template, modelfile, license, details, modelinfo, parameters, capabilities`
(**no `digest` field**).

Live output, `client.list().models` (digest shortened):

```
bge-m3:latest  digest=7907646426070047a77...  size=1157672605  details: format=gguf family=bert parameter_size=566.70M quantization_level=F16
llama3.2:1b    digest=baf6a787fdffd633537...  size=1321098329  details: format=gguf family=llama parameter_size=1.2B quantization_level=Q8_0
```

Full `llama3.2:1b` digest (from `/api/ps`, same value as in `list()`): `baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878`.

| Fact | Source |
|---|---|
| **Digest source: `client.list().models[i].digest`** (match on `.model`, the tag such as `llama3.2:1b`). `show()` does not carry it. | live output above; `model_fields` |
| `GET /api/tags` returned per model the keys `name, model, modified_at, size, digest, details, capabilities`. | `httpx.get('http://127.0.0.1:11434/api/tags')` |
| `POST /api/show {"model": ...}` returned the keys `thinking, license, modelfile, template, details, model_info, capabilities, modified_at` (**no digest**; python `modelinfo` = REST `model_info`). `show().capabilities` for `llama3.2:1b` = `['completion', 'tools']`. | live call |
| The `FROM` line of `show().modelfile` names a blob path `.../blobs/sha256-74701a8c...`; this is a file (layer) digest and was **not** equal to the `list()` digest `baf6a787...`. Use `list()` for the recorded model digest. | live output |
| `GET /api/ps` also lists loaded models with `digest`, `context_length` and `size_vram`. | live call (see 17) |
| Docs for `/api/tags`: "List models that are available locally" (section 2.1). | https://github.com/ollama/ollama/blob/main/docs/api.md |

## 13. Token counts: repeated identical request (closes UNVERIFIED item 2 of section 6, for one case)

Prompt: one user message of about 21,500 characters (400 German sentences, `Rechenzentrum Nummer i verbraucht Strom und Wasser.`)
plus `Fasse in einem Wort zusammen.`; options `temperature=0, seed=1, num_predict=8`. Single observation, identical
calls in a row:

| Call | `prompt_eval_count` | `eval_count` | `prompt_eval_duration` | `total_duration` |
|---|---|---|---|---|
| 1 (cold: model load plus prompt processing) | 6032 | 8 | 267706 ms | 270811 ms |
| 2 (identical) | 6032 | 8 | 366 ms | 3223 ms |
| 3 (identical) | 6032 | 8 | 440 ms | 3532 ms |
| 4 (same text, different last sentence) | 6030 | 8 | 3238 ms | not recorded |

**Observed:** `prompt_eval_count` was identical (6032) on the repeated request while the prompt evaluation time
fell by about 99.9 percent, so the server evidently re-used cached work, **but the count still covered the full
prompt**. For usage accounting, `prompt_eval_count` can be taken as the full input size in this case (not tested:
agentic multi-turn prefixes with tool messages, other versions). Call 1 took 268 s; the cause was not
investigated (cold model load plus CPU prompt processing; nothing isolated). Use a client `timeout` of several
minutes, or warm the model first.

## 14. pgvector 0.8.7 (HNSW, cosine), tested in schema `scratch_research`

Syntax and defaults: pgvector README, https://github.com/pgvector/pgvector/blob/master/README.md (already cited in
section 3: `CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops);`, `m` default 16, `ef_construction`
default 64, `hnsw.ef_search` default 40, `<=>` cosine distance, 2,000 dimension limit for indexes). Live checks
(1024-dim random Gaussian vectors, 200 rows):

| Check | Observed |
|---|---|
| Create | `CREATE INDEX c_hnsw ON c USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)` succeeded; `pg_indexes.indexdef` = `... USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')`. |
| `hnsw.ef_search` | `SHOW hnsw.ef_search` = `40` (default); `SET hnsw.ef_search = 100` then `SHOW` = `100`. A session setting: set it on the connection used for queries. |
| Ordering | `SELECT id, embedding <=> %s AS d ... ORDER BY embedding <=> %s LIMIT 3` for stored vector 7 returned `[(7, 0.0), (136, 0.9217...), (66, 0.9372...)]`; a Python cosine-distance computation gave the same top 3 ids `[7, 136, 66]`. Lower = more similar; `<=>` is cosine **distance** (1 - similarity). |
| Planner on 200 rows | `EXPLAIN` chose `Sort` over a sequential scan by default; with `SET enable_seqscan=off` it showed `Index Scan using c_hnsw` with `Order By: (embedding <=> ...)`. Tiny tables will not use the index; this is normal planner behaviour. |
| Dimensions | `vector(1024)` HNSW: ok. `vector(2000)` HNSW: ok. `vector(2001)`: `ProgramLimitExceeded: column cannot have more than 2000 dimensions for hnsw index`. 1024 fits. |
| Pass a Python list | `SELECT %s::vector <=> %s::vector` with plain lists failed: `CannotCoerce: cannot cast type smallint[] to vector`. Wrap with `pgvector.Vector`. |
| Loaded value | Selecting `embedding` returns `pgvector.Vector` (after `register_vector`); `.to_list()` has 1024 floats. |

The index is approximate: the observed top 3 equal the exact top 3 only for this tiny example. Recall on the real
corpus is not measured.

## 15. PostgreSQL 17 full-text search for Variant A

Docs: https://www.postgresql.org/docs/17/textsearch-controls.html and
https://www.postgresql.org/docs/17/textsearch-limitations.html (both fetched 2026-10-15).

| Fact | Source |
|---|---|
| `ts_headline` options (comma-separated `name=value`, case-insensitive): `MaxWords` (default 35), `MinWords` (15), `ShortWord` (3), `HighlightAll` (false), `MaxFragments` (0), `StartSel` / `StopSel` (`<b>`, `</b>`), `FragmentDelimiter` (` ... `). Values with spaces or commas need double quotes. | textsearch-controls |
| `ts_headline` works on the **original text, not the tsvector**; the docs warn it "can be slow and should be used with care". With `HighlightAll=false` only some simple XML tags are removed, so untrusted text can pass HTML through. If no match is found, a fragment of the first `MinWords` words is shown. | textsearch-controls |
| `plainto_tsquery([config,] text)` parses like `to_tsvector` and joins surviving words with `&` (AND). It ignores operators and never raises a syntax error, so it suits raw user input. | textsearch-controls |
| `ts_rank` ignores document length by default (normalisation `0`); ranking "can be expensive". Weights default `{0.1, 0.2, 0.4, 1.0}`. | textsearch-controls |
| Limits: `tsvector` (lexemes + positions) < 1 MB; lexeme < 2 KB; positions <= 16,383, at most 256 positions per lexeme. | textsearch-limitations |

Live tests (PostgreSQL 17.11, scratch schema):

```
CREATE TABLE docs (id text primary key, text text,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED);
CREATE INDEX docs_tsv ON docs USING gin (tsv);
```

Both statements worked as written; inserting a row fills `tsv` automatically (95,039-character text gives a
`tsv::text` of 86,140 characters).

| Check | Observed (single run) |
|---|---|
| `plainto_tsquery('simple', ...)` | `Rechenzentren Strom` gives `'rechenzentren' & 'strom'` (lower-cased, AND). `Rechenzentrum OR Strom` gives `'rechenzentrum' & 'or' & 'strom'`: **`OR` is a word, not an operator**. A multi-word model query needs **all** words in a document (`rechenzentrum hamburg` matched 1 of 3 test rows). |
| `ts_rank(tsv, query)` | The row matching the AND query scored `0.0915`; non-matching rows scored `1e-20`. Rank only rows selected with `tsv @@ query`. |
| **No stemming in `'simple'`** (single observation; row `a` = `Die Rechenzentren in Hamburg nutzen Abwärme. Ein Rechenzentrum braucht Kühlung.`; row `big` = ~95k characters containing only `Rechenzentrum`) | Query `Rechenzentrum` matched `a` and `big`; query `Rechenzentren` matched only `a`. An inflected form misses every document that has only the other form. Variant A cannot reach `big` with `Rechenzentren`. The tool description should tell the model to try singular and plural, or the design accepts the limit (it matters for the A-vs-B comparison). |
| `ts_headline('simple', text, query, 'MaxWords=30, MinWords=10, StartSel=<<, StopSel=>>')`, short row | `Die Rechenzentren in Hamburg nutzen Abwärme. Ein <<Rechenzentrum>> braucht Kühlung` (options applied; default options give `<b>..</b>`). |
| `ts_headline` on the 95,039-character text | Snippet of 89 characters at the match (with the options above), **20 ms**; a match at ~char 40k: 19 ms. No error. |
| `ts_headline` on a **143,409**-character text (> 100k), only match in the last 10 characters | Returned `w496 w497 w498 w499 <<ENDMARKER>>` in **57 ms**. In this test there was **no 100k truncation or error**. Larger texts, other queries and the real corpus were not tested. |
| `ts_rank` + `@@` over 3 rows | 1 ms (tiny table; no timing claim for the real corpus). |

## 16. psycopg 3.3.6 + pgvector-python 0.5.0 patterns (all run in the scratch schema)

| Pattern | Verified result |
|---|---|
| numpy | **Not installed** in `.venv` (`import numpy` -> `ModuleNotFoundError`); `pgvector 0.5.0` declares no dependencies. Pass `Vector(list_of_floats)`; do not rely on `numpy.ndarray`. |
| `register_vector(conn)` | Called after the extension existed; `Vector(list)` parameters and `Vector` results worked. A plain `list` is not accepted as `vector` (14). Register on every connection. |
| `cursor.executemany` | `with conn.cursor() as cur: cur.executemany("INSERT INTO c (id,tag,embedding) VALUES (%s,%s,%s)", rows)` inserted 200 rows (`cur.rowcount == 200`; rows were `(int, str, Vector)`). It was used on the cursor, not on the connection. |
| Upsert | `INSERT ... ON CONFLICT (id) DO UPDATE SET tag=EXCLUDED.tag, embedding=EXCLUDED.embedding` replaced row `id=0` (`tag` = `new`); row count stayed 200. |
| Transactions | With `autocommit=False`: `with conn.transaction(): ...; raise RuntimeError` rolled the insert back (count 0 afterwards); a block that finished normally committed it (count 1). DDL ran on an `autocommit=True` connection in the test. |
| Search path | `conn.execute("SET search_path = scratch_research, public")` isolated the tests. |
| Generated column | `tsv` is not written by INSERT; the insert lists only `(id, text)`. |
| Secrets | `DATABASE_URL` comes from the environment (`.env`, gitignored); never print it. |

Sources: pgvector-python README https://github.com/pgvector/pgvector-python/blob/master/README.md (section 3) and the live runs above.
**UNVERIFIED:** psycopg's internal batching/pipelining behaviour of `executemany` (only the result was observed, not the wire behaviour or its speed); `ConnectionPool` use.

## 17. Context length and a ~7000-token prompt

| Fact | Observed |
|---|---|
| Server-side context | `GET /api/ps` for the loaded `llama3.2:1b`: `"context_length": 8192`, `"size_vram": 0` (CPU), `"runner": "llamacpp"`. The running model uses 8192 (compose sets `OLLAMA_CONTEXT_LENGTH=8192`; the 4096 default of section 2.2 does not apply here). |
| ~7000-token prompt (single observation) | German filler of 24,945 characters plus a short instruction: `prompt_eval_count=6992`, `eval_count=8` (`num_predict=8`, so `done_reason=length` is expected). 6992 matches the expected size (6032 tokens for 21,489 characters in the calibration call, scaled), so the count covers the **full prompt**; it does not by itself prove nothing was dropped. 45 s wall time with the model already loaded. |
| Retrieval of an early fact | The same prompt with `Das Geheimwort ist KORMORAN-4711.` at the very start plus a question for it returned `'Nichts.'` (wrong); `prompt_eval_count=7017`. Truncation of the start could therefore **not** be ruled out or shown with this probe: the 1B model failed the lookup anyway. |
| Budget | Current design value: **3000 tokens** of retrieved text plus prompt overhead, well below 8192. The first design used 6000; it was lowered because cold prefill ran at about 22 tokens/s on this CPU (268 s for about 6000 tokens, one observation; decisions.md 2026-10-15). |

## 18. Status of the scratch schema and open items

- Schema `scratch_research` (tables `c`, `d2000`, `d2001`, `docs`) was created in the live database. Its cleanup (the
  cascading schema drop) was **blocked by the session's destructive-SQL guard hook** and needs the user's
  explicit approval; **at the time of writing the schema still exists.** Nothing outside it was touched.
- UNVERIFIED: whether chat `prompt_eval_count` behaves the same in an agentic multi-turn prefix; whether
  `tools` + `format` always misbehaves as in 11.4; psycopg executemany pipelining (16); `ts_headline` speed on
  real-corpus documents; HNSW recall on the real corpus; whether bge-m3 vectors are L2-normalised (section 6
  item 3, not examined); actual truncation behaviour above `num_ctx` (17).

## 19. Office and ODF parts and elements read by the stdlib extractor (task 7.1)

Verified on **2026-10-16** (spec `2026-10-14-assistant`, Group 7, task 7.1; contracts.md "Addendum: Filesystem crawler").
Python 3.12.15 (`.venv/bin/python`), standard library only. Hand-written minimal samples (no external library):
`/tmp/claude-1000/-workspaces-ngo-assistant/b869d625-7650-4a8a-8589-06b9a154f3d3/scratchpad/office-samples/`
(`sample.docx`, `sample.pptx`, `sample.xlsx`, `sample.odt`, `sample.ods`), generator
`.../scratchpad/make_samples.py`, check script `.../scratchpad/check_samples.py` (both in the scratchpad above; run with
`.venv/bin/python -I make_samples.py <outdir>` and `-I check_samples.py <outdir>`). The output below comes from that check.

### 19.1 Namespaces (exact URIs)

| Prefix | URI | Source |
|---|---|---|
| `w:` (WordprocessingML) | `http://schemas.openxmlformats.org/wordprocessingml/2006/main` | used in the working samples; the element pages below name the `w:` prefix. URI itself: UNVERIFIED against the ECMA text (taken from the known transitional namespace; ElementTree found all elements with it, so it is at least self-consistent) |
| `a:` (DrawingML) | `http://schemas.openxmlformats.org/drawingml/2006/main` | same remark |
| `p:` (PresentationML) | `http://schemas.openxmlformats.org/presentationml/2006/main` | same remark |
| main SpreadsheetML (default ns, Learn prints prefix `x:`) | `http://schemas.openxmlformats.org/spreadsheetml/2006/main` | same remark |
| `r:` (relationships attr, e.g. `r:id` on `sheet`) | `http://schemas.openxmlformats.org/officeDocument/2006/relationships` | Learn `Sheet` page: "id (Relationship Id) Namespace: .../officeDocument/2006/relationships" https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.sheet?view=openxml-3.0.1 |
| package relationships | `http://schemas.openxmlformats.org/package/2006/relationships` | UNVERIFIED (from memory, only used in the sample `.rels` files) |
| ODF `office:` | `urn:oasis:names:tc:opendocument:xmlns:office:1.0` | OASIS ODF 1.3 part 3, "Declared XML namespaces" https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html |
| ODF `text:` | `urn:oasis:names:tc:opendocument:xmlns:text:1.0` | same |
| ODF `table:` | `urn:oasis:names:tc:opendocument:xmlns:table:1.0` | same |

Use ElementTree Clark notation (`{uri}local`); never match on the prefix, it is arbitrary per file.
The "Learn" pages quote ISO/IEC 29500-1 1st edition text ("[ISO/IEC 29500-1 1st Edition]"); the section numbers below are from them.
ECMA-376 / ISO 29500 themselves were not opened directly (**UNVERIFIED** at primary-document level; the Microsoft Learn
Open XML SDK reference reproduces the ISO text).

### 19.2 docx (`word/document.xml`)

| Element | Fact | Source (all fetched 2026-10-16) |
|---|---|---|
| `w:p` | paragraph; text is in `w:r/w:t` descendants | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraph?view=openxml-3.0.1 (qualified name `w:p`) |
| `w:t` | "literal text which shall be displayed in the document"; parent `w:r`. Leading/trailing spaces need `xml:space="preserve"` in files written by Word; ET returns the text as written either way (sample: `'Hello '`). The `xml:space` attribute itself is **UNVERIFIED** on the Learn page (not in the fetched text) | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.text?view=openxml-3.0.1 |
| `w:tab` | "a tab character shall be placed at the current location in the run content" (leaf child of `w:r`) | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tabchar?view=openxml-3.0.1 |
| `w:br` | a break at the current location; has a `w:type` attribute (page, column, textWrapping). Which values exist and the default were **UNVERIFIED** (the page text I fetched shows only "Type: Break Type, w:type"); treat every `w:br` as a newline, ignore the type | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.break?view=openxml-3.0.1 |
| `w:tbl` / `w:tr` / `w:tc` | table / row / cell; each `w:tc` contains `w:p` paragraphs. Observed in the sample: `.//w:tbl/w:tr` found 1 row, `.//w:tc` found 2 cells, and a plain `iter(w:p)` also returns the cell paragraphs (A1, B1) as separate paragraphs, so the extractor must handle `w:tbl` before generic paragraph iteration or it will duplicate/misplace table text. `w:tbl` page: https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.table?view=openxml-3.0.1 (qualified name `w:tbl`); `w:tr`/`w:tc` names are from the working sample (**UNVERIFIED** on a Learn page) |
| `w:pPr/w:pStyle` (`w:val`) | "specifies the style ID of the paragraph style ... applied"; matches `w:styleId` of a `w:style` in `styles.xml` (§17.7.4.17); "If this element is omitted, or it references a style which does not exist, then no paragraph style shall be applied" | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraphstyleid?view=openxml-3.0.1 |
| `w:style/w:name` (`w:val`) | "primary name for the current style ... can be used in an application's user interface"; parent `w:style` (§17.7.4.17). The page's own example uses a custom name (`GD20Complex`) | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.stylename?view=openxml-3.0.1 |

Observed with ElementTree on `sample.docx`:
```
docx p Heading1 ['Title one']
docx p berschrift2 ['German style']
docx p None ['Hello ', 'tabbed', 'after break'] tab br
docx p None ['A1']        (inside w:tbl)
docx tbl rows 1 cells 2
style Heading1 heading 1 / style berschrift2 heading 2     (styleId -> w:name map built from styles.xml)
```
Reusable snippet for the test writer (namespace `W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"`):
`st = p.find(f"{W}pPr/{W}pStyle"); st.get(W+"val")`; `[t.text for t in p.iter(W+"t")]`; `p.find(f".//{W}tab")`.

**Heading style names and localisation (what was and was not verified).**
- Verified: `w:pStyle/@w:val` is a style **ID** (matches `w:style/@w:styleId`), not a display name; `w:name` is the display name. So `startswith("Heading")` on the pStyle value only works for English-created documents whose style IDs are `Heading1`...
- **UNVERIFIED (no primary source, no German Word file available here):** that Word writes the localised German heading style with `styleId` `berschrift1` (umlaut dropped) and `w:name` `Überschrift 1`, and that the English name `heading 1` lives only in Word's latent styles (not in the file). Evidence found is secondary/anecdotal: a docx4java forum post shows a German document whose heading style appears as `berschrift` (https://www.docx4java.org/forums/docx-java-f6/recognizing-headings-t1268.html); a LibreOffice bug report states Word maps localised names back to standard styles through "latent styles", "an underlying model that is not in the docx/xml file" (https://bugs.libreoffice.org/show_bug.cgi?id=115856); German vendor/forum posts confirm the display name "Überschrift 1" (https://community.adobe.com/t5/robohelp-discussions/quot-%C3%BCberschrift-1-quot-not-recognized-when-importing-word-document/td-p/10831644).
- Consequence for the contract (`Heading`/`Titel`/`Title` prefixes on the pStyle value): it will miss localised headings; this is the documented known limitation. A cheap improvement that stays within the verified facts: build a `styleId -> w:name/@w:val` map from `word/styles.xml` (as in the sample) and treat a paragraph as heading when either the styleId or the style name, compared case-insensitively with spaces removed, starts with `heading`, `title`, `titel` or `berschrift`/`überschrift`. Whether Word-generated files in other languages use `w:name="heading 1"` is **UNVERIFIED**; if `styles.xml` is missing or unparsable, fall back to the pStyle value only. `w:outlineLvl` (paragraph outline level) is a further language-independent signal but was **not** researched.

### 19.3 pptx (`ppt/slides/slideN.xml`, `ppt/notesSlides/notesSlideN.xml`)

| Item | Fact | Source |
|---|---|---|
| `a:t` | "the actual text for this text run"; parents are `a:r` (run) or `a:fld` (field) (page lists "Parent Elements fld; r") | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.text?view=openxml-3.0.1 |
| `a:p` | text paragraph (DrawingML), qualified name `a:p`; used inside `p:txBody` (and `a:txBody` in table cells, **UNVERIFIED**) | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.paragraph?view=openxml-3.0.1 |
| `p:sld` | root element of a slide part | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.presentation.slide?view=openxml-3.0.1 |
| `p:notes` | root of a notes slide part ("existence of a notes slide along with its corresponding data"; common slide data in `p:cSld`) | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.presentation.notesslide?view=openxml-3.0.1 |
| slide order | Numeric order of `slideN.xml` is **not** necessarily presentation order (real order is `p:sldIdLst` in `ppt/presentation.xml` via its relationships). The contract says "numeric order"; that is a simplification, **UNVERIFIED** against the spec; sample sorts by number (1, 2, 10, not lexicographic 1, 10, 2) | verified only on the sample |
| notes linkage | A slide's notes are found through `ppt/slides/_rels/slideN.xml.rels` (relationship type ending in `/notesSlide`, `Target="../notesSlides/notesSlideM.xml"`); the number M need not equal N. Relationship type URI **UNVERIFIED** (written from memory in the sample) | sample only |
| notes text | In real notes slides the text of all placeholders (incl. slide image / slide number placeholders) lies under `p:cSld`; only `a:t` text is read, so slide numbers may show up as extra text (not tested with a real file; **UNVERIFIED**) | - |

Observed on `sample.pptx`: order `slide1, slide2, slide10`; `a:t` texts `['First']`, `['Second']`, `['Tenth']`; notes `['speaker note']`; slide1 rels Target `../notesSlides/notesSlide1.xml`.
Not covered by the sample (decide in 7.4): `a:br` (line break), tables in `p:graphicFrame` (`a:tbl/a:tr/a:tc/a:txBody/a:p`, **UNVERIFIED**), grouped shapes, hidden slides.

### 19.4 xlsx

| Part / element | Fact | Source |
|---|---|---|
| `xl/workbook.xml` `sheets/sheet` | `name` = sheet name (required, unique); `r:id` = "identifier of the sheet part where the definition for this sheet is stored" (required); `sheetId` internal id | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.sheet?view=openxml-3.0.1 |
| `xl/_rels/workbook.xml.rels` | maps `r:id` -> worksheet part (`Target="worksheets/sheet1.xml"`, relative to `xl/`; may also be absolute `/xl/worksheets/...`: **UNVERIFIED**). Sheet **order** = order of `sheet` elements in `workbook.xml` (not the number in `sheetN.xml`); the extractor must resolve `r:id` through the rels part (sample does) | sample; ordering rule UNVERIFIED in spec text |
| `xl/sharedStrings.xml` | root `sst` (optional `count`, `uniqueCount`); children `si` (String Item, §18.4.8). A `si` contains `t` directly or rich-text runs `r/t`; the extractor must concatenate **all** `t` descendants of `si`, skipping phonetic `rPh` text (`rPh` handling **UNVERIFIED**) | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.sharedstringtable?view=openxml-3.0.1 |
| `c` (cell) | attributes `r` (A1 reference), `s` (style index), `t` (data type, `ST_CellType` §18.18.11); children `f`, `v`, `is`. "when the cell's type t is inlineStr then only the element `is` is allowed as a child" | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.cell?view=openxml-3.0.1 |
| `v` | "If the cell contains a string, then this value is an index into the shared string table ... Otherwise, the value of the cell is expressed directly in this element. Cells containing formulas express the last calculated result of the formula in this element." | https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.cellvalue?view=openxml-3.0.1 |

`t` values (Learn `CellValues`, https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.cellvalues?view=openxml-3.0.1):

| `t` | Meaning | Extractor rule (proposal) | Observed in sample |
|---|---|---|---|
| `s` | Shared String: `<v>` is the index into `sst/si` | look up; index out of range -> `ExtractError` or skip (decide in 7.4) | `A1 t=s v=0` -> `shared text` |
| `inlineStr` | Inline String: text in `<is><t>` (no `<v>`) | concatenate `is//t` | `B1` -> `inline` |
| `str` | String (formula result): text in `<v>` | `<v>` text (cached value; do not read `<f>`) | `C1` -> `cached formula str` (formula `A1&"x"` ignored) |
| `b` | Boolean, `<v>` `0`/`1` | `TRUE`/`FALSE` or skip | `D1 v=1` |
| `n` or absent | Number: `<v>` is a number | use the cached text as is | `E1 v=42.5` |
| `e` | Error, `<v>` e.g. `#DIV/0!` | skip (or text) | `G1 v=#DIV/0!` |
| `d` | ISO 8601 date in `<v>` (Office 2010+ per Learn; example `1976-11-22T08:30Z`) | use text | not in sample |

A date is normally **not** `t="d"`: it is a number (serial, e.g. `45000`) whose date meaning comes only from `s` -> `cellXfs` number format in `xl/styles.xml`. Observed: `F1 s=1 v=45000` is just a number to ElementTree. Decision proposal: emit the cached number text; do not parse `styles.xml` (a serial like 45000 in the output is acceptable for retrieval). That date formats are only in `styles.xml` is **UNVERIFIED** against the ISO text (known from general practice).

Cell cap: the contract's 20000 cells per workbook is a count of `c` elements visited. Rows/columns can also be sparse (`r="XFD1048576"`); only iterate `c` elements, never expand ranges. Large `dimension` values do not matter then.

### 19.5 ODF (`content.xml` of odt/ods/odp)

| Element / attribute | Fact (ODF 1.3 part 3, https://docs.oasis-open.org/office/OpenDocument/v1.3/os/part3-schema/OpenDocument-v1.3-os-part3-schema.html, fetched 2026-10-16) |
|---|---|
| `text:h` (§5.1.2) | "represents a heading in a document"; contains text, `text:span`, `text:s`, `text:tab`, `text:line-break` etc. Attribute `text:outline-level` (§19.850.4 for `text:h`): the section shows its use on headings; the level value semantics (positive integer, default) were **UNVERIFIED** in the text I read; use the attribute only for deciding `# ` depth, default to level 1 |
| `text:p` (§5.1.3) | paragraph |
| `text:s` (§6.1.3) | `text:c` "specifies the number of space characters (U+0020) that a `text:s` element represents. A missing `text:c` attribute is interpreted as a single space"; data type nonNegativeInteger |
| `text:tab` (§6.1.4) | "represents the Unicode tab character (U+0009)" |
| `text:line-break` (§6.1.5) | "represents a line break" |
| `table:table-row` (§9.1.3) | attribute `table:number-rows-repeated` (§19.681): "the number of rows to which a row element applies ... may be described by a single `table:table-row` element that has `table:number-rows-repeated` with a value greater than 1"; data type positiveInteger (no upper bound in the schema) |
| `table:table-cell` (§9.1.4) | attribute `table:number-columns-repeated` (§19.679.3): "the number of successive columns in which a cell is repeated"; positiveInteger; `table:covered-table-cell` (§9.1.5) is the cell covered by a span (default 1) |

Important ElementTree behaviour (observed in `sample.odt`): text inside a paragraph is split into `.text` and the **`.tail`** of children. `<text:p>Para <text:s text:c="2"/>with<text:tab/>tab<text:line-break/>next</text:p>` gives `p.text == "Para "`, children `s` (attr `text:c=2`), `tab`, `line-break`; the words `with`, `tab`, `next` are the `.tail` values of those children. Use `"".join(e.itertext())` for plain text, but then `text:s`, `text:tab` and `text:line-break` contribute nothing: handle them by walking the tree explicitly (`.text`, per child map `s` -> `" " * int(attr or 1)`, `tab` -> `\t`, `line-break` -> `\n`, recurse for `text:span`/`text:a`, then `.tail`).

**Memory explosion with repeated cells/rows** (demonstrated): `sample.ods` has one row with `table:number-rows-repeated="3"` containing a cell with text and an empty cell with `table:number-columns-repeated="1000000"`; the file is 466 bytes. Real spreadsheets written by LibreOffice use this for trailing empty cells/rows (a typical value is 1024 columns / ~1,048,576 rows; **UNVERIFIED** here, from general experience). Rules for the extractor: never materialise a repeated cell or row; for an **empty** cell (no `text:p`) skip it entirely (do not count it); for a **non-empty** cell/row emit it at most `min(n, REPEAT_CAP)` times, with a cap such as 10 (or count each repetition against the 20000-cell budget); parse `int()` defensively (non-numeric or `<= 0` -> `ExtractError`); also clamp huge numbers before multiplying. Cells in `odp` are in `draw:` frames; for `.odp` only `text:p`/`text:h` descendants are read (page structure `draw:page` not researched, **UNVERIFIED**).

Observed (`sample.odt` / `sample.ods`): `odt h [('1', 'Heading')]`; `row repeat 3 [None, '1000000']`.

Ordering and `mimetype`: ODF packages start with an uncompressed `mimetype` member (as in the samples); the extractor can ignore it, but must not trust it for the extension decision (use the file extension from the crawler). Spec text for the package layout was **not** fetched (**UNVERIFIED**).

## 20. Python 3.12 `zipfile`, `xml.etree.ElementTree` and expat (task 7.1)

Verified on **2026-10-16**. `.venv/bin/python` = Python 3.12.15; `pyexpat.EXPAT_VERSION` = `expat_2.8.5` (`pyexpat.version_info` = `(2, 8, 5)`).

### 20.1 `zipfile`

| Fact | Source / observation |
|---|---|
| Warning: "Never extract archives from untrusted sources without prior inspection. It is possible that files are created outside of path, e.g. members that have absolute filenames starting with "/" or filenames with two dots "..". This module attempts to prevent that." (about `extractall`). The extractor never extracts to disk (uses `ZipFile.read`/`open` on named parts only), so path traversal does not apply, but part names are still looked up by exact string. `zipfile.Path` "does not sanitize filenames" and is not used | https://docs.python.org/3.12/library/zipfile.html (fetched 2026-10-16) |
| Zip bombs: "decompression bombs (aka ZIP bomb) apply to zipfile library that can cause disk volume exhaustion"; **no built-in size or ratio limit is documented** | same page |
| `ZipInfo.file_size` "Size of the uncompressed file", `ZipInfo.compress_size` "Size of the compressed data", `ZipInfo.flag_bits` "ZIP flag bits" (no more detail in the docs) | same page. Observed on `sample.docx` member `word/document.xml`: `file_size=610`, `compress_size=286`, `flag_bits=0`. Slots of `ZipInfo` (3.12.15): `filename, date_time, compress_type, comment, extra, create_system, create_version, extract_version, reserved, flag_bits, volume, internal_attr, external_attr, header_offset, CRC, compress_size, file_size, ...` |
| Encrypted members: decryption is supported ("`pwd`"), "Decryption is extremely slow as it is implemented in native Python". Encrypted flag = bit 0 of `flag_bits`. Observed: with bit 0 set in the headers, `ZipInfo.flag_bits & 1 == 1` and `ZipFile.read(name)` raises `RuntimeError: File 'a' is encrypted, password required for extraction` (not `BadZipFile`). The extractor must check `flag_bits & 0x1` for every member it will read (and ideally all members) and raise `ExtractError("encrypted archive")`, and also catch `RuntimeError` | observed (the docs do not name this exception); the bit meaning (general ZIP appnote) is **UNVERIFIED** against PKWARE APPNOTE |
| Declared size is attacker-controlled but the reader is bounded by it: a real 100000-byte deflate member whose central-directory `file_size` was edited to 10 made `ZipFile.read` raise `BadZipFile: Bad CRC-32 for file 'a'` after 10 bytes (the reader stops at the declared size, then the CRC check fails). So `file_size` is an upper bound on what `read()` returns, and a lying header cannot make `read()` exceed it. The Python docs state **no** such protection (docs page section "no documentation of this"), so this is an observation of 3.12.15 only; re-test on a version change | observed |
| Honest bomb ratio: 50,000,000 NUL bytes deflate to `compress_size=48604`, `file_size=50000000`: ratio **1028**. The contract limit `max_ratio=200` (per member `file_size / max(compress_size, 1)`) catches this; `max_member_bytes=52428800` (50 MiB) would not (50,000,000 < 52,428,800), so the ratio check is the one that matters. Check `file_size` and ratio from `infolist()` **before** any `read`, sum `file_size` over all members for `max_total_uncompressed`, and still read with a bounded loop (`ZipFile.open(...).read(n)`) as defence in depth | observed |
| Duplicate member names: writing the same name twice gives `UserWarning: Duplicate name: 'a'`; reading returns the **last** one (`b'2'`), `infolist()` lists both. A crafted file could show different content to different tools; reject archives with duplicate names (`ExtractError`) | observed |
| Not a zip: `zipfile.ZipFile(BytesIO(b"not a zip"))` raises `zipfile.BadZipFile`. Other errors to map to `ExtractError`: `BadZipFile` (corrupt, bad CRC), `RuntimeError` (encrypted), `NotImplementedError` (unsupported compression method, **UNVERIFIED** here), `zlib.error`, `EOFError`, `KeyError` (missing part), `OSError` | observed / partly UNVERIFIED |

### 20.2 `xml.etree.ElementTree` and expat

Official table (https://docs.python.org/3.12/library/xml.html, "XML security", fetched 2026-10-16), column `etree`:

| kind | etree | footnote |
|---|---|---|
| billion laughs | **Vulnerable** (1) | "Expat 2.4.1 and newer is not vulnerable to the 'billion laughs' and 'quadratic blowup' vulnerabilities. Items still listed as vulnerable due to potential reliance on system-provided libraries. Check `pyexpat.EXPAT_VERSION`." |
| quadratic blowup | **Vulnerable** (1) | same |
| external entity expansion | Safe (2) | "`xml.etree.ElementTree` doesn't expand external entities and raises a `ParseError` when an entity occurs." |
| DTD retrieval | Safe | |
| decompression bomb | Safe | |
| large tokens | **Vulnerable** (6) | "Expat 2.6.0 and newer is not vulnerable to denial of service through quadratic runtime caused by parsing large tokens. Items still listed as vulnerable due to potential reliance on system-provided libraries. Check `pyexpat.EXPAT_VERSION`." |

(The table has no `pyexpat` column; it covers sax, etree, minidom, pulldom, xmlrpc.)

Expat release note, https://github.com/libexpat/libexpat/blob/master/expat/Changes (raw file fetched 2026-10-16): "Release 2.4.0 Sun May 23 2021 / Security fixes: #34 #466 #484 CVE-2013-0340/CWE-776 -- Protect against billion laughs attacks (denial-of-service; flavors targeting CPU time or RAM or both, leveraging general entities or parameter entities or both) by tracking and limiting the input amplification factor ... By conservative default, amplification up to a factor of 100.0 is tolerated and rejection only starts after 8 MiB of output bytes ... have been processed." Python's footnote says 2.4.1 and newer (2.4.1 is a bug-fix release on the same date). The venv's `expat_2.8.5` (release 2.8.5, 22 September 2026 per the same file) is therefore newer than both thresholds (2.4.1 for billion laughs, 2.6.0 for large tokens). The file's top entry at fetch time is 2.9.0 (5 October 2026); `libexpat` 2.6.2 additionally fixed CVE-2024-28757 (billion laughs with isolated external parsers).

Live checks in the venv (expat 2.8.5):
- A ten-level nested-entity bomb (each level 10 references to the previous, `<l>&j;</l>`) raised `xml.etree.ElementTree.ParseError: limit on input amplification factor (from DTD and entities) breached: line 1, column 459`. The protection is active; the extractor maps `ParseError` to `ExtractError`.
- External entity `<!ENTITY x SYSTEM "file:///etc/hostname">` with `&x;`: `ParseError: undefined entity &x;: line 1, column 80` (no file read).
- A harmless internal entity (`<!ENTITY a "hi">`, `&a;`) is expanded: `'hi'`. Hence DOCTYPE with internal entities is accepted; it is limited only by expat's amplification limit. Optional extra hardening: reject any part whose first 4 KiB contains `<!DOCTYPE` / `<!ENTITY` (OOXML and ODF `content.xml` never need a DTD; **not** verified that every real-world producer omits it, so decide in 7.4). `defusedxml` is not used (no new dependency).
- Because the docs flag billion laughs as "Vulnerable" for system-provided expat, the code must not assume 2.8.5 is the runtime (e.g. a different Docker base image): the amplification protection is a property of the expat in use. Optional runtime guard: parse `pyexpat.EXPAT_VERSION`, warn/refuse below `2.6.0`. Expat's size limits do not bound total element count; the `max_member_bytes` limit and the 20000-cell cap remain necessary, and ElementTree builds the whole tree in memory (a 50 MiB member can need several hundred MiB; the exact factor was **not** measured).

Sources: https://docs.python.org/3.12/library/xml.html, https://github.com/libexpat/libexpat/blob/master/expat/Changes, and the live runs above.

## 21. Symlink behaviour: `os.scandir`, `os.walk`, `Path.resolve`, `os.path.realpath`, `is_relative_to` (task 7.1)

Verified on **2026-10-16**, Python 3.12.15, Linux. Experiment tree (kept): `.../scratchpad/symexp/` (`root/real/f.txt`, `root/dirlink -> real`, `root/outlink -> ../outside`, `root/filelink -> real/f.txt`, `root/loopa <-> root/loopb`, `root/dangling -> nowhere`, `root/real/up -> ..`, plus `outside/o.txt`).

| API | Documented (URL, fetched 2026-10-16) | Observed |
|---|---|---|
| `DirEntry.is_symlink()` | "Return True if this entry is a symbolic link (even if broken); return False if the entry points to a directory or any kind of file, or if it doesn't exist anymore." https://docs.python.org/3.12/library/os.html | `True` for dirlink, outlink, filelink, loopa, loopb, dangling, and `real/up`; `False` for `real`. Never raises for loops. |
| `DirEntry.is_dir(*, follow_symlinks=True)` / `is_file` | default follows symlinks ("a symbolic link pointing to a directory"); with `follow_symlinks=False` "True only if this entry is a directory (without following symlinks)". "This method can raise OSError, such as PermissionError, but FileNotFoundError is caught and not raised." Result cached on the entry | default: `dirlink`, `outlink` -> `is_dir() True`; `filelink` -> `is_file() True`; `dangling` -> both `False`; **`loopa`/`loopb` raise `OSError(40, 'Too many levels of symbolic links')`** for default `is_dir()`/`is_file()`. With `follow_symlinks=False` every symlink gives `False` for both and nothing raises. So: test `entry.is_symlink()` **first** and skip with reason `symlink`; never call the following variants before that. |
| `os.walk(top, followlinks=False)` | "dirnames is a list of the names of the subdirectories in dirpath (including symlinks to directories ...)". "By default, walk() will not walk down into symbolic links that resolve to directories." "setting followlinks to True can lead to infinite recursion if a link points to a parent directory of itself. walk() does not keep track of the directories it visited already." | Walk of `root` listed `dirlink` and `outlink` in `dirnames` of `root` (but never descended into them; the only visited directories were `root` and `root/real`), listed `dangling`, `filelink`, `loopa`, `loopb` in `filenames`, and listed `up` (symlink to `..`) in `dirnames` of `root/real` without descending. With `followlinks=True` the walk did not terminate by itself (stopped by my 200-directory counter). **Symlinks therefore still appear in `os.walk` lists:** filter them with `os.path.islink`/`DirEntry.is_symlink` to count them as skipped (reason `symlink`); `os.walk` cannot report a symlink-to-directory as a skipped file. The crawler should use a hand-written recursive `os.scandir` loop (depth counter, sorted entries) instead of `os.walk`. |
| `Path.is_symlink()` | "Return True if the path points to a symbolic link, False otherwise. False is also returned if the path doesn't exist; other errors (such as permission errors) are propagated." https://docs.python.org/3.12/library/pathlib.html | `True` for the dangling link and the loop link; `Path.exists()` `False` for both. |
| `Path.resolve(strict=False)` | "If the path doesn't exist and strict is True, FileNotFoundError is raised. If strict is False, the path is resolved as far as possible and any remainder is appended without checking whether it exists. If an infinite loop is encountered along the resolution path, RuntimeError is raised." | `dirlink` -> `.../root/real`; `outlink` -> `.../outside` (outside the root); `filelink` -> `root/real/f.txt`; `real/up` -> `root`; `dangling` strict=False -> `root/nowhere` (no error), strict=True -> `FileNotFoundError`; `loopa` raises **`RuntimeError`** (message "Symlink loop from ...") for **both** strict values. |
| `os.path.realpath(path, *, strict=False)` | "By default, the path is evaluated up to the first component that does not exist, is a symlink loop, or whose evaluation raises OSError. All such components are appended unchanged ... the resulting path may be missing or inaccessible, may still contain links or loops". "If strict is True, the first error encountered when evaluating the path is re-raised"; `strict` added in 3.10; `ALLOW_MISSING` added in 3.12.11. https://docs.python.org/3.12/library/os.path.html (the docs do not name the exception for a loop under strict) | non-strict results equal the `Path.resolve` results; `strict=True`: dangling -> `FileNotFoundError`, **loop -> `OSError`** (class not narrowed here; catch `OSError`); non-strict loop returns the path unchanged and does not raise. |
| `PurePath.is_relative_to(other)` | "This method is string-based; it neither accesses the filesystem nor treats '..' segments specially." Added 3.9; passing extra arguments deprecated in 3.12. https://docs.python.org/3.12/library/pathlib.html | `Path("/a/rootx/f").is_relative_to("/a/root")` -> `False` (not a string-prefix test), `Path("/a/root/f")` -> `True`, **`Path("/a/root/../x").is_relative_to("/a/root")` -> `True`** (`..` not collapsed). So apply it only to already **resolved/real** paths. |

Recommended containment check per entry (matches the contract "real path of every entry must stay inside the real path of the root"): `real_root = os.path.realpath(root)`; for each entry that is **not** a symlink, `Path(os.path.realpath(entry.path)).is_relative_to(real_root)` (realpath is only a guard against a symlinked **parent** component; since the crawler never descends symlinks and the root itself is resolved once, this should always be true, and a `False` is a bug or a race, so skip with reason `symlink`). Catch `OSError` and `RuntimeError` around the resolution and skip with reason `unreadable`. A time-of-check/time-of-use race (a directory swapped for a symlink after the scan) is not prevented by any of these APIs (**not tested; UNVERIFIED**); mitigations are hashing at read time and re-checking `is_symlink()` before opening (`os.open(..., os.O_NOFOLLOW)` is Linux/macOS-only; not researched).

## 22. PEM private-key header forms to detect (task 7.1)

Verified on **2026-10-16**.

| Fact | Source |
|---|---|
| PEM textual encoding: `preeb = "-----BEGIN " label "-----"`, `posteb = "-----END " label "-----"`; "Labels are formally case-sensitive, uppercase, and comprised of zero or more characters" | RFC 7468 section 2/3 (fetched 2026-10-16) https://www.rfc-editor.org/rfc/rfc7468 |
| `-----BEGIN PRIVATE KEY-----`: label `PRIVATE KEY` = unencrypted PKCS #8 `PrivateKeyInfo` / `OneAsymmetricKey` | RFC 7468 section 10 |
| `-----BEGIN ENCRYPTED PRIVATE KEY-----`: label `ENCRYPTED PRIVATE KEY` = PKCS #8 `EncryptedPrivateKeyInfo` | RFC 7468 section 11 |
| `-----BEGIN RSA PRIVATE KEY-----` and `-----BEGIN EC PRIVATE KEY-----` are **not** defined in RFC 7468 (the fetched RFC text does not mention them; Appendix A lists only non-conforming certificate/CSR labels). They are the traditional OpenSSL formats (PKCS #1 RSA, SEC1 EC). Their existence is common practice, **UNVERIFIED** against a primary source here. Also `-----BEGIN DSA PRIVATE KEY-----` exists in the same family (UNVERIFIED) | RFC 7468 text; no primary source found |
| `-----BEGIN OPENSSH PRIVATE KEY-----` / `-----END OPENSSH PRIVATE KEY-----`: marker strings `MARK_BEGIN "-----BEGIN OPENSSH PRIVATE KEY-----\n"`, `MARK_END` in OpenSSH `sshkey.c` lines 67-68; payload starts with `AUTH_MAGIC "openssh-key-v1"` (PROTOCOL.key section 1) | https://raw.githubusercontent.com/openssh/openssh-portable/master/sshkey.c and https://raw.githubusercontent.com/openssh/openssh-portable/master/PROTOCOL.key (fetched 2026-10-16). `PROTOCOL.key` itself does not show the armor line; `sshkey.c` does. |
| `-----BEGIN PGP PRIVATE KEY BLOCK-----`: OpenPGP ASCII armor header line for secret keys (RFC 4880 section 6.2 / RFC 9580). **UNVERIFIED** here: the RFC was not fetched in this task. Not a PEM label (armor syntax differs: header "BLOCK" suffix, CRC24 / checksum line) | no source fetched |
| Also in the wild (UNVERIFIED, general knowledge): `-----BEGIN DSA PRIVATE KEY-----`, `-----BEGIN ENCRYPTED PRIVATE KEY-----` (listed), PuTTY `PuTTY-User-Key-File-` header (not PEM), and `-----BEGIN SSH2 ENCRYPTED PRIVATE KEY-----` (SSH.com) | none |

Detection rule consistent with the contract (`-----BEGIN ` + any text + `PRIVATE KEY-----` in the first 64 KiB): it matches `PRIVATE KEY`, `ENCRYPTED PRIVATE KEY`, `RSA PRIVATE KEY`, `EC PRIVATE KEY`, `DSA PRIVATE KEY`, `OPENSSH PRIVATE KEY`, but **not** `-----BEGIN PGP PRIVATE KEY BLOCK-----` (it ends in `BLOCK-----`), so the regex needs a second alternative: `-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----`. Do a byte-level search on the raw bytes (do not decode) and also accept CRLF; do not require the `END` line (a truncated file still counts). A key inside a docx/xlsx/pdf is compressed and is **not** found by this scan (limitation; the Office text itself would be extracted, so a pasted key would appear in the corpus: **known limitation**, document it).

Sources: https://www.rfc-editor.org/rfc/rfc7468, OpenSSH `sshkey.c` and `PROTOCOL.key` (URLs above).

## 23. Open items after task 7.1

**UNVERIFIED** (not checked against a primary document or a real producer file):
- The ECMA-376 / ISO 29500 and OASIS ODF texts were read only through Microsoft Learn (which quotes ISO 29500-1) and the ODF 1.3 part 3 schema HTML; the namespace URIs of `w:`, `a:`, `p:`, main SpreadsheetML and the package-relationships namespace come from the working samples, not from the text.
- Real-world files: no Word/PowerPoint/Excel/LibreOffice output was inspected; all XML is hand-written minimal. Behaviours not seen: rich-text shared strings (`si/r/t`), phonetic runs, `a:br`, pptx tables, `p:sldIdLst` order, hidden sheets/slides, odp page structure, `office:annotation`, tracked changes (`w:del`/`w:ins`), text boxes (`w:txbxContent`) and headers/footers/footnotes (separate parts, not read by the contract).
- Localised docx heading style IDs/names (19.2): `berschrift1`/`Überschrift 1` claim is anecdotal; `w:br` type values; `w:t` `xml:space`.
- ZIP encrypted flag meaning against the PKWARE APPNOTE; `NotImplementedError` for unsupported compression; zip64 members; behaviour of the three limits on archives with data descriptors (flag bit 3, where local headers carry zero sizes: the central directory `ZipInfo` sizes are what `infolist()` returns).
- Memory cost of ElementTree on a 50 MiB XML member (not measured); the repeat caps for ODF are proposals, not spec values.
- PGP armor header (RFC 4880/9580), RSA/EC/DSA PEM labels (OpenSSL), time-of-check/time-of-use symlink races, `O_NOFOLLOW`.
