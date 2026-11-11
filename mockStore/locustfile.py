import random
from locust import HttpUser, task, between

class CustomerTraffic(HttpUser):
    # Short wait times ensure fast connection pool exhaustion
    wait_time = between(0.5, 1.5)

    @task(3)
    def browse_history(self):
        cid = random.randint(1, 1000)
        self.client.get(f"/api/v1/customers/{cid}/orders", name="/orders [SeqScan]")

    @task(2)
    def checkout(self):
        payload = {
            "customer_id": random.randint(1, 1000),
            "product_id": random.randint(1, 4),
            "quantity": 1,
            "client_source": "swarm"
        }
        self.client.post(
            "/api/v1/orders/checkout",
            json=payload,
            headers={"X-Simulation-Swarm": "true"},
            name="/checkout [Lock+Sleep]"
        )
