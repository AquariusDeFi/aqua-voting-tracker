import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import IntegrityError, connections
from django.test import TransactionTestCase
from django.utils import timezone

from asgiref.sync import sync_to_async
from dateutil.parser import parse as date_parse
from stellar_sdk.client.response import Response
from stellar_sdk.exceptions import NotFoundError

from aqua_voting_tracker.voting.models import Vote
from aqua_voting_tracker.voting.parser import parse_claimable_balance
from aqua_voting_tracker.voting.tasks import (
    CLAIM_BACK_CURSOR_CACHE_KEY,
    CLAIMABLE_BALANCES_CURSOR_CACHE_KEY,
    task_load_new_claimable_balances,
    task_update_claim_back_time,
)
from aqua_voting_tracker.voting.tests.factories import VoteFactory


class LoadNewClaimableBalancesTests(TransactionTestCase):
    @staticmethod
    def _claimable_balance(sequence):
        balance_id = '00000000' + f'{sequence:064x}'
        return {
            'id': balance_id,
            'asset': settings.VOTING_ASSETS[0],
            'amount': '5.0000000',
            'sponsor': 'G' + 'V' * 55,
            'last_modified_time': '2021-12-06T18:15:25Z',
            'claimants': [
                {
                    'destination': 'G' + 'M' * 55,
                    'predicate': {
                        'not': {
                            'unconditional': True,
                        },
                    },
                },
                {
                    'destination': 'G' + 'V' * 55,
                    'predicate': {
                        'not': {
                            'abs_before': '2022-06-06T18:15:25Z',
                        },
                    },
                },
            ],
            'paging_token': str(sequence),
        }

    @patch('aqua_voting_tracker.voting.tasks.Server')
    @patch('aqua_voting_tracker.voting.tasks.load_all_records')
    @patch('aqua_voting_tracker.voting.tasks.cache')
    def test_existing_duplicate_does_not_drop_new_vote(self, cache, load_all_records, _server):
        duplicate = self._claimable_balance(1)
        new_vote = self._claimable_balance(2)
        parse_claimable_balance(duplicate).save()
        cache.get.return_value = 'cursor-before-page'
        load_all_records.return_value = [duplicate, new_vote]

        task_load_new_claimable_balances.run()

        self.assertEqual(
            set(Vote.objects.values_list('balance_id', flat=True)),
            {duplicate['id'], new_vote['id']},
        )
        cache.set.assert_called_once_with(
            CLAIMABLE_BALANCES_CURSOR_CACHE_KEY,
            new_vote['paging_token'],
            None,
        )

    @patch('aqua_voting_tracker.voting.tasks.Server')
    @patch('aqua_voting_tracker.voting.tasks.load_all_records')
    @patch('aqua_voting_tracker.voting.tasks.cache')
    def test_database_failure_propagates_without_advancing_cursor(self, cache, load_all_records, _server):
        invalid_vote = self._claimable_balance(1)
        invalid_vote['sponsor'] = settings.VOTING_BALANCES_DISTRIBUTOR
        invalid_vote['claimants'][1]['destination'] = None
        cache.get.return_value = 'cursor-before-page'
        load_all_records.return_value = [invalid_vote]

        with self.assertRaises(IntegrityError):
            task_load_new_claimable_balances.run()

        self.assertFalse(Vote.objects.exists())
        cache.set.assert_not_called()

    @patch('aqua_voting_tracker.voting.tasks.Server')
    @patch('aqua_voting_tracker.voting.tasks.load_all_records')
    @patch('aqua_voting_tracker.voting.tasks.cache')
    def test_cache_failure_replays_committed_vote_and_then_advances_cursor(self, cache, load_all_records, _server):
        claimable_balance = self._claimable_balance(1)
        cursor = {'value': 'cursor-before-page'}
        set_attempts = 0

        cache.get.side_effect = lambda key, default=None: cursor['value']

        def set_cursor(key, value, timeout):
            nonlocal set_attempts
            set_attempts += 1
            if set_attempts == 1:
                raise RuntimeError('cache unavailable')
            cursor['value'] = value

        cache.set.side_effect = set_cursor
        load_all_records.return_value = [claimable_balance]

        with self.assertRaisesRegex(RuntimeError, 'cache unavailable'):
            task_load_new_claimable_balances.run()

        self.assertEqual(Vote.objects.filter(balance_id=claimable_balance['id']).count(), 1)
        self.assertEqual(cursor['value'], 'cursor-before-page')

        task_load_new_claimable_balances.run()

        self.assertEqual(Vote.objects.filter(balance_id=claimable_balance['id']).count(), 1)
        self.assertEqual(cursor['value'], claimable_balance['paging_token'])

    @patch('aqua_voting_tracker.voting.tasks.Server')
    @patch('aqua_voting_tracker.voting.tasks.load_all_records')
    @patch('aqua_voting_tracker.voting.tasks.cache')
    def test_competing_and_repeated_ingestion_creates_no_duplicates_or_loss(
            self, cache, load_all_records, _server):
        first_vote = self._claimable_balance(1)
        second_vote = self._claimable_balance(2)
        cache.get.return_value = None

        def records_with_competing_insert():
            yield first_vote
            parse_claimable_balance(first_vote).save()
            yield second_vote

        load_all_records.side_effect = [
            records_with_competing_insert(),
            [first_vote, second_vote],
        ]

        task_load_new_claimable_balances.run()
        task_load_new_claimable_balances.run()

        self.assertEqual(
            set(Vote.objects.values_list('balance_id', flat=True)),
            {first_vote['id'], second_vote['id']},
        )
        self.assertEqual(Vote.objects.count(), 2)


