from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List

from django.conf import settings

from aqua_voting_tracker.voting_rewards.data import get_market_pairs, get_voting_rewards_candidate, get_voting_stats


@dataclass
class MarketReward:
    market_key: str
    votes_value: Decimal

    asset1: str = None
    asset2: str = None

    whitelisted_for_rewards: bool = False

    share: Decimal = None
    reward_value: Decimal = None

    sdex_share: Decimal = None
    amm_share: Decimal = None
    sdex_reward_value: Decimal = None
    amm_reward_value: Decimal = None


class RewardsCalculator:
    def __init__(self):
        self.MIN_SHARE_FOR_REWARD_ZONE = Decimal(settings.MIN_SHARE_FOR_REWARD_ZONE)
        self.REWARD_MAX_SHARE = Decimal(settings.REWARD_MAX_SHARE)
        self.TOTAL_REWARDS = Decimal(settings.TOTAL_REWARD_VALUE)

    def get_reward_zone(self) -> Iterable[MarketReward]:
        current_stats = get_voting_stats()
        total_voting_value = Decimal(current_stats['adjusted_votes_value_sum'])

        reward_candidates = get_voting_rewards_candidate(self.MIN_SHARE_FOR_REWARD_ZONE)
        for candidate in reward_candidates:
            votes_value = Decimal(candidate['adjusted_votes_value'])
            if votes_value / total_voting_value < self.MIN_SHARE_FOR_REWARD_ZONE:
                break

            yield MarketReward(
                market_key=candidate['market_key'],
                votes_value=votes_value,
            )

    def connect_assets(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        reward_zone = list(reward_zone)
        market_pairs = get_market_pairs((market.market_key for market in reward_zone))
        market_pair_mapping = {
            market_pair['account_id']: market_pair
            for market_pair in market_pairs
        }

        for market_reward in reward_zone:
            market_pair = market_pair_mapping[market_reward.market_key]
            market_reward.asset1 = market_pair['asset1']
            market_reward.asset2 = market_pair['asset2']
            market_reward.whitelisted_for_rewards = bool(market_pair.get('whitelisted_for_rewards'))

            yield market_reward

    def filter_eligible(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        # Drop markets whose pair is not whitelisted for rewards. Runs after
        # calculate_shares so dropped shares are not redistributed to survivors.
        for market_reward in reward_zone:
            if not market_reward.whitelisted_for_rewards:
                continue
            yield market_reward

    def calculate_shares(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        reward_zone = list(reward_zone)
        reward_zone_votes_value = sum(market.votes_value for market in reward_zone)

        cut_share = 0
        remain_share = 1
        for market_reward in reward_zone:

            share = market_reward.votes_value / reward_zone_votes_value
            add_share = cut_share * share / remain_share
            remain_share -= share
            cut_share -= add_share
            share += add_share

            if share > self.REWARD_MAX_SHARE:
                cut_share += share - self.REWARD_MAX_SHARE
                share = self.REWARD_MAX_SHARE

            market_reward.share = share

            yield market_reward

    def set_reward_value(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        # No /total_share renormalization: per-pair cap stays absolute at
        # REWARD_MAX_SHARE * TOTAL_REWARDS, and total dispersion across survivors
        # can be < TOTAL_REWARDS when filter_eligible has dropped any markets.
        for market_reward in reward_zone:
            market_reward.reward_value = round(self.TOTAL_REWARDS * market_reward.share)
            market_reward.share = Decimal(round(market_reward.share, 4))

            yield market_reward

    def run(self) -> List[MarketReward]:
        raise NotImplementedError
