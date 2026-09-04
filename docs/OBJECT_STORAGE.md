# Object storage

The object store has three synchronous methods. `exists` checks a key, `push` publishes a local
file, and `pull` copies an object to a local file. Each method takes a validated relative key. The
interface passes file paths instead of byte strings, so callers can handle large source files
without loading them into memory.

`LocalObjectStore` is the current implementation. A push copies the source through a temporary
file, calculates its SHA256 hash, and publishes it with an atomic filesystem link. An existing key
can be reused only when its size and hash match. A pull also uses a temporary file and then replaces
the requested destination atomically. The implementation also flushes the containing directory
after it links or replaces a file, which protects the directory update across a system crash on
Linux. A pipeline that needs concurrent storage work should run each complete operation in a worker
process.

The local store root must be trusted and owned only by the application. The implementation rejects
symbolic links that already exist in an object's path, but it does not claim to protect against a
hostile process that changes path components during an operation. Preventing path replacement
races would require Linux directory file descriptor operations and a larger interface.

The interface contains only the operations used by the source and release pipeline. A future R2
or S3 implementation can implement the same protocol with multipart transfers. Cloud
credentials, buckets, signed URLs, object listing, deletion, and lifecycle policies are outside
the current scope. The running application never needs object-store credentials: it serves a
sealed local SQLite database and immutable map artifact.
