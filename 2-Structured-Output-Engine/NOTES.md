# Design Notes

## Model map (4060 8 GB)

| Job | Model |
|---|---|
| First-pass structured generate | granite4.1:3b |
| Fast / cheap pass | qwen3.5:2b |
| JSON repair / retry | qwen3.5:0.8b |
| Extract from image / scan | qwen3-vl:2b or AuditAid/PaddleOCR-VL-1.6-0.9B, then text schema |
| Embed / translate | not required for core path |

Do not load a 3B chat model and a VL model together.
