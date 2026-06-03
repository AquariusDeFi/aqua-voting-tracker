from decimal import Decimal
from typing import Iterable, List

from django.test import TestCase
from django.utils import timezone

from dateutil.parser import parse as date_parse

from aqua_voting_tracker.utils.tests import fake
from aqua_voting_tracker.voting.marketkeys.base import BaseMarketKeysProvider
from aqua_voting_tracker.voting.models import VotingSnapshot
from aqua_voting_tracker.voting.services.snapshot_creation import (
    SnapshotAssetRecord,
    SnapshotCreationUseCase,
    SnapshotRecord,
)
from aqua_voting_tracker.voting.tests.factories import SnapshotRecordFactory, VoteFactory


class SnapshotCreationVoteAggregationTestCase(TestCase):
    def setUp(self):
        self.use_case = SnapshotCreationUseCase(BaseMarketKeysProvider())

    def test_base_get_votes_aggregation(self):
        market_key1 = fake.stellar_public_key()
        market_key2 = fake.stellar_public_key()
        VoteFactory(
            market_key=market_key1,
            amount=Decimal(10),
            locked_at=date_parse('2024-12-06T12:00:00Z'),
        )
        VoteFactory(
            market_key=market_key1,
            amount=Decimal(20),
            locked_at=date_parse('2024-12-05T12:00:00Z'),
        )
        VoteFactory(
            market_key=market_key2,
            amount=Decimal(27),
            locked_at=date_parse('2024-12-04T12:00:00Z'),
        )

        votes_aggregation = self.use_case.get_votes_aggregation(date_parse('2024-12-06T13:00:00Z'))

        self.assertDictEqual(votes_aggregation, {
            market_key1: [{
                'market_key': market_key1,
                'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                'votes_value': Decimal(30),
                'voting_amount': 2,
            }],
            market_key2: [{
                'market_key': market_key2,
                'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                'votes_value': Decimal(27),
                'voting_amount': 1,
            }],
        })

    def test_get_votes_aggregation_with_claimed_votes(self):
        vote1 = VoteFactory(
            locked_at=date_parse('2024-12-06T12:00:00Z'),
        )
        vote2 = VoteFactory(
            locked_at=date_parse('2024-12-05T12:00:00Z'),
            locked_until=date_parse('2024-12-06T12:00:00Z'),
        )
        VoteFactory(
            locked_at=date_parse('2024-12-05T12:00:00Z'),
            locked_until=date_parse('2024-12-06T12:00:00Z'),
            claimed_back_at=date_parse('2024-12-06T12:30:00Z'),
        )

        votes_aggregation = self.use_case.get_votes_aggregation(date_parse('2024-12-06T13:00:00Z'))

        self.assertDictEqual(votes_aggregation, {
            vote1.market_key: [{
                'market_key': vote1.market_key,
                'asset': vote1.asset,
                'votes_value': vote1.amount,
                'voting_amount': 1,
            }],
            vote2.market_key: [{
                'market_key': vote2.market_key,
                'asset': vote2.asset,
                'votes_value': vote2.amount,
                'voting_amount': 1,
            }],
        })

    def test_get_votes_aggregation_with_several_assets(self):
        market_key = fake.stellar_public_key()
        vote1 = VoteFactory(
            market_key=market_key,
            asset='VOTE1:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
        )
        vote2 = VoteFactory(
            market_key=market_key,
            asset='VOTE2:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
        )

        votes_aggregation = self.use_case.get_votes_aggregation(timezone.now())

        self.assertDictEqual(votes_aggregation, {
            market_key: [
                {
                    'market_key': market_key,
                    'asset': vote1.asset,
                    'votes_value': vote1.amount,
                    'voting_amount': 1,
                },
                {
                    'market_key': market_key,
                    'asset': vote2.asset,
                    'votes_value': vote2.amount,
                    'voting_amount': 1,
                },
            ]
        })


class TestMarketKeysProvider(BaseMarketKeysProvider):
    def __init__(self, markets_data: Iterable[dict]):
        markets_data = [
            {
                'account_id': md['upvote'],
                'upvote_account_id': md['upvote'],
                'downvote_account_id': md['downvote'],
                'voting_boost': md.get('voting_boost', 0),
                'downvote_immunity': md.get('downvote_immunity', False),
                'whitelisted_for_rewards': md.get('whitelisted_for_rewards', False),
            } for md in markets_data
        ]
        self.markets_data_by_upvote = {
            md['upvote_account_id']: md for md in markets_data
        }
        self.markets_data_by_downvote = {
            md['downvote_account_id']: md for md in markets_data
        }

    def get_multiple(self, account_ids: Iterable[str]) -> List[dict]:
        result = dict()
        for account in account_ids:
            if account in self.markets_data_by_upvote:
                md = self.markets_data_by_upvote[account]
                result[md['account_id']] = md
            if account in self.markets_data_by_downvote:
                md = self.markets_data_by_downvote[account]
                result[md['account_id']] = md

        return list(result.values())


