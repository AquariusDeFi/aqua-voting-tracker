from decimal import Decimal
from typing import Iterable, List

from django.conf import settings

from aqua_voting_tracker.voting_rewards.services.rewards.base import MarketReward, RewardsCalculator


class RewardsV1Calculator(RewardsCalculator):
    def __init__(self):
        super(RewardsV1Calculator, self).__init__()

        self.SDEX_SHARE = Decimal(settings.SDEX_SHARE)
        self.AMM_SHARE = Decimal(settings.AMM_SHARE)

    def distribute_sdex_amm_rewards(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        amm_share = self.AMM_SHARE / (self.AMM_SHARE + self.SDEX_SHARE)
        for market_reward in reward_zone:
            market_reward.amm_share = Decimal(amm_share).quantize(Decimal('0.00'))
            market_reward.sdex_share = 1 - market_reward.amm_share
            market_reward.amm_reward_value = round(market_reward.reward_value * amm_share)
            market_reward.sdex_reward_value = market_reward.reward_value - market_reward.amm_reward_value

            yield market_reward

    def run(self) -> List[MarketReward]:
        reward_zone = self.get_reward_zone()
        reward_zone = self.connect_assets(reward_zone)
        reward_zone = self.filter_eligible(reward_zone)
        reward_zone = self.calculate_shares(reward_zone)
        reward_zone = self.set_reward_value(reward_zone)
        reward_zone = self.distribute_sdex_amm_rewards(reward_zone)
        return list(reward_zone)
