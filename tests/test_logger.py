"""Tests for the timestamps that mongodb.logger adds to tutor message pairs.

The collection is a stub, so no database or secrets are needed.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from mongodb.logger import UserLogger


def make_logger(existing_doc):
    """A UserLogger whose conversations collection is a stub returning existing_doc."""
    logger = UserLogger.__new__(UserLogger)
    logger.conversations = MagicMock()
    logger.conversations.find_one.return_value = existing_doc
    return logger


class LogConversationTimestampTests(unittest.TestCase):
    def assert_stamped(self, pairs, sent):
        self.assertEqual(len(pairs), len(sent))
        now = datetime.now(timezone.utc)
        for pair, original in zip(pairs, sent):
            self.assertEqual(len(pair), 3)
            self.assertEqual(pair[:2], original)
            self.assertEqual(pair[2].utcoffset(), timedelta(0))
            self.assertLess(abs(now - pair[2]), timedelta(seconds=10))

    def test_pairs_appended_to_an_existing_conversation_are_stamped(self):
        existing = {"user_id": "u", "conversations": [{"module": "1", "topic": "T", "conversation": []}]}
        logger = make_logger(existing)
        sent = [["hello", "hi"], ["", "an opening question"]]

        logger.log_conversation("u", "1", "T", sent)

        update = logger.conversations.update_one.call_args.args[1]
        self.assert_stamped(update["$push"]["conversations.$.conversation"]["$each"], sent)

    def test_pairs_for_a_new_topic_are_stamped(self):
        existing = {"user_id": "u", "conversations": [{"module": "1", "topic": "Other", "conversation": []}]}
        logger = make_logger(existing)
        sent = [["hello", "hi"]]

        logger.log_conversation("u", "1", "T", sent)

        update = logger.conversations.update_one.call_args.args[1]
        self.assert_stamped(update["$push"]["conversations"]["conversation"], sent)

    def test_pairs_for_a_new_user_are_stamped(self):
        logger = make_logger(None)
        sent = [["hello", "hi"]]

        logger.log_conversation("u", "1", "T", sent)

        document = logger.conversations.insert_one.call_args.args[0]
        self.assert_stamped(document["conversations"][0]["conversation"], sent)

    def test_the_callers_list_is_not_changed(self):
        logger = make_logger(None)
        sent = [["hello", "hi"]]

        logger.log_conversation("u", "1", "T", sent)

        self.assertEqual(sent, [["hello", "hi"]])


if __name__ == "__main__":
    unittest.main()
