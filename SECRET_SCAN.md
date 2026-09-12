# Secret and public-repository audit

Audit date: 2026-09-12. Scope: `D:\ai-projects`.

## Publication verdict

**GO for the reviewed Git publication candidate with the updated ignore rules. NO-GO for uploading or archiving the entire working directory.**

No confirmed credential leak or unresolved likely-leak was found in publication-eligible source. The final candidate must include this report and the updated `.gitignore`, and must continue excluding the local artifacts listed below. This is an audit verdict, not authorization to commit or publish.

This report distinguishes a secret leak from a keyword match. No credential values are printed. `[REDACTED; N characters]` gives the matched length without revealing a credential prefix or suffix. `leak` means a credential exposed in publication-eligible content; `likely-leak` means credential-like material requiring review; `false-positive` means an inspected reference, placeholder, public certificate, test value, or non-secret identifier.

## Scope and method

- Enumerated hidden and ignored files on disk, including virtual environments, caches, Git metadata, model artifacts, and document outputs. Initial inventory: 181,740 files, 9,312,039,368 bytes.
- Searched credential filenames: `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa`, `credentials.json`, and `service-account*.json`.
- Searched the requested keywords and provider-token prefixes, private-key headers, credential-bearing URLs, and assignments next to key/secret/token/password/credential names. Entropy screening uses at least 16 characters and Shannon entropy of at least 3.5 bits per character, with separate signature and short-source-literal checks.
- Used ripgrep with hidden files, ignore rules disabled, binary text scanning, and redacted post-processing. No provider credential verification requests were made.
- Binary bytes were searched; archives and Git objects were not decompressed, PDFs were not OCRed, and model tensors were not interpreted. Excluding those artifacts from publication is a separate required control.
- The prior `.secrets.baseline` was consulted as a candidate list, not treated as proof that the full disk was clean.
- Git already existed at the start of this audit. It has no commits and 878 staged paths. This audit did not initialize Git, commit, rewrite history, create a remote repository, or publish anything.

The full-disk scan finished successfully with **zero enumeration/read errors**. It recorded 53,585 broad assignment/signature candidates; 464 were in publication-eligible files, while the remaining 53,121 were in excluded files. These are heuristic matches, not counts of secrets. The source review and independent detector cross-check found references, expressions, placeholders, hashes, and test inputs rather than hardcoded real credentials. No application-source replacement or new environment template was needed.

The content pass read files as they existed during the audit; this report was authored afterward from sanitized results. The existing Git index was cross-checked separately. The scan did not inspect configured process/user environment-variable values or claim to prove that arbitrary encrypted/compressed content is secret-free.

| Requested string | Observed occurrences, case-insensitive |
| --- | ---: |
| `API_KEY` | 15,480 |
| `SECRET` | 54,842 |
| `TOKEN` | 365,901 |
| `PASSWORD` | 21,154 |
| `PRIVATE KEY` | 4,497 |
| `BEGIN OPENSSH` | 5 |
| `sk-` | 3,855 |
| `ghp_` | 21 |
| `github_pat_` | 31 |
| `AIza` | 165 |
| `xai-` | 1 |
| `Bearer ` | 1,679 |

Most occurrences are in installed dependencies and bytecode. Keyword occurrences were observed in 38,183 files. In particular, private-key parsing/header constants in cryptography/auth libraries are not themselves private keys. Provider-looking strings and credential-bearing URLs also occur in dependency tests and documentation. Those dependency trees remain excluded rather than being endorsed for publication.

## Additional reviewed matches

