from __future__ import annotations
import unittest
from master import master_server
from worker.worker_node import compute_chunk, merge_results

ROWS = [{"year": 2024, "month": 1, "valid_pixels": 2, "mean_radiance": 5.0,
         "min_radiance": 1.0, "max_radiance": 9.0, "sum_radiance": 10.0}]


class NewArchitectureTests(unittest.TestCase):
    def setUp(self):
        master_server.store.tasks.clear(); master_server.store.results.clear()
        master_server.registry.workers.clear(); master_server.jobs.clear()
        master_server.failure_injections.clear()
        master_server.repository.payload = lambda params: {"records": ROWS}
        self.client = master_server.app.test_client()
        self.headers = ({"X-DLUMEN-Token": master_server.TOKEN} if master_server.TOKEN else {})

    def test_end_to_end_rest_contract(self):
        self.assertEqual(200, self.client.post("/register", headers=self.headers,
            json={"worker_id": "w1", "processes": 2}).status_code)
        job = self.client.post("/jobs", json={"start_year": 2024, "end_year": 2024,
            "months_per_task": 12, "worker_count": 1}, headers=self.headers)
        self.assertEqual(201, job.status_code)
        claim = self.client.get("/get-task/w1", headers=self.headers)
        self.assertEqual(ROWS, claim.json["task"]["payload"]["records"])
        task = claim.json["task"]; result = compute_chunk("aggregate", ROWS, {})
        submitted = self.client.post("/submit-result", json={"worker_id": "w1",
            "task_id": task["task_id"], "result": result, "metrics": {"cpu_percent": 10}}, headers=self.headers)
        self.assertTrue(submitted.json["accepted"])

    def test_reset_and_metrics(self):
        self.assertEqual(200, self.client.post("/reset", headers=self.headers).status_code)
        self.assertIn("recovery_time_seconds", self.client.get("/metrics").json)

    def test_numpy_operations(self):
        part = compute_chunk("extreme", ROWS, {"threshold": 4})
        combined = merge_results([part], "extreme")
        self.assertEqual(5.0, combined["global_mean"])
        self.assertEqual(1, len(combined["extreme_records"]))

    def test_grid_records_count_unique_months(self):
        rows = [dict(ROWS[0], row_off=0), dict(ROWS[0], row_off=64)]
        parts = [compute_chunk("aggregate", [row], {"work_factor": 2}) for row in rows]
        combined = merge_results(parts, "aggregate")
        self.assertEqual(1, combined["months"])
        self.assertEqual(4, combined["valid_pixels"])

    def test_fault_injection_requires_running_task(self):
        self.client.post("/register", headers=self.headers, json={"worker_id": "w1", "processes": 2})
        response = self.client.post("/fault/inject/w1", headers=self.headers)
        self.assertEqual(409, response.status_code)

    def test_fault_injection_delivered_by_heartbeat(self):
        self.client.post("/register", headers=self.headers, json={"worker_id": "w1", "processes": 2})
        self.client.post("/jobs", headers=self.headers, json={"start_year": 2024,
            "end_year": 2024, "months_per_task": 12, "worker_count": 1})
        self.client.get("/get-task/w1", headers=self.headers)
        injected = self.client.post("/fault/inject/w1", headers=self.headers)
        self.assertEqual(202, injected.status_code)
        heartbeat = self.client.post("/heartbeat", headers=self.headers,
            json={"worker_id": "w1", "metrics": {}})
        self.assertEqual("terminate", heartbeat.json["command"])


if __name__ == "__main__": unittest.main()
