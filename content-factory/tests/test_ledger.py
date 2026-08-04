import sqlite3
import unittest

from yula_factory.ledger import initialize_connection


class LedgerTests(unittest.TestCase):
    def test_expected_tables_exist(self):
        with sqlite3.connect(":memory:") as connection:
            initialize_connection(connection)
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        expected = {
            "assets", "production_runs", "post_performance", "strategy_weights", "learning_notes", "workflow_errors",
            "schedule_plans", "scheduled_posts", "scheduler_runs", "music_generations", "editing_style_history",
            "temporary_media_objects",
        }
        self.assertTrue(expected.issubset(tables))


if __name__ == "__main__":
    unittest.main()
