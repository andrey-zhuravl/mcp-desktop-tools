# Export Formats

All CLI commands can serialise their output through the shared export writer.
The ``--export-format`` flag supports ``json``, ``yaml`` and ``ndjson``.

* ``json`` – pretty printed JSON with UTF-8 output.
* ``yaml`` – ``safe_dump`` without re-ordering keys.
* ``ndjson`` – each element of the supplied list is rendered as a JSON object on
  its own line.

An optional ``--max-output-bytes`` flag truncates the output when the encoded
size exceeds the limit, emitting a warning to stderr. For ``ndjson`` the writer
stops before writing the item that would exceed the limit.
