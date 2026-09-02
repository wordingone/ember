// API rate limits and size constraints for Ember model communication.
// L1 leaf: no intra-ember dependencies.

/** Maximum tokens per single API request. */
export const MAX_TOKENS_PER_REQUEST = 131072;

/** Maximum tokens per session (sliding window across conversation). */
export const MAX_TOKENS_PER_SESSION = 1000000;

/** Maximum number of concurrent API requests. */
export const MAX_CONCURRENT_REQUESTS = 10;

/** Maximum retries per failed API call. */
export const MAX_API_RETRIES = 3;

/** API call timeout in milliseconds. */
export const API_TIMEOUT_MS = 120000;

/** Rate limit: requests per minute. */
export const RATE_LIMIT_REQUESTS_PER_MINUTE = 100;

/** Rate limit: tokens per hour. */
export const RATE_LIMIT_TOKENS_PER_HOUR = 5000000;

/** Maximum size for a single file upload in bytes (500 MB). */
export const MAX_FILE_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024;

/** Maximum size for cached context in bytes. */
export const MAX_CACHE_SIZE_BYTES = 100 * 1024 * 1024;

/** Age threshold for context invalidation in milliseconds (4 hours). */
export const CONTEXT_INVALIDATION_AGE_MS = 4 * 60 * 60 * 1000;
