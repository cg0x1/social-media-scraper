# Index Definitions and Design

Using a single Asset document with a Transcript and a field is udpated results in:

Daily metric updates rewrite the whole Lucene doc
Even if you update only view_count, ES rewrites the document under the hood. If the doc contains transcript_text + transcript_lines (nested), you’re rewriting “big payload” docs constantly → more segment merges, I/O, and heap pressure.

Nested transcript_lines multiplies index cost
Nested docs are implemented as additional hidden docs. A single asset with (say) 200 lines is effectively 201 docs at index-time. That’s fine for static indexing, but painful when the parent doc is updated frequently.

refresh_interval=30s + heavy writes
30s is decent, but thousands/day is not huge by itself — what becomes huge is thousands/day × daily refresh updates × large docs.


