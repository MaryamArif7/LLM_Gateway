
from prometheus_client import Counter, Gauge, Histogram


HTTP_REQUESTS = Counter(
    "gateway_http_requests_total", "HTTP requests handled",
    ["method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "gateway_http_request_duration_seconds",
    "Time from request start to the last byte sent. For streamed chat this is the whole stream.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
HTTP_IN_FLIGHT = Gauge("gateway_http_requests_in_flight", "HTTP requests being handled right now")

REQUESTS = Counter(
    "gateway_requests_total", "Gateway requests by how they ended",
    ["endpoint", "provider", "model", "outcome", "fallback"],
)

ATTEMPTS = Counter(
    "gateway_provider_attempts_total", "Calls to providers by result",
    ["provider", "model", "result"],
)
PROVIDER_DURATION = Histogram(
    "gateway_provider_duration_seconds", "Time for a successful provider call, including streaming",
    ["provider", "model"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120),
)

CACHE_LOOKUPS = Counter("gateway_cache_lookups_total", "Response cache lookups", ["result"])


CIRCUIT_STATE = Gauge("gateway_circuit_state", "Circuit breaker state per provider", ["provider"])
CIRCUIT_TRIPS = Counter("gateway_circuit_trips_total", "Times a provider's breaker opened", ["provider"])

USAGE_EVENTS = Counter("gateway_usage_events_total", "Usage rows by how they were recorded", ["result"])
USAGE_PUBLISH_SECONDS = Histogram(
    "gateway_usage_publish_seconds", "Time to hand a usage row to Kafka (or give up)",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 3),
)

CIRCUIT_VALUES = {"closed": 0, "half_open": 1, "open": 2}
