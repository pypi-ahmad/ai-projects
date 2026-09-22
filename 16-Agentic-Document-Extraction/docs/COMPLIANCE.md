# Data and output boundaries

The app transcribes supplied documents into layout-aware artifacts. It does not interpret business meaning, validate arithmetic, infer missing fields, or write records to another system.

The app treats model output as untrusted input. Pydantic checks the response shape, the annotation code checks bounding-box ranges before drawing, and the local renderer escapes document text in HTML. The runtime prompt tells the model to mark unreadable text instead of guessing it.

Uploaded files and generated artifacts stay on the local machine. Page images and prompt context are sent to the configured OpenAI-compatible endpoint. Operators must choose endpoint retention, access, and privacy controls that fit their documents.

Diagnostics expose model/request status and token counts without printing credentials.