class SnapshotCreationMarketsDataTestCase(TestCase):
    def setUp(self):
        upvote_account1 = fake.stellar_public_key()
        downvote_account1 = fake.stellar_public_key()
        upvote_account2 = fake.stellar_public_key()
        downvote_account2 = fake.stellar_public_key()

        self.snapshot_record1 = SnapshotRecord(
            market_key=upvote_account1,
            upvote_account_id=upvote_account1,
            downvote_account_id=downvote_account1,
            voting_boost=Decimal(0.3),
            downvote_immunity=False,
        )
        self.snapshot_record2 = SnapshotRecord(
            market_key=upvote_account2,
            upvote_account_id=upvote_account2,
            downvote_account_id=downvote_account2,
            voting_boost=Decimal(0),
            downvote_immunity=True,
        )

        market_keys_provider = TestMarketKeysProvider([
            {
                'upvote': upvote_account1,
                'downvote': downvote_account1,
                'voting_boost': 0.3,
                'downvote_immunity': False,
            },
            {
                'upvote': upvote_account2,
                'downvote': downvote_account2,
                'voting_boost': 0,
                'downvote_immunity': True,
            },
        ])
        self.use_case = SnapshotCreationUseCase(market_keys_provider)

    def test_base_prepare_markets_data(self):
        snapshot = list(self.use_case.get_markets_data([
            self.snapshot_record1.upvote_account_id,
            self.snapshot_record2.upvote_account_id,
        ]))

        self.assertListEqual(snapshot, [
            self.snapshot_record1,
            self.snapshot_record2,
        ])

    def test_prepare_markets_data_with_downvote(self):
        snapshot = list(self.use_case.get_markets_data([
            self.snapshot_record1.upvote_account_id,
            self.snapshot_record2.downvote_account_id,
            self.snapshot_record2.downvote_account_id,
        ]))

        self.assertListEqual(snapshot, [
            self.snapshot_record1,
            self.snapshot_record2,
        ])

    def test_prepare_markets_data_with_not_exist(self):
        snapshot = list(self.use_case.get_markets_data([
            self.snapshot_record1.upvote_account_id,
            fake.stellar_public_key(),
        ]))

        self.assertListEqual(snapshot, [
            self.snapshot_record1,
        ])

    def test_prepare_markets_data_copies_whitelisted_for_rewards(self):
        upvote = fake.stellar_public_key()
        downvote = fake.stellar_public_key()

        provider = TestMarketKeysProvider([{
            'upvote': upvote,
            'downvote': downvote,
            'whitelisted_for_rewards': True,
        }])
        use_case = SnapshotCreationUseCase(provider)

        snapshot = list(use_case.get_markets_data([upvote]))

        self.assertEqual(len(snapshot), 1)
        self.assertTrue(snapshot[0].whitelisted_for_rewards)

    def test_prepare_markets_data_whitelisted_defaults_to_false(self):
        upvote = fake.stellar_public_key()
        downvote = fake.stellar_public_key()

        provider = TestMarketKeysProvider([{
            'upvote': upvote,
            'downvote': downvote,
        }])
        use_case = SnapshotCreationUseCase(provider)

        snapshot = list(use_case.get_markets_data([upvote]))

        self.assertEqual(len(snapshot), 1)
        self.assertFalse(snapshot[0].whitelisted_for_rewards)