| Classification | Path | Line | Variable | Redacted preview | Assessment |
| --- | --- | --- | --- | --- | --- |
| false-positive | `10-Guardrails-Middleware/tests/test_pii.py` | 53 | `token` | `[REDACTED; 21 characters]` | Synthetic input to a PII-detection test. |
| false-positive | `7-Multi-Tenant-LLM-API/docs/API.md` | 9 | `X-Admin-Token` | `[environment-variable placeholder]` | Header example refers to `ADMIN_TOKEN`. |
| false-positive | `14-Tool-Calling-Framework/docs/ARCHITECTURE.md` | 82 | `api_key` | `[variable reference]` | SDK example passes a variable, not a literal credential. |
| false-positive | `.secrets.baseline` | 132–228 | `hashed_secret` | `[REDACTED; 40-character fingerprints]` | Scanner fingerprints of reviewed false positives, not raw secrets. |
| false-positive | `16-Agentic-Document-Extraction/data/parse/prompt-eval-20260912/comparison.html` | 1691 | image `src` | `[REDACTED; 132-character match]` | `AIza` signature occurs inside an embedded base64 image. File is ignored. |
| false-positive | `7-Multi-Tenant-LLM-API/data/app.db` | 81 (binary line) | key-related binary fragment | `[REDACTED; 59-character matches]` | Binary fragments are not reliable variable names. Read-only schema inspection confirms an `api_keys.key_hash` field. Database also has audit and prompt-log tables and must remain private. |

No credential-bearing URL was found in publication-eligible project files. Non-project URL matches came from excluded dependency examples, fixtures, or compiled copies. This does not authorize publishing those directories.

## Local environment files

| Classification | Path | Lines | Variable | Redacted preview | Assessment |
| --- | --- | --- | --- | --- | --- |
| false-positive | `2-Structured-Output-Engine/.env` | 1, 2, 4 | `AGNES_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` | `[EMPTY]` | Credential slots are empty; file is ignored. |
| false-positive | `5-Semantic-Cache-Layer/.env` | 19, 21, 24 | `AGNES_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` | `[EMPTY]` | Credential slots are empty; file is ignored. |
| false-positive | `2-Structured-Output-Engine/.env.example` | 1, 2, 4 | API-key slots | `[EMPTY]` | Safe template. |
| false-positive | `5-Semantic-Cache-Layer/.env.example` | 19, 21, 24 | API-key slots | `[EMPTY]` | Safe template. |
| false-positive | `7-Multi-Tenant-LLM-API/.env.example` | 2, 7, 10, 14 | `ADMIN_TOKEN`, API-key slots | `[EMPTY]` | Safe template. |
| false-positive | `10-Guardrails-Middleware/.env.example` | 17, 22, 27 | API-key slots | `[EMPTY]` | Safe template. |

## Fixture keys in the publication candidate

There are **no committed fixture keys**, because there are no commits. The following synthetic literals are staged in tests. They are false positives, not production credentials. Other matches named `key` are UI widget identifiers or JSON/dictionary keys; `user_key` is an identity/hash input, not an API credential.

| Classification | Path | Lines | Variable | Redacted preview | Evidence |
| --- | --- | --- | --- | --- | --- |
| false-positive | `2-Structured-Output-Engine/tests/test_providers.py` | 188, 207, 224, 280, 300, 309 | `api_key` | `[REDACTED; 7 characters]` | Synthetic provider values used with mocked HTTP clients. |
| false-positive | `2-Structured-Output-Engine/tests/test_providers.py` | 249 | `api_key` | `[REDACTED; 9 characters]` | Mock-client test checks request/schema construction. |
| false-positive | `2-Structured-Output-Engine/tests/test_providers.py` | 214 | `Authorization/Bearer` | `[REDACTED; 7 characters]` | Assertion against the mock key. |
| false-positive | `7-Multi-Tenant-LLM-API/tests/conftest.py` | 32 | `TEST_ADMIN_TOKEN` | `[REDACTED; 16 characters]` | Test-only token installed with `monkeypatch.setenv`. |
| false-positive | `7-Multi-Tenant-LLM-API/tests/test_auth.py` | 67 | `Authorization/Bearer` | `[REDACTED; 26 characters]` | Invalid-credential rejection test. |
| false-positive | `7-Multi-Tenant-LLM-API/tests/test_auth.py` | 98, 103, 110 | `admin_token` | `[REDACTED; 9 characters]` | Explicit test-local comparison value. |
| false-positive | `11-Streaming-Response-Infrastructure/tests/test_provider_adapters.py` | 87, 110 | `api_key` | `[REDACTED; 8 characters]` | Synthetic adapter key. |
| false-positive | `12-Prompt-Versioning-and-AB-System/tests/test_api.py` | 10 | `ADMIN_TOKEN` | `[REDACTED; 16 characters]` | Test-only environment token and temporary stores. |
| false-positive | `12-Prompt-Versioning-and-AB-System/tests/test_outcomes.py` | 88 | `user_key` | `[REDACTED; 20 characters]` | Test asserts that the identity input is hashed and not stored raw. |
| false-positive | `13-LLM-Observability-Stack/tests/test_api.py` | 157, 164 | token header | `[REDACTED; 5 / 6 characters]` | Authentication test literals. |
| false-positive | `15-Self-Correcting-RAG-Agent/tests/test_http_search.py` | 46, 51 | `api_key`, `Authorization/Bearer` | `[REDACTED; 8 characters]` | Mock search-provider key and header assertion. |
| false-positive | `16-Agentic-Document-Extraction/tests/test_diagnostics.py` | 33 | `api_key` | `[REDACTED; 19 characters]` | Deliberately fake value used to test diagnostic redaction. |

