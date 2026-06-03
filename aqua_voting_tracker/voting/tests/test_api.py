from decimal import Decimal

from django.test import RequestFactory, TestCase
from django.utils import timezone

from aqua_voting_tracker.voting.api import WhitelistedSnapshotView
from aqua_voting_tracker.voting.models import VotingSnapshot


class WhitelistedSnapshotViewTestCase(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def create_snapshot(self, market_key, voting_amount, timestamp, rank=1, whitelisted_for_rewards=False):
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

    def test_get_queryset_filters_whitelisted_and_orders_by_voting_amount_desc(self):
        old_timestamp = timezone.now() - timezone.timedelta(hours=1)
        latest_timestamp = timezone.now()

        # old whitelisted — should not appear (not from the latest snapshot)
        self.create_snapshot('old-whitelisted-market', 999, old_timestamp, whitelisted_for_rewards=True)
        # latest whitelisted, low voting amount
        self.create_snapshot('latest-whitelisted-low', 3, latest_timestamp, whitelisted_for_rewards=True)
        # latest NOT whitelisted — should be filtered out
        self.create_snapshot('latest-not-whitelisted', 100, latest_timestamp, whitelisted_for_rewards=False)
        # latest whitelisted, high voting amount
        self.create_snapshot('latest-whitelisted-high', 8, latest_timestamp, whitelisted_for_rewards=True)

        view = WhitelistedSnapshotView()
        view.request = self.request_factory.get('/voting-snapshot/whitelisted/')

        queryset = view.get_queryset()

        self.assertQuerysetEqual(
            queryset.values_list('market_key', flat=True),
            ['latest-whitelisted-high', 'latest-whitelisted-low'],
            transform=lambda market_key: market_key,
        )

    def test_get_queryset_returns_empty_when_no_whitelisted_snapshots(self):
        latest_timestamp = timezone.now()

        self.create_snapshot('market-1', 10, latest_timestamp, whitelisted_for_rewards=False)
        self.create_snapshot('market-2', 20, latest_timestamp, whitelisted_for_rewards=False)

        view = WhitelistedSnapshotView()
        view.request = self.request_factory.get('/voting-snapshot/whitelisted/')

        queryset = view.get_queryset()

        self.assertQuerysetEqual(queryset, [])
