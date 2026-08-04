import unittest

from yula_factory.duration import DAILY_TARGET_SECONDS, target_duration_seconds, validate_duration


class DurationTests(unittest.TestCase):
    def test_curve_reaches_seventy_seconds(self):
        self.assertEqual(target_duration_seconds(10), 15)
        self.assertEqual(target_duration_seconds(11), 17)
        self.assertEqual(target_duration_seconds(30), 70)
        increments = [DAILY_TARGET_SECONDS[day] - DAILY_TARGET_SECONDS[day - 1] for day in range(11, 31)]
        self.assertTrue(all(value in (2, 3) for value in increments))

    def test_day_eleven_and_later_use_soft_tolerance(self):
        self.assertIsNone(validate_duration(11, 19.5))
        self.assertIsNotNone(validate_duration(11, 22))


if __name__ == "__main__":
    unittest.main()
