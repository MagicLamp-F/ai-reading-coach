import unittest

from app.telegram import parse_feedback_updates


class TelegramTests(unittest.TestCase):
    def test_parse_feedback_callback(self):
        offset, callbacks = parse_feedback_updates(
            [
                {
                    "update_id": 10,
                    "callback_query": {
                        "id": "abc",
                        "data": "fb:42:go_deeper",
                        "message": {"text": "book"},
                    },
                }
            ]
        )
        self.assertEqual(offset, 11)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].recommendation_id, 42)
        self.assertEqual(callbacks[0].feedback_type, "go_deeper")


if __name__ == "__main__":
    unittest.main()

