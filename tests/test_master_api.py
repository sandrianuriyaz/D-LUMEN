import os
import unittest

os.environ.setdefault("DLUMEN_TOKEN", "test-token")
from parallel import master_app


class MasterApiTests(unittest.TestCase):
    def setUp(self):
        master_app.registry.workers.clear(); master_app.store.tasks.clear(); master_app.store.results.clear()
        master_app.jobs.clear()
        self.client = master_app.app.test_client(); self.headers = {"X-DLUMEN-Token": "test-token"}

    def test_registration_heartbeat_and_job(self):
        response = self.client.post("/api/register", headers=self.headers,
            json={"worker_id": "w1", "port": 5002, "processes": 2})
        self.assertEqual(200, response.status_code)
        self.assertEqual(200, self.client.post("/api/heartbeat", headers=self.headers,
            json={"worker_id": "w1", "metrics": {"cpu_percent": 5}}).status_code)
        job = self.client.post("/api/jobs", headers=self.headers,
            json={"start_year": 2020, "end_year": 2020, "months_per_task": 6, "scheduling": "static"})
        self.assertEqual(201, job.status_code); self.assertEqual(2, job.json["count"])
        claim = self.client.post("/api/tasks/claim", headers=self.headers, json={"worker_id": "w1"})
        task = claim.json["task"]
        done = self.client.post(f"/api/tasks/{task['task_id']}/result", headers=self.headers,
            json={"worker_id": "w1", "result": {"months": 6, "valid_pixels": 10, "sum_radiance": 20}})
        self.assertTrue(done.json["accepted"])
        status = self.client.get("/api/status", query_string={"job_id": job.json["job_id"]})
        self.assertEqual(50.0, status.json["progress"])

    def test_worker_limit_and_partition_metadata(self):
        for worker, partitions in (("w1", ["2020"]), ("w2", ["2021"])):
            self.client.post("/api/register", headers=self.headers,
                json={"worker_id": worker, "port": 5002, "partitions": partitions})
        job = self.client.post("/api/jobs", headers=self.headers,
            json={"start_year": 2020, "end_year": 2020, "worker_count": 1})
        self.assertEqual(201, job.status_code); self.assertEqual(["w1"], job.json["worker_ids"])

    def test_auth_required(self):
        self.assertEqual(401, self.client.post("/api/jobs", json={}).status_code)

    def test_dashboard_has_demo_controls(self):
        response = self.client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Jalankan Query", response.data)
        self.assertIn(b"Fault Recovery", response.data)
        self.assertNotIn(b"test-token", response.data)


if __name__ == "__main__": unittest.main()