## Independent detector cross-check

A fresh `detect-secrets scan --no-verify` of the Git publication candidate, excluding the baseline and this report, returned 11 findings. Three are fixture literals listed above. The remaining eight are the following non-secrets. No old baseline suppression was used to hide these findings.

| Classification | Path | Line | Variable | Redacted preview | Assessment |
| --- | --- | --- | --- | --- | --- |
| false-positive | `10-Guardrails-Middleware/config/pii.yaml` | 8 | `api_key` | `[boolean]` | Detector enable/disable setting. |
| false-positive | `11-Streaming-Response-Infrastructure/src/stream/config.py` | 30 | `OPENAI_API_KEY_VAR` | `[environment variable name]` | Name of an environment variable, not its value. |
| false-positive | `11-Streaming-Response-Infrastructure/src/stream/config.py` | 37 | `AGNES_API_KEY_VAR` | `[environment variable name]` | Name of an environment variable, not its value. |
| false-positive | `11-Streaming-Response-Infrastructure/src/stream/config.py` | 40 | `GEMINI_API_KEY_VAR` | `[environment variable name]` | Name of an environment variable, not its value. |
| false-positive | `2-Structured-Output-Engine/src/providers/agnes_provider.py` | 22 | `API_KEY_ENV_VAR` | `[environment variable name]` | Name of an environment variable, not its value. |
| false-positive | `2-Structured-Output-Engine/src/providers/gemini_provider.py` | 30 | `API_KEY_ENV_VAR` | `[environment variable name]` | Name of an environment variable, not its value. |
| false-positive | `2-Structured-Output-Engine/src/providers/openai_compatible.py` | 30 | `API_KEY_ENV_VAR` | `[environment variable name]` | Name of an environment variable, not its value. |
| false-positive | `4-LLM-Evaluation-Harness/baselines/current.json` | 5 | `dataset_hash` | `[REDACTED; 64 characters]` | Dataset content hash, not an authentication credential. |

## Private and generated artifacts

These files must not be included in a public upload even when no credential signature is found. Existing local files are preserved.

| Path/category | Why excluded |
| --- | --- |
| Child `.venv/`, `__pycache__/`, package caches, `node_modules/` if present | Installed dependencies, compiled files, bundled certificates and test material. |
| `1-Production-RAG-Pipeline/data/indexes/` | Generated BM25 and Qdrant index/storage. |
| `1-Production-RAG-Pipeline/data/processed/` | Ingestion/chunk outputs. |
| `5-Semantic-Cache-Layer/data/cache/qdrant/` | Runtime vector database and cache data. |
| `8-Fine-Tuning-Pipeline/outputs/` | Generated model adapters, tokenizer data, training metadata. |
| `8-Fine-Tuning-Pipeline/outputs/adapters/20260912-193951/adapter_model.safetensors` | Model weights: 18,713,144 bytes. |
| `8-Fine-Tuning-Pipeline/outputs/adapters/20260912-193951/tokenizer.json` | Generated tokenizer: 19,989,325 bytes. |
| `16-Agentic-Document-Extraction/data/inbox/` | Five local input PDFs; not public fixtures. |
| `16-Agentic-Document-Extraction/data/{crops,parse,annotated,audit,committed,review}/` | Document-derived images, extraction results, prompt snapshots, audit/review output. |
| `16-Agentic-Document-Extraction/data/parse/diagnostics-20260912/prompts/` | On-disk prompt snapshots confirmed present. |
| `.codegraph/`, `.code-review-graph/`, `.aiwg/` | Local indexes and agent/audit state. |
| Six child `.git.empty-backup/` directories | Local Git metadata backups, excluded from the root repository. |

