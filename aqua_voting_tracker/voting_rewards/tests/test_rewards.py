from decimal import Decimal
from typing import Iterable, List, Union
from unittest import TestCase
from unittest.mock import patch

from django.conf import settings

from aqua_voting_tracker.voting_rewards.services.rewards.base import MarketReward
from aqua_voting_tracker.voting_rewards.services.rewards.v1 import RewardsV1Calculator


def get_markets(market_keys: Iterable[str]):
    return [
        {
            'account_id': market_key,
            'asset1': f'A{i // 2 + 1}:ISSUER',
            'asset2': f'A{i // 2 + 2}:ISSUER',
            'whitelisted_for_rewards': True,
        }
        for i, market_key in enumerate(market_keys)
    ]


def make_get_markets(whitelist_flags: List[bool]):
    def _builder(market_keys: Iterable[str]):
        keys = list(market_keys)
        return [
            {
                'account_id': market_key,
                'asset1': f'A{i // 2 + 1}:ISSUER',
                'asset2': f'A{i // 2 + 2}:ISSUER',
                'whitelisted_for_rewards': whitelist_flags[i] if i < len(whitelist_flags) else False,
            }
            for i, market_key in enumerate(keys)
        ]
    return _builder


def get_candidates(votes_value):
    return [
        {
            'market_key': f'market{i + 1}',
            'adjusted_votes_value': value,
        }
        for i, value in enumerate(votes_value)
    ]


def get_stats(candidates):
    return {
        'adjusted_votes_value_sum': sum(candidate['adjusted_votes_value'] for candidate in candidates),
    }


