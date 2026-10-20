import unittest

import guard_engine


class GuardEngineTests(unittest.TestCase):
    def setUp(self):
        if guard_engine.cp_model is None:
            self.skipTest("OR-Tools must be installed to run CP-SAT tests")

    def test_full_schedule_respects_balance(self):
        payload = {
            "seconds": 2,
            "teachers": [{"id": i, "subjectId": ""} for i in range(1, 5)],
            "tasks": [
                {"se": {"id": "s1", "date": "2026-11-01", "start": "09:00", "end": "11:00"}, "mins": 120, "role": "guard", "subjects": []},
                {"se": {"id": "s1", "date": "2026-11-01", "start": "09:00", "end": "11:00"}, "mins": 120, "role": "guard", "subjects": []},
                {"se": {"id": "s2", "date": "2026-11-02", "start": "09:00", "end": "11:00"}, "mins": 120, "role": "guard", "subjects": []},
                {"se": {"id": "s2", "date": "2026-11-02", "start": "09:00", "end": "11:00"}, "mins": 120, "role": "guard", "subjects": []},
            ],
            "rules": {"maxPerDay": 2, "avoidConsecutiveDay": False, "subjectTeacherRule": "must"},
            "exclusions": [],
            "dayIndex": {"2026-11-01": 0, "2026-11-02": 1},
        }
        result = guard_engine.solve_batch(payload)
        self.assertTrue(result.get("ok"), result)
        best = result["best"]
        self.assertEqual(len(best["assignments"]), 4)
        self.assertFalse(best["unfilled"])
        self.assertLessEqual(best["metrics"]["loadSpread"], 1)
        self.assertLessEqual(best["metrics"]["daySpread"], 1)
        self.assertLessEqual(best["metrics"]["minuteSpread"], 240)

    def test_reserve_must_not_be_alone(self):
        payload = {
            "seconds": 2,
            "teachers": [{"id": "A", "subjectId": ""}, {"id": "B", "subjectId": ""}],
            "tasks": [
                {"se": {"id": "s1", "date": "2026-11-01", "start": "09:00", "end": "10:00"}, "mins": 60, "role": "guard", "subjects": []},
                {"se": {"id": "s1", "date": "2026-11-01", "start": "11:00", "end": "12:00"}, "mins": 60, "role": "reserve", "subjects": []},
                {"se": {"id": "s2", "date": "2026-11-02", "start": "09:00", "end": "10:00"}, "mins": 60, "role": "guard", "subjects": []},
            ],
            "rules": {"maxPerDay": 2, "avoidConsecutiveDay": False, "subjectTeacherRule": "must"},
            "exclusions": [],
            "dayIndex": {"2026-11-01": 0, "2026-11-02": 1},
        }
        result = guard_engine.solve_batch(payload)
        self.assertTrue(result.get("ok"), result)
        assignments = result["best"]["assignments"]
        reserve_teacher = assignments[1]
        self.assertIn(reserve_teacher, assignments[0:1])
        self.assertEqual(result["best"]["metrics"]["loneReserves"], 0)


if __name__ == "__main__":
    unittest.main()