## Ignore-rule verification

The root `.gitignore` now covers Python environments/build products/caches, Node dependencies, `.env` files, private-key and credential filenames, models and embedding indexes, Qdrant storage, IDE state, Windows thumbnails, private inbox scans, and prompt/audit dumps. `.env.example` files and intended `.gitkeep` placeholders remain eligible for tracking.

Synthetic-path checks passed for credential files, weights, indexes, inbox PDFs, prompt dumps, Node dependencies, IDE settings, and Windows thumbnails. `git ls-files -ci --exclude-standard` returned no paths: the new exclusions do not silently leave matching artifacts in the existing index. This audit leaves the Git index unchanged, so the updated `.gitignore` and this report must be included in the eventual reviewed publication candidate.

## Complete credential-filename inventory

All 27 matches are accounted for below. The six environment/template files are described above. Each PEM was inspected for its block types and contains only public `CERTIFICATE` blocks; no private-key block was present. No `*.key`, `*.p12`, `*.pfx`, `id_rsa`, `credentials.json`, or `service-account*.json` files were found.

| Classification | Path | Bytes | Preview |
| --- | --- | ---: | --- |
| false-positive | `1-Production-RAG-Pipeline/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `1-Production-RAG-Pipeline/.venv/Lib/site-packages/grpc/_cython/_credentials/roots.pem` | 623801 | [public certificate bundle; no private-key block] |
| false-positive | `10-Guardrails-Middleware/.env.example` | 805 | [empty credential slots / template] |
| false-positive | `10-Guardrails-Middleware/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `11-Streaming-Response-Infrastructure/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `12-Prompt-Versioning-and-AB-System/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `13-LLM-Observability-Stack/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `14-Tool-Calling-Framework/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/grpc/_cython/_credentials/roots.pem` | 623801 | [public certificate bundle; no private-key block] |
| false-positive | `16-Agentic-Document-Extraction/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `16-Agentic-Document-Extraction/.venv/Lib/site-packages/pip/_vendor/certifi/cacert.pem` | 234354 | [public certificate bundle; no private-key block] |
| false-positive | `2-Structured-Output-Engine/.env` | 99 | [empty credential slots / template] |
| false-positive | `2-Structured-Output-Engine/.env.example` | 99 | [empty credential slots / template] |
| false-positive | `2-Structured-Output-Engine/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `3-Context-Assembly-Service/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `4-LLM-Evaluation-Harness/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `5-Semantic-Cache-Layer/.env` | 717 | [empty credential slots / template] |
| false-positive | `5-Semantic-Cache-Layer/.env.example` | 717 | [empty credential slots / template] |
| false-positive | `5-Semantic-Cache-Layer/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `5-Semantic-Cache-Layer/.venv/Lib/site-packages/grpc/_cython/_credentials/roots.pem` | 623801 | [public certificate bundle; no private-key block] |
| false-positive | `6-Model-Routing-Gateway/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `7-Multi-Tenant-LLM-API/.env.example` | 583 | [empty credential slots / template] |
| false-positive | `7-Multi-Tenant-LLM-API/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `9-Agent-Memory-System/.venv/Lib/site-packages/certifi/cacert.pem` | 240216 | [public certificate bundle; no private-key block] |
| false-positive | `9-Agent-Memory-System/.venv/Lib/site-packages/grpc/_cython/_credentials/roots.pem` | 623801 | [public certificate bundle; no private-key block] |

## Environment and cache inventory

Sixteen `.venv` directories and 3,087 `__pycache__` directories were found. No `node_modules` directories or `*.gguf` files were found. All environments and bytecode caches are excluded.

