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
        # Stash the full voting denominator so calculate_shares scores each market
        # against ALL votes (not the survivor sum). Set before the first yield, so
        # it is populated by the time calculate_shares runs downstream.
        self.total_voting_value = total_voting_value

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
        # Drop markets whose pair is not whitelisted for rewards. Their votes still
        # count toward the full denominator (self.total_voting_value), so removing
        # them does NOT lift the survivors' shares — a dropped market's share is
        # simply not emitted.
        for market_reward in reward_zone:
            if not market_reward.whitelisted_for_rewards:
                continue
            yield market_reward

    def calculate_shares(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        # Cap-only, no redistribution (decision 2026-06-01, Глеб + Roman).
        # Each market's share is its vote fraction of the FULL voting denominator
        # (self.total_voting_value, including non-eligible / non-whitelisted votes),
        # clamped at REWARD_MAX_SHARE. The capped excess is NOT spread across other
        # markets, and the denominator is NOT renormalized to survivors. So a market
        # with 43% of the votes earns exactly the 10% cap and the other 33pp are
        # simply not emitted — small pairs keep their raw share (e.g. 0.5% -> 35k),
        # they are not lifted toward the cap. Total dispersion falls below
        # TOTAL_REWARDS by the capped excess plus the non-eligible vote share; this
        # sub-7M payout is intended for the whitelist transition period.
        for market_reward in reward_zone:
            share = market_reward.votes_value / self.total_voting_value

            if share > self.REWARD_MAX_SHARE:
                share = self.REWARD_MAX_SHARE

            market_reward.share = share

            yield market_reward

    def set_reward_value(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        # No /total_share renormalization: per-pair reward stays absolute at
        # share * TOTAL_REWARDS (cap = REWARD_MAX_SHARE * TOTAL_REWARDS = 700k),
        # and the dispersed total is below TOTAL_REWARDS by the capped excess plus
        # the non-eligible vote share.
        for market_reward in reward_zone:
            market_reward.reward_value = round(self.TOTAL_REWARDS * market_reward.share)
            market_reward.share = Decimal(round(market_reward.share, 4))

            yield market_reward

    def run(self) -> List[MarketReward]:
        raise NotImplementedError
