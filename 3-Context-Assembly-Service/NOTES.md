# Design Notes

## Model map (4060 8 GB)

| Job | Model |
|---|---|
| Compress / summarize a slice that will not fit | qwen3.5:2b |
| Tiny compressor / title a memory turn | qwen3.5:0.8b |
| Optional "explain this budget" debug | granite4.1:3b |
| Tokenize docs in another language (translate) | gemma:4b only if source is not English |
| Embed / OCR | skip unless a later phase adds retrieval |

Default path needs no model loaded; tiktoken + packing rules only.
Do not load two 3B+ models simultaneously (8 GB ceiling).
