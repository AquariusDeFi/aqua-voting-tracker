from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from aqua_voting_tracker.voting.models import VotingSnapshot, VotingSnapshotAsset


AST = VotingSnapshotAsset.Direction
WHITELISTED_URL = '/api/voting-snapshot/whitelisted/'


class WhitelistedSnapshotEndpointTestCase(TestCase):
    def _make_snapshot(self, market_key, voting_amount, timestamp, *, whitelisted_for_rewards, rank=1):
        return VotingSnapshot.objects.create(
            market_key=market_key,
            rank=rank,
            votes_value=Decimal('10'),
            voting_amount=voting_amount,
            upvote_value=Decimal('10'),
            downvote_value=Decimal('0'),
            adjusted_votes_value=Decimal('10'),
            timestamp=timestamp,
            extra={},
            whitelisted_for_rewards=whitelisted_for_rewards,
        )

    def _make_asset(self, snapshot, asset, direction, votes_sum='5', votes_count=2):
        return VotingSnapshotAsset.objects.create(
            snapshot=snapshot,
            asset=asset,
            direction=direction,
            votes_sum=Decimal(votes_sum),
            votes_count=votes_count,
        )

    # ── contract ───────────────────────────────────────────────────────────────

    def test_whitelisted_endpoint_contract(self):
        """
        GET returns 200, a paginated envelope, only *latest* whitelisted rows
        ordered by -voting_amount, and includes whitelisted_for_rewards plus
        serialized VotingSnapshotAsset data under ``extra``.
        """
        old_ts = timezone.now() - timezone.timedelta(hours=2)
        latest_ts = timezone.now()

        # Old whitelisted — should be excluded because not latest timestamp.
        self._make_snapshot('old-whitelisted', 999, old_ts, whitelisted_for_rewards=True)

        # Latest BUT not whitelisted — should be excluded.
        self._make_snapshot('latest-not-whitelisted', 100, latest_ts, whitelisted_for_rewards=False)

        # Latest whitelisted, low voting amount (should sort second).
        low = self._make_snapshot('latest-whitelisted-low', 3, latest_ts, whitelisted_for_rewards=True)

        # Latest whitelisted, high voting amount (should sort first).
        high = self._make_snapshot('latest-whitelisted-high', 8, latest_ts, whitelisted_for_rewards=True)

        # Attach one upvote asset to prove asset serialisation.
        self._make_asset(high, 'VOTE:X', AST.UP, votes_sum='4', votes_count=2)
        self._make_asset(high, 'VOTE:Y', AST.DOWN, votes_sum='1', votes_count=1)

        response = self.client.get(WHITELISTED_URL)

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Pagination envelope.
        for key in ('count', 'next', 'previous', 'results'):
            self.assertIn(key, data)

        self.assertEqual(data['count'], 2)

        results = data['results']
        self.assertEqual(len(results), 2)

        # Order: highest voting_amount first.
        self.assertEqual(results[0]['market_key'], 'latest-whitelisted-high')
        self.assertEqual(results[0]['voting_amount'], 8)
        self.assertEqual(results[1]['market_key'], 'latest-whitelisted-low')
        self.assertEqual(results[1]['voting_amount'], 3)

        # whitelisted_for_rewards is present in the serialized row.
        for r in results:
            self.assertIn('whitelisted_for_rewards', r)
            self.assertTrue(r['whitelisted_for_rewards'])

        # Asset annotations are serialized under extra.
        high_extra = results[0]['extra']
        self.assertIn('upvote_assets', high_extra)
        self.assertIn('downvote_assets', high_extra)
        self.assertEqual(len(high_extra['upvote_assets']), 1)
        self.assertEqual(high_extra['upvote_assets'][0]['asset'], 'VOTE:X')
        self.assertEqual(len(high_extra['downvote_assets']), 1)
        self.assertEqual(high_extra['downvote_assets'][0]['asset'], 'VOTE:Y')

        # Snapshot without assets gets empty lists (still present because of
        # annotate_assets prefetch).
        low_extra = results[1]['extra']
        self.assertIn('upvote_assets', low_extra)
        self.assertEqual(low_extra['upvote_assets'], [])
        self.assertIn('downvote_assets', low_extra)
        self.assertEqual(low_extra['downvote_assets'], [])

    # ── pagination ─────────────────────────────────────────────────────────────

    def test_pagination_limit_param(self):
        """?limit=1 returns one result while count reflects total matched rows."""
        timestamp = timezone.now()

        self._make_snapshot('a', 30, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('b', 20, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('c', 10, timestamp, whitelisted_for_rewards=True)

        response = self.client.get(WHITELISTED_URL + '?limit=1')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['count'], 3)
        self.assertEqual(len(data['results']), 1)
        self.assertIsNotNone(data['next'])
        self.assertIsNone(data['previous'])

    # ── empty ──────────────────────────────────────────────────────────────────

    def test_empty_when_no_whitelisted_latest_rows(self):
        """No latest whitelisted rows → count 0, empty results list."""
        timestamp = timezone.now()

        self._make_snapshot('a', 10, timestamp, whitelisted_for_rewards=False)
        self._make_snapshot('b', 20, timestamp, whitelisted_for_rewards=False)

        response = self.client.get(WHITELISTED_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['count'], 0)
        self.assertEqual(data['results'], [])
        self.assertIsNone(data['next'])
        self.assertIsNone(data['previous'])