| Environment path | `__pycache__` directories in that child |
| --- | ---: |
| `1-Production-RAG-Pipeline/.venv` | 182 |
| `10-Guardrails-Middleware/.venv` | 99 |
| `11-Streaming-Response-Infrastructure/.venv` | 105 |
| `12-Prompt-Versioning-and-AB-System/.venv` | 170 |
| `13-LLM-Observability-Stack/.venv` | 189 |
| `14-Tool-Calling-Framework/.venv` | 165 |
| `15-Self-Correcting-RAG-Agent/.venv` | 231 |
| `16-Agentic-Document-Extraction/.venv` | 328 |
| `2-Structured-Output-Engine/.venv` | 125 |
| `3-Context-Assembly-Service/.venv` | 74 |
| `4-LLM-Evaluation-Harness/.venv` | 138 |
| `5-Semantic-Cache-Layer/.venv` | 182 |
| `6-Model-Routing-Gateway/.venv` | 71 |
| `7-Multi-Tenant-LLM-API/.venv` | 219 |
| `8-Fine-Tuning-Pipeline/.venv` | 625 |
| `9-Agent-Memory-System/.venv` | 184 |

## Complete large-file inventory

Threshold: 10 MiB (10,485,760 bytes). All 130 files below are ignored and absent from the Git index. This inventory includes large non-binary artifacts as well as binaries so that none can enter publication unnoticed.