class UpdateClaimBackTimeTests(TransactionTestCase):
    def tearDown(self):
        # Votes are saved from the sync_to_async worker thread; close its connection so the test DB can be dropped.
        asyncio.run(sync_to_async(connections.close_all)())
        super().tearDown()

    @staticmethod
    def _horizon(responses):
        server = MagicMock()

        def for_claimable_balance(balance_id):
            builder = MagicMock()
            builder.order.return_value.limit.return_value.call = AsyncMock(side_effect=[responses[balance_id]])
            return builder

        server.operations.return_value.for_claimable_balance.side_effect = for_claimable_balance
        return server

    @patch('aqua_voting_tracker.voting.tasks.ServerAsync')
    @patch('aqua_voting_tracker.voting.tasks.cache')
    def test_vote_without_retained_history_does_not_block_bunch(self, cache, server_async):
        locked_until = timezone.now() - timezone.timedelta(days=1)
        not_found_vote = VoteFactory(locked_until=locked_until)
        empty_history_vote = VoteFactory(locked_until=locked_until)
        claimed_vote = VoteFactory(locked_until=locked_until)
        cache.get.return_value = None
        server_async.return_value.__aenter__.return_value = self._horizon({
            not_found_vote.balance_id: NotFoundError(Response(404, '{"status": 404}', {}, '')),
            empty_history_vote.balance_id: {'_embedded': {'records': []}},
            claimed_vote.balance_id: {'_embedded': {'records': [
                {'type': 'claim_claimable_balance', 'created_at': '2022-06-07T10:00:00Z'},
            ]}},
        })

        task_update_claim_back_time.run()

        for vote in (not_found_vote, empty_history_vote, claimed_vote):
            vote.refresh_from_db()
        self.assertIsNone(not_found_vote.claimed_back_at)
        self.assertIsNone(empty_history_vote.claimed_back_at)
        self.assertEqual(claimed_vote.claimed_back_at, date_parse('2022-06-07T10:00:00Z'))
        cache.delete.assert_called_once_with(CLAIM_BACK_CURSOR_CACHE_KEY)