@patch('aqua_voting_tracker.voting_rewards.services.rewards.base.get_market_pairs', new=get_markets)
class GetCurrentRewardTestCase(TestCase):
    get_candidates_patch = 'aqua_voting_tracker.voting_rewards.services.rewards.base.get_voting_rewards_candidate'
    get_stats_patch = 'aqua_voting_tracker.voting_rewards.services.rewards.base.get_voting_stats'

    def assert_rewards(self, rewards: List[MarketReward]):
        total_reward = sum(reward.reward_value for reward in rewards)
        self.assertLessEqual(total_reward, settings.TOTAL_REWARD_VALUE)
        self.assertAlmostEqual(
            total_reward,
            settings.TOTAL_REWARD_VALUE,
            delta=5,
        )
        self.assertTrue(all(reward.reward_value == reward.amm_reward_value + reward.sdex_reward_value
                            for reward in rewards))

        self.assertAlmostEqual(
            sum(float(reward.share) for reward in rewards),
            1,
            delta=0.0001,
        )
        self.assertTrue(all(reward.share <= settings.REWARD_MAX_SHARE for reward in rewards))

        prev_reward = rewards[0]
        for reward in rewards[1:]:
            if prev_reward.share < settings.REWARD_MAX_SHARE:
                votes_ratio = float(prev_reward.votes_value) / float(reward.votes_value)
                self.assertAlmostEqual(float(prev_reward.share) / float(reward.share),
                                       votes_ratio, delta=0.01)
                self.assertAlmostEqual(float(prev_reward.reward_value) / float(reward.reward_value),
                                       votes_ratio, delta=0.01)
            prev_reward = reward

    def assert_shares(self, rewards: List[MarketReward], shares: List[Union[Decimal, str]]):
        self.assertListEqual(
            [reward.share for reward in rewards],
            [Decimal(share) for share in shares],
        )

    def test_common(self):
        candidates = get_candidates([95, 90, 85, 80, 75, 70, 65, 60, 55, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10])
        stats = get_stats(candidates)

        with patch(self.get_candidates_patch, new=lambda x: candidates):
            with patch(self.get_stats_patch, new=lambda: stats):
                rewards = RewardsV1Calculator().run()

        self.assert_rewards(rewards)
        self.assert_shares(rewards, [
            '0.095', '0.09', '0.085', '0.08', '0.075', '0.07', '0.065', '0.06', '0.055', '0.055',
            '0.05', '0.045', '0.04', '0.035', '0.03', '0.025', '0.02', '0.015', '0.01',
        ])

    def test_cut_to_limit1(self):
        candidates = get_candidates([50, 50, 50, 50, 30, 30, 20, 20, 10, 10, 10, 10, 10, 10, 10, 10, 5, 5, 5, 5])
        stats = get_stats(candidates)

        with patch(self.get_candidates_patch, new=lambda x: candidates):
            with patch(self.get_stats_patch, new=lambda: stats):
                rewards = RewardsV1Calculator().run()

        self.assert_rewards(rewards)
        self.assert_shares(rewards, [
            '0.1', '0.1', '0.1', '0.1', '0.09', '0.09', '0.06', '0.06', '0.03', '0.03', '0.03',
            '0.03', '0.03', '0.03', '0.03', '0.03', '0.015', '0.015', '0.015', '0.015',
        ])

    def test_cut_to_limit2(self):
        candidates = get_candidates([50, 50, 50, 50, 35, 30, 20, 20, 10, 10, 10, 10, 10, 10, 10, 10, 5, 5, 5])
        stats = get_stats(candidates)

        with patch(self.get_candidates_patch, new=lambda x: candidates):
            with patch(self.get_stats_patch, new=lambda: stats):
                rewards = RewardsV1Calculator().run()

        self.assert_rewards(rewards)
        self.assert_shares(rewards, [
            '0.1', '0.1', '0.1', '0.1', '0.1', '0.0909', '0.0606', '0.0606', '0.0303', '0.0303',
            '0.0303', '0.0303', '0.0303', '0.0303', '0.0303', '0.0303', '0.0152', '0.0152', '0.0152',
        ])

    def test_whitelist_dilution(self):
        # Non-whitelisted markets do not get rewards and their shares are NOT
        # redistributed to survivors — total dispersion drops by their combined share.
        candidates = get_candidates([95, 90, 85, 80, 75, 70, 65, 60, 55, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10])
        stats = get_stats(candidates)  # full_voting_value = 1000

        # Whitelist first 5 markets only: survivors_votes = 95+90+85+80+75 = 425, dilution = 0.425.
        whitelist_flags = [True] * 5 + [False] * 14
        survivors_share = Decimal('0.425')

        with patch(self.get_candidates_patch, new=lambda x: candidates):
            with patch(self.get_stats_patch, new=lambda: stats):
                with patch(
                    'aqua_voting_tracker.voting_rewards.services.rewards.base.get_market_pairs',
                    new=make_get_markets(whitelist_flags),
                ):
                    rewards = RewardsV1Calculator().run()

        self.assertEqual(len(rewards), 5)

        # Per-pair share = votes / full_voting_value (no /total_share renormalization).
        self.assert_shares(rewards, ['0.095', '0.09', '0.085', '0.08', '0.075'])

        # Total dispersion = TOTAL_REWARDS * survivors_share (≈ 0.425 * 7M).
        total_reward = sum(reward.reward_value for reward in rewards)
        self.assertAlmostEqual(
            total_reward,
            settings.TOTAL_REWARD_VALUE * survivors_share,
            delta=5,
        )
        self.assertLessEqual(total_reward, settings.TOTAL_REWARD_VALUE)

        # Per-pair cap is absolute (REWARD_MAX_SHARE * TOTAL_REWARDS = 700k), not relative.
        self.assertTrue(all(reward.share <= settings.REWARD_MAX_SHARE for reward in rewards))
        self.assertTrue(all(
            reward.reward_value <= settings.REWARD_MAX_SHARE * settings.TOTAL_REWARD_VALUE
            for reward in rewards
        ))

    def test_whitelist_cap_redistribute(self):
        # filter_eligible runs AFTER calculate_shares: cap+redistribute is computed
        # over the full reward_zone (including non-whitelisted), then non-whitelisted
        # markets are dropped — their final share is removed entirely, not dissolved
        # back into survivors. Per-pair cap is 700k absolute (REWARD_MAX_SHARE * TOTAL_REWARDS).
        # Votes [600, 200, 50, 50, 50, 50], denominator = 1000.
        # First (600 votes) not whitelisted.
        candidates = get_candidates([600, 200, 50, 50, 50, 50])
        stats = get_stats(candidates)

        whitelist_flags = [False, True, True, True, True, True]

        with patch(self.get_candidates_patch, new=lambda x: candidates):
            with patch(self.get_stats_patch, new=lambda: stats):
                with patch(
                    'aqua_voting_tracker.voting_rewards.services.rewards.base.get_market_pairs',
                    new=make_get_markets(whitelist_flags),
                ):
                    rewards = RewardsV1Calculator().run()

        self.assertEqual(len(rewards), 5)

        # All 6 markets hit the 0.1 cap during calculate_shares (m1 base=0.6, m2 base=0.2;
        # cut_share accumulates and pushes m3..m6 over the cap too). After dropping
        # m1, survivors each retain their cap of 0.1.
        self.assert_shares(rewards, ['0.1', '0.1', '0.1', '0.1', '0.1'])

        # Total = 5 * 700k = 3.5M (= 0.5 * TOTAL_REWARDS); m1's 0.1 capped share is lost.
        total_reward = sum(reward.reward_value for reward in rewards)
        self.assertAlmostEqual(
            total_reward,
            settings.TOTAL_REWARD_VALUE * Decimal('0.5'),
            delta=5,
        )

        # Per-pair cap is 700k absolute.
        self.assertTrue(all(
            reward.reward_value <= settings.REWARD_MAX_SHARE * settings.TOTAL_REWARD_VALUE
            for reward in rewards
        ))
