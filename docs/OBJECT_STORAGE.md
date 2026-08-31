# Object storage

The object store has three async methods. `exists` checks a key, `push` publishes a local file, and
`pull` copies an object to a local file. Each method takes a validated relative key. The interface
passes file paths instead of byte strings, so callers can handle large source files without loading
them into memory.

`LocalObjectStore` is the current implementation. A push copies the source through a temporary
file, calculates its SHA256 hash, and publishes it with an atomic filesystem link. An existing key
can be reused only when its size and hash match. A pull also uses a temporary file and then replaces
the requested destination atomically. Local file calls run in the calling task, so a pipeline that
needs concurrent local copies should place each copy in its own worker process.

The interface contains only the operations used by the source pipeline. A future R2 or S3
implementation can implement the same protocol with multipart transfers. Cloud credentials,
buckets, signed URLs, object listing, deletion, and lifecycle policies are outside the current
scope.
