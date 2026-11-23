import time
import unittest

from parallel.core import Task, TaskStatus, TaskStore, WorkerRegistry, aggregate_results, make_tasks


class CoreTests(unittest.TestCase):
    def test_decomposition_unique_non_overlapping(self):
        tasks = make_tasks("aggregate", 2020, 2021, 3)
        self.assertEqual(8, len(tasks))
        self.assertEqual(len(tasks), len({t.partition_id for t in tasks}))

    def test_claim_complete_and_duplicate_prevention(self):
        store = TaskStore(); task = Task("aggregate", {}, "p1"); store.add([task])
        self.assertEqual(task.task_id, store.claim("w1").task_id)
        self.assertTrue(store.complete(task.task_id, "w1", {"months": 1}))
        self.assertFalse(store.complete(task.task_id, "w1", {"months": 2}))

    def test_retry_requeue_and_limit(self):
        store = TaskStore(max_retries=1); task = Task("aggregate", {}, "p1"); store.add([task])
        store.claim("w1"); store.fail(task.task_id, "boom")
        self.assertEqual(TaskStatus.RETRYING, task.status)
        self.assertIsNotNone(store.claim("w2")); store.fail(task.task_id, "again")
        self.assertEqual(TaskStatus.FAILED, task.status)

    def test_partition_availability(self):
        store = TaskStore(); store.add([Task("aggregate", {}, "2020", ["w2"])])
        self.assertIsNone(store.claim("w1", {"2020"}))
        self.assertIsNone(store.claim("w2", {"2021"}))
        self.assertIsNotNone(store.claim("w2", {"2020"}))

    def test_static_preference_can_fail_over_to_replica(self):
        task = Task("aggregate", {"_static_worker": "w1"}, "p", ["w1", "w2"])
        store = TaskStore(); store.add([task])
        self.assertIsNone(store.claim("w2", {"p"}))
        store.claim("w1", {"p"}); store.recover_worker("w1")
        self.assertIsNotNone(store.claim("w2", {"p"}))

    def test_task_timeout(self):
        store = TaskStore(); task = Task("aggregate", {}, "p"); store.add([task]); store.claim("w")
        task.started_at = time.time()-10
        self.assertEqual([task.task_id], store.expire(1))

    def test_offline_and_recovery(self):
        registry = WorkerRegistry(.01); registry.register("w1", "127.0.0.1", {"port": 1})
        store = TaskStore(); task = Task("aggregate", {}, "p"); store.add([task]); store.claim("w1")
        time.sleep(.02); offline = registry.refresh()
        self.assertEqual(["w1"], offline); self.assertEqual([task.task_id], store.recover_worker("w1"))

    def test_heartbeat_reconnect(self):
        registry = WorkerRegistry(.01); registry.register("w", "1", {})
        time.sleep(.02); registry.refresh(); self.assertFalse(registry.snapshot()[0]["online"])
        self.assertTrue(registry.heartbeat("w", {"cpu_percent": 2})); self.assertTrue(registry.snapshot()[0]["online"])

    def test_weighted_global_aggregation_and_empty(self):
        value = aggregate_results([{"months": 1, "valid_pixels": 2, "sum_radiance": 10,
             "min_radiance": 1, "max_radiance": 6}, {"months": 1, "valid_pixels": 8,
             "sum_radiance": 16, "min_radiance": 2, "max_radiance": 5}])
        self.assertEqual(2.6, value["global_mean"]); self.assertEqual(1, value["min_radiance"])
        self.assertIsNone(aggregate_results([])["global_mean"])


if __name__ == "__main__": unittest.main()