class SnapshotCreationVotesValueTestCase(TestCase):
    def setUp(self):
        self.use_case = SnapshotCreationUseCase(BaseMarketKeysProvider())

        upvote_account1 = fake.stellar_public_key()
        downvote_account1 = fake.stellar_public_key()
        upvote_account2 = fake.stellar_public_key()
        downvote_account2 = fake.stellar_public_key()

        self.snapshot_record1 = SnapshotRecord(
            market_key=upvote_account1,
            upvote_account_id=upvote_account1,
            downvote_account_id=downvote_account1,
        )
        self.snapshot_record2 = SnapshotRecord(
            market_key=upvote_account2,
            upvote_account_id=upvote_account2,
            downvote_account_id=downvote_account2,
        )

        self.snapshot = [
            self.snapshot_record1,
            self.snapshot_record2,
        ]

    def test_base_set_votes_value(self):
        snapshot = list(self.use_case.set_votes_value(self.snapshot, {
            self.snapshot_record1.upvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(10),
                    'voting_amount': 1,
                },
            ],
            self.snapshot_record2.upvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(20),
                    'voting_amount': 3,
                },
            ],
        }))

        self.assertEqual(snapshot[0].upvote_value, Decimal(10))
        self.assertEqual(snapshot[0].downvote_value, 0)
        self.assertEqual(snapshot[0].voting_amount, 1)
        self.assertEqual(snapshot[0].votes_value, Decimal(10))

        self.assertEqual(snapshot[1].upvote_value, Decimal(20))
        self.assertEqual(snapshot[1].downvote_value, 0)
        self.assertEqual(snapshot[1].voting_amount, 3)
        self.assertEqual(snapshot[1].votes_value, Decimal(20))

    def test_set_votes_value_downvote(self):
        snapshot = list(self.use_case.set_votes_value(self.snapshot, {
            self.snapshot_record1.upvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(10),
                    'voting_amount': 3,
                },
            ],
            self.snapshot_record1.downvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(6),
                    'voting_amount': 1,
                },
            ],
            self.snapshot_record2.downvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(3),
                    'voting_amount': 1,
                },
            ],
        }))

        self.assertEqual(snapshot[0].upvote_value, Decimal(10))
        self.assertEqual(snapshot[0].downvote_value, Decimal(6))
        self.assertEqual(snapshot[0].votes_value, Decimal(4))
        self.assertEqual(snapshot[0].voting_amount, 4)

        self.assertEqual(snapshot[1].upvote_value, Decimal(0))
        self.assertEqual(snapshot[1].downvote_value, Decimal(3))
        self.assertEqual(snapshot[1].votes_value, -Decimal(3))
        self.assertEqual(snapshot[1].voting_amount, 1)

    def test_set_votes_value_with_several_assets(self):
        snapshot = list(self.use_case.set_votes_value(self.snapshot, {
            self.snapshot_record1.upvote_account_id: [
                {
                    'asset': 'VOTE1:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(5),
                    'voting_amount': 2,
                },
                {
                    'asset': 'VOTE2:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(3),
                    'voting_amount': 1,
                },
            ],
            self.snapshot_record1.downvote_account_id: [
                {
                    'asset': 'VOTE3:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(7),
                    'voting_amount': 1,
                },
            ],
        }))

        self.assertEqual(snapshot[0].votes_value, Decimal(1))
        self.assertEqual(snapshot[0].upvote_value, Decimal(8))
        self.assertEqual(snapshot[0].downvote_value, Decimal(7))
        self.assertEqual(snapshot[0].voting_amount, 4)
        self.assertEqual(snapshot[0].upvote_assets[0], SnapshotAssetRecord(
            asset='VOTE1:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
            votes_sum='5',
            votes_count=2,
        ))
        self.assertEqual(snapshot[0].upvote_assets[1], SnapshotAssetRecord(
            asset='VOTE2:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
            votes_sum='3',
            votes_count=1,
        ))
        self.assertEqual(snapshot[0].downvote_assets[0], SnapshotAssetRecord(
            asset='VOTE3:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
            votes_sum='7',
            votes_count=1,
        ))

    def test_set_votes_value_with_downvote_immunity(self):
        self.snapshot_record1.downvote_immunity = True

        snapshot = list(self.use_case.set_votes_value(self.snapshot, {
            self.snapshot_record1.upvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(5),
                    'voting_amount': 2,
                },
            ],
            self.snapshot_record1.downvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(2),
                    'voting_amount': 1,
                },
            ],
            self.snapshot_record2.upvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(3),
                    'voting_amount': 2,
                },
            ],
            self.snapshot_record2.downvote_account_id: [
                {
                    'asset': 'VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
                    'votes_value': Decimal(1),
                    'voting_amount': 1,
                },
            ],
        }))

        self.assertEqual(snapshot[0].votes_value, Decimal(5))
        self.assertEqual(snapshot[0].upvote_value, Decimal(5))
        self.assertEqual(snapshot[0].downvote_value, Decimal(0))
        self.assertEqual(snapshot[0].upvote_assets[0], SnapshotAssetRecord(
            asset='VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
            votes_sum='5',
            votes_count=2,
        ))
        self.assertEqual(len(snapshot[0].downvote_assets), 0)

        self.assertEqual(snapshot[1].votes_value, Decimal(2))
        self.assertEqual(snapshot[1].upvote_value, Decimal(3))
        self.assertEqual(snapshot[1].downvote_value, Decimal(1))
        self.assertEqual(snapshot[1].upvote_assets[0], SnapshotAssetRecord(
            asset='VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
            votes_sum='3',
            votes_count=2,
        ))
        self.assertEqual(snapshot[1].downvote_assets[0], SnapshotAssetRecord(
            asset='VOTE:GAT3XHMN2WXG62BDC3JGNANIA2Y53BCUAHO6B5UFZM2EITZRRYKEBGQ6',
            votes_sum='1',
            votes_count=1,
        ))


