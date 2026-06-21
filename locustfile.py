"""
CreditVoice AI load test — run with:

    pip install locust
    locust -f locustfile.py --host https://creditvoice-ai.onrender.com

Then open http://localhost:8089 and set:
  - Number of users:  50
  - Spawn rate:       5 per second

Performance targets (Render free tier, single worker):
  - /health              < 200 ms  p95
  - /app/api/dashboard   < 800 ms  p95
  - /webhook (WhatsApp)  < 300 ms  p95  (actual processing is background)

Failure thresholds:
  - Error rate > 1%  → investigate DB pool exhaustion
  - p95 > 3 000 ms   → timing middleware will log WARNINGs
"""

from locust import HttpUser, between, task


class AnonymousUser(HttpUser):
    """Unauthenticated traffic — health checks and static assets."""

    wait_time = between(1, 3)

    @task(10)
    def health(self):
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"health returned {resp.status_code}")
            elif resp.json().get("db") != "ok":
                resp.failure("db not ok: " + resp.text)

    @task(5)
    def spa_shell(self):
        self.client.get("/app")

    @task(2)
    def static_asset(self):
        # Fetches the SPA entry point — exercises static file serving.
        self.client.get("/app/", name="/app/ (SPA shell)")


class WhatsAppWebhook(HttpUser):
    """Simulates Meta sending WhatsApp message events.

    In production Meta always sends POST /webhook with HMAC signature.
    Here we send unsigned requests to measure the 403-fast-path cost so
    we can confirm the signature check itself never becomes a bottleneck.
    """

    wait_time = between(0.5, 2)

    @task
    def webhook_unsigned(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "LOAD_TEST",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "0000", "phone_number_id": "0"},
                        "messages": [{
                            "from": "234800000000",
                            "id": "load_test_msg",
                            "timestamp": "1700000000",
                            "text": {"body": "test"},
                            "type": "text",
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        # Expect 403 — we're testing throughput of the signature-check fast path.
        with self.client.post(
            "/webhook",
            json=payload,
            headers={"Content-Type": "application/json"},
            catch_response=True,
            name="/webhook (unsigned — expects 403)",
        ) as resp:
            if resp.status_code == 403:
                resp.success()
            else:
                resp.failure(f"expected 403 got {resp.status_code}")
