import time

from app import metrics


class MetricsMiddleware:
    

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = {"code": 500}
        start = time.perf_counter()
        metrics.HTTP_IN_FLIGHT.inc()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            metrics.HTTP_IN_FLIGHT.dec()
            path = _route_template(scope)
            if path != "/metrics":
                method = scope["method"]
                metrics.HTTP_REQUESTS.labels(method, path, str(status["code"])).inc()
                metrics.HTTP_DURATION.labels(method, path).observe(time.perf_counter() - start)


def _route_template(scope) -> str:
   
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "unmatched"
