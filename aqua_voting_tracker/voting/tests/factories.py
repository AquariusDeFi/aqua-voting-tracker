import random
from decimal import Decimal

from django.utils import timezone

import factory
import factory.fuzzy

import aqua_voting_tracker.utils.tests  # NoQA: F401
from aqua_voting_tracker.voting.models import Vote
from aqua_voting_tracker.voting.services.snapshot_creation import SnapshotAssetRecord, SnapshotRecord


class VoteFactory(factory.django.DjangoModelFactory):
    balance_id = factory.Faker('stellar_claimable_balance_id')

    voting_account = factory.Faker('stellar_public_key')
    market_key = factory.Faker('stellar_public_key')

    amount = factory.fuzzy.FuzzyDecimal(100)
    asset = 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6'

    locked_at = factory.fuzzy.FuzzyDateTime(timezone.now() - timezone.timedelta(days=10))
    locked_until = factory.LazyAttribute(lambda v: v.locked_at + timezone.timedelta(days=random.randint(1, 10)))

    class Meta:
        model = Vote


class SnapshotAssetRecordFactory(factory.Factory):
    asset = 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6'

    votes_sum = '5'
    votes_count = 1

    class Meta:
        model = SnapshotAssetRecord


class SnapshotRecordFactory(factory.Factory):
    market_key = factory.LazyAttribute(lambda sr: sr.upvote_account_id)

    upvote_account_id = factory.Faker('stellar_public_key')
    downvote_account_id = factory.Faker('stellar_public_key')

    voting_boost = Decimal(0)

    upvote_value = factory.fuzzy.FuzzyDecimal(10)
    downvote_value = factory.fuzzy.FuzzyDecimal(0)

    voting_amount = factory.fuzzy.FuzzyInteger(1)
    votes_value = factory.LazyAttribute(lambda sr: sr.upvote_value - sr.downvote_value)

    upvote_assets = factory.LazyAttribute(lambda sr: [SnapshotAssetRecordFactory(votes_sum=str(sr.upvote_value),
                                                                                  votes_count=sr.voting_amount)])
    downvote_assets = factory.LazyAttribute(lambda sr: [])

    adjusted_votes_value = factory.LazyAttribute(lambda sr: sr.votes_value)
    rank = 1

    whitelisted_for_rewards = False

    class Meta:
        model = SnapshotRecord
