from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from aqua_voting_tracker.voting.models import VotingSnapshot, VotingSnapshotAsset


AST = VotingSnapshotAsset.Direction
TOP_VOTED_URL = '/api/voting-snapshot/top-voted/'
TOP_VOLUME_URL = '/api/voting-snapshot/top-volume/'


class WhitelistedFilterTestCase(TestCase):
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

    # ── top-voted with whitelisted_for_rewards=true ─────────────────────────────

    def test_top_voted_whitelisted_true_contract(self):
        """
        GET /api/voting-snapshot/top-voted/?whitelisted_for_rewards=true returns
        a paginated envelope with only the *latest* whitelisted rows, ordered by
        -voting_amount, and includes whitelisted_for_rewards plus serialized
        VotingSnapshotAsset data under ``extra``.
        """
        old_ts = timezone.now() - timezone.timedelta(hours=2)
        latest_ts = timezone.now()

        # Old whitelisted — excluded (not latest timestamp).
        self._make_snapshot('old-whitelisted', 999, old_ts, whitelisted_for_rewards=True)

        # Latest BUT not whitelisted — excluded.
        self._make_snapshot('latest-not-whitelisted', 100, latest_ts, whitelisted_for_rewards=False)

        # Latest whitelisted, low voting amount (should sort second).
        low = self._make_snapshot('latest-whitelisted-low', 3, latest_ts, whitelisted_for_rewards=True)

        # Latest whitelisted, high voting amount (should sort first).
        high = self._make_snapshot('latest-whitelisted-high', 8, latest_ts, whitelisted_for_rewards=True)

        # Attach one upvote and one downvote asset to prove asset serialisation.
        self._make_asset(high, 'VOTE:X', AST.UP, votes_sum='4', votes_count=2)
        self._make_asset(high, 'VOTE:Y', AST.DOWN, votes_sum='1', votes_count=1)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=true')

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Pagination envelope.
        for key in ('count', 'next', 'previous', 'results'):
            self.assertIn(key, data)

        self.assertEqual(data['count'], 2)

        results = data['results']
        self.assertEqual(len(results), 2)

        # Order: highest voting_amount first (TopVotedSnapshotView.sort = -voting_amount).
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

        # Snapshot without assets gets empty lists.
        low_extra = results[1]['extra']
        self.assertIn('upvote_assets', low_extra)
        self.assertEqual(low_extra['upvote_assets'], [])
        self.assertIn('downvote_assets', low_extra)
        self.assertEqual(low_extra['downvote_assets'], [])

    # ── top-volume with whitelisted_for_rewards=true ────────────────────────────

    def test_top_volume_whitelisted_true(self):
        """Query param also works on /api/voting-snapshot/top-volume/."""
        timestamp = timezone.now()

        hi = self._make_snapshot('whitelisted-hi', 50, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('not-whitelisted', 30, timestamp, whitelisted_for_rewards=False)

        response = self.client.get(TOP_VOLUME_URL + '?whitelisted_for_rewards=true')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['market_key'], 'whitelisted-hi')
        self.assertTrue(data['results'][0]['whitelisted_for_rewards'])

    # ── whitelisted_for_rewards=false ───────────────────────────────────────────

    def test_whitelisted_false_returns_non_whitelisted(self):
        """?whitelisted_for_rewards=false returns only non-whitelisted rows."""
        timestamp = timezone.now()

        self._make_snapshot('whitelisted-a', 50, timestamp, whitelisted_for_rewards=True)
        not_whitelisted = self._make_snapshot('not-whitelisted-b', 30, timestamp, whitelisted_for_rewards=False)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=false')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['market_key'], 'not-whitelisted-b')
        self.assertFalse(data['results'][0]['whitelisted_for_rewards'])

    # ── whitelisted_for_rewards=1 and =0 ────────────────────────────────────────

    def test_whitelisted_param_1(self):
        """?whitelisted_for_rewards=1 works like true."""
        timestamp = timezone.now()
        self._make_snapshot('a', 10, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('b', 20, timestamp, whitelisted_for_rewards=False)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=1')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['market_key'], 'a')

    def test_whitelisted_param_0(self):
        """?whitelisted_for_rewards=0 works like false."""
        timestamp = timezone.now()
        self._make_snapshot('a', 10, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('b', 20, timestamp, whitelisted_for_rewards=False)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=0')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['market_key'], 'b')

    # ── case-insensitive values ─────────────────────────────────────────────────

    def test_whitelisted_param_true_case_insensitive(self):
        """?whitelisted_for_rewards=TRUE works (case-insensitive)."""
        timestamp = timezone.now()
        self._make_snapshot('a', 10, timestamp, whitelisted_for_rewards=True)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=TRUE')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)

    # ── pagination ─────────────────────────────────────────────────────────────

    def test_pagination_limit_param(self):
        """?limit=1 returns one result while count reflects total matched rows."""
        timestamp = timezone.now()

        self._make_snapshot('a', 30, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('b', 20, timestamp, whitelisted_for_rewards=True)
        self._make_snapshot('c', 10, timestamp, whitelisted_for_rewards=True)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=true&limit=1')
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

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=true')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['count'], 0)
        self.assertEqual(data['results'], [])
        self.assertIsNone(data['next'])
        self.assertIsNone(data['previous'])

    # ── invalid value ──────────────────────────────────────────────────────────

    def test_invalid_whitelisted_value_returns_400(self):
        """/api/voting-snapshot/top-voted/?whitelisted_for_rewards=maybe returns 400."""
        timestamp = timezone.now()
        self._make_snapshot('a', 10, timestamp, whitelisted_for_rewards=True)

        response = self.client.get(TOP_VOTED_URL + '?whitelisted_for_rewards=maybe')
        self.assertEqual(response.status_code, 400)