| Path | Bytes |
| --- | ---: |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cublasLt64_13.dll` | 477896816 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/torch_cuda.dll` | 422652928 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/torch_cpu.dll` | 306006528 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cufft64_12.dll` | 284331040 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cudnn_engines_precompiled64_9.dll` | 221832304 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cusparse64_12.dll` | 150326304 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cusolver64_12.dll` | 126421024 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cudnn_graph64_9.dll` | 110908016 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cudnn_adv64_9.dll` | 106547312 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cusolverMg64_12.dll` | 95365152 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/nvrtc64_130_0.alt.dll` | 91028512 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/nvrtc64_130_0.dll` | 90961440 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/nvJitLink_130_0.dll` | 88218656 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/curand64_10.dll` | 58863672 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cudnn_heuristic64_9.dll` | 58741360 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cublas64_13.dll` | 50288240 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cudnn_ops64_9.dll` | 36770416 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/cudnn_engines_runtime_compiled64_9.dll` | 31745136 |
| `15-Self-Correcting-RAG-Agent/.venv/Scripts/ty.exe` | 30639104 |
| `12-Prompt-Versioning-and-AB-System/.venv/Scripts/ty.exe` | 30639104 |
| `13-LLM-Observability-Stack/.venv/Scripts/ty.exe` | 30639104 |
| `10-Guardrails-Middleware/.venv/Scripts/ty.exe` | 30639104 |
| `1-Production-RAG-Pipeline/.venv/Scripts/ty.exe` | 30639104 |
| `4-LLM-Evaluation-Harness/.venv/Scripts/ty.exe` | 30639104 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/torch_cpu.lib` | 29325638 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/nvperf_host.dll` | 27764256 |
| `10-Guardrails-Middleware/.venv/Scripts/ruff.exe` | 26491392 |
| `1-Production-RAG-Pipeline/.venv/Scripts/ruff.exe` | 26491392 |
| `12-Prompt-Versioning-and-AB-System/.venv/Scripts/ruff.exe` | 26491392 |
| `4-LLM-Evaluation-Harness/.venv/Scripts/ruff.exe` | 26491392 |
| `15-Self-Correcting-RAG-Agent/.venv/Scripts/ruff.exe` | 26491392 |
| `13-LLM-Observability-Stack/.venv/Scripts/ruff.exe` | 26491392 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/pymupdf/mupdfcpp64.dll` | 26295808 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/pymupdf/mupdfcpp64.dll` | 26295808 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/bitsandbytes/libbitsandbytes_cuda128.dll` | 26289152 |
| `.code-review-graph/graph.db` | 26107904 |
| `6-Model-Routing-Gateway/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `7-Multi-Tenant-LLM-API/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `4-LLM-Evaluation-Harness/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `2-Structured-Output-Engine/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `16-Agentic-Document-Extraction/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `9-Agent-Memory-System/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `5-Semantic-Cache-Layer/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `3-Context-Assembly-Service/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `11-Streaming-Response-Infrastructure/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `13-LLM-Observability-Stack/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `14-Tool-Calling-Framework/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `12-Prompt-Versioning-and-AB-System/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `10-Guardrails-Middleware/.venv/Lib/site-packages/pyarrow/arrow.dll` | 21993984 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/bitsandbytes/libbitsandbytes_cuda118.dll` | 21728768 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/bitsandbytes/libbitsandbytes_cuda121.dll` | 21422592 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/bitsandbytes/libbitsandbytes_cuda126.dll` | 21178368 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/bitsandbytes/libbitsandbytes_cuda124.dll` | 21133824 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/torch/lib/torch_python.dll` | 20728832 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `6-Model-Routing-Gateway/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `14-Tool-Calling-Framework/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `4-LLM-Evaluation-Harness/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `12-Prompt-Versioning-and-AB-System/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `5-Semantic-Cache-Layer/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `13-LLM-Observability-Stack/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `7-Multi-Tenant-LLM-API/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `11-Streaming-Response-Infrastructure/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `9-Agent-Memory-System/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `2-Structured-Output-Engine/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `10-Guardrails-Middleware/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `3-Context-Assembly-Service/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `16-Agentic-Document-Extraction/.venv/Lib/site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll` | 20589056 |
| `8-Fine-Tuning-Pipeline/outputs/adapters/20260912-193951/tokenizer.json` | 19989325 |
| `11-Streaming-Response-Infrastructure/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `7-Multi-Tenant-LLM-API/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `7-Multi-Tenant-LLM-API/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `8-Fine-Tuning-Pipeline/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `1-Production-RAG-Pipeline/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `12-Prompt-Versioning-and-AB-System/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `12-Prompt-Versioning-and-AB-System/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `10-Guardrails-Middleware/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `10-Guardrails-Middleware/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `11-Streaming-Response-Infrastructure/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `9-Agent-Memory-System/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `6-Model-Routing-Gateway/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `14-Tool-Calling-Framework/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `14-Tool-Calling-Framework/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `15-Self-Correcting-RAG-Agent/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `16-Agentic-Document-Extraction/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `16-Agentic-Document-Extraction/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `6-Model-Routing-Gateway/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `2-Structured-Output-Engine/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `9-Agent-Memory-System/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `3-Context-Assembly-Service/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `3-Context-Assembly-Service/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `2-Structured-Output-Engine/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `13-LLM-Observability-Stack/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `13-LLM-Observability-Stack/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `4-LLM-Evaluation-Harness/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `5-Semantic-Cache-Layer/.venv/share/jupyter/nbextensions/pydeck/index.js.map` | 19408921 |
| `5-Semantic-Cache-Layer/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `4-LLM-Evaluation-Harness/.venv/Lib/site-packages/pydeck/nbextension/static/index.js.map` | 19408921 |
| `8-Fine-Tuning-Pipeline/outputs/adapters/20260912-193951/adapter_model.safetensors` | 18713144 |
| `.codegraph/codegraph.db` | 16523264 |
| `12-Prompt-Versioning-and-AB-System/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `9-Agent-Memory-System/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `7-Multi-Tenant-LLM-API/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `6-Model-Routing-Gateway/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `14-Tool-Calling-Framework/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `5-Semantic-Cache-Layer/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `13-LLM-Observability-Stack/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `10-Guardrails-Middleware/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `2-Structured-Output-Engine/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `11-Streaming-Response-Infrastructure/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `3-Context-Assembly-Service/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `8-Fine-Tuning-Pipeline/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `4-LLM-Evaluation-Harness/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `16-Agentic-Document-Extraction/.venv/Lib/site-packages/pyarrow/arrow_flight.dll` | 14660096 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/pymupdf/_mupdf.pyd` | 13063168 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/pymupdf/_mupdf.pyd` | 13063168 |
| `5-Semantic-Cache-Layer/.venv/Lib/site-packages/grpc/_cython/cygrpc.cp314-win_amd64.pyd` | 11205120 |
| `1-Production-RAG-Pipeline/.venv/Lib/site-packages/grpc/_cython/cygrpc.cp313-win_amd64.pyd` | 11176960 |
| `15-Self-Correcting-RAG-Agent/.venv/Lib/site-packages/grpc/_cython/cygrpc.cp313-win_amd64.pyd` | 11176960 |
| `9-Agent-Memory-System/.venv/Lib/site-packages/grpc/_cython/cygrpc.cp313-win_amd64.pyd` | 11176960 |