class SnapshotCreationApplyBoostTestCase(TestCase):
    def setUp(self):
        self.use_case = SnapshotCreationUseCase(BaseMarketKeysProvider())

    def test_base_apply_boost(self):
        snapshot_record1 = SnapshotRecordFactory(
            votes_value=Decimal(50),
            voting_boost=Decimal('0.3'),
        )
        snapshot_record2 = SnapshotRecordFactory(
            votes_value=Decimal(40),
            voting_boost=Decimal('0.1'),
        )
        snapshot_record3 = SnapshotRecordFactory(
            votes_value=Decimal(10),
            voting_boost=Decimal(0),
        )

        snapshot = list(self.use_case.apply_boost([snapshot_record1, snapshot_record2, snapshot_record3]))

        self.assertEqual(snapshot[0].adjusted_votes_value, Decimal(65))
        self.assertEqual(snapshot[1].adjusted_votes_value, Decimal(44))
        self.assertEqual(snapshot[2].adjusted_votes_value, Decimal(10))


class SnapshotCreationSetRankTestCase(TestCase):
    def setUp(self):
        self.use_case = SnapshotCreationUseCase(BaseMarketKeysProvider())

    def test_base_set_rank(self):
        snapshot_record1 = SnapshotRecordFactory(
            adjusted_votes_value=Decimal(50),
            votes_value=Decimal(40),
        )
        snapshot_record2 = SnapshotRecordFactory(
            adjusted_votes_value=Decimal(50),
            votes_value=Decimal(50),
        )
        snapshot_record3 = SnapshotRecordFactory(
            adjusted_votes_value=Decimal(20),
            votes_value=Decimal(15),
        )
        snapshot_record4 = SnapshotRecordFactory(
            adjusted_votes_value=Decimal(150),
            votes_value=Decimal(130),
        )

        snapshot = list(self.use_case.set_rank([
            snapshot_record1,
            snapshot_record2,
            snapshot_record3,
            snapshot_record4,
        ]))

        self.assertEqual(snapshot[0].rank, 1)
        self.assertEqual(snapshot[0].market_key, snapshot_record4.market_key)
        self.assertEqual(snapshot[1].rank, 2)
        self.assertEqual(snapshot[1].market_key, snapshot_record2.market_key)
        self.assertEqual(snapshot[2].rank, 3)
        self.assertEqual(snapshot[2].market_key, snapshot_record1.market_key)
        self.assertEqual(snapshot[3].rank, 4)
        self.assertEqual(snapshot[3].market_key, snapshot_record3.market_key)


class SnapshotCreationPersistenceTestCase(TestCase):
    def setUp(self):
        self.use_case = SnapshotCreationUseCase(BaseMarketKeysProvider())

    def test_save_snapshot_persists_whitelisted_for_rewards(self):
        timestamp = timezone.now()

        whitelisted = SnapshotRecordFactory(
            market_key=fake.stellar_public_key(),
            rank=1,
            whitelisted_for_rewards=True,
        )
        not_whitelisted = SnapshotRecordFactory(
            market_key=fake.stellar_public_key(),
            rank=2,
            whitelisted_for_rewards=False,
        )

        self.use_case.save_snapshot([whitelisted, not_whitelisted], timestamp)

        saved = VotingSnapshot.objects.filter(timestamp=timestamp).order_by('rank')
        self.assertEqual(saved.count(), 2)
        self.assertTrue(saved[0].whitelisted_for_rewards)
        self.assertFalse(saved[1].whitelisted_for_rewards)
