"""Streaming Response Infrastructure: SSE, backpressure, reconnect, TTFT/inter-token timing.

Responsible for turning a provider's token stream into a resumable SSE
response; not responsible for prompt construction, auth beyond checking a
key is present, or persisting anything beyond the one-line-per-session
`logs/streams.jsonl`. Start reading at `stream.session` (the state model),
then `stream.api` (how it's exposed over HTTP).
"""
