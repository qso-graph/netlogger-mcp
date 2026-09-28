# Changelog

## 0.1.0 (unreleased)

- Tools for every documented NetLogger API 1.3 call: active nets, live check-ins with the pointer,
  past nets, past check-ins; plus `get_version_info`.
- Records follow a source-independent contract (`schema/contract.schema.json`, 0.1).
- NetLogger's call limits enforced before sending; answers cached; back-off on 429.
- Street, ZIP and IP address never returned.
- `NetLoggerSource` usable as a plain Python library.
