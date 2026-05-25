import asyncio
from decimal import Decimal
from typing import Iterable, List, Tuple

from django.conf import settings

from stellar_sdk import Asset, ServerAsync

from aqua_voting_tracker.utils.stellar.asset import get_asset_string, parse_asset_string
from aqua_voting_tracker.voting_rewards.services.rewards.base import MarketReward, RewardsCalculator
from aqua_voting_tracker.voting_rewards.services.sdex_amm_distribution.exponent import ExponentDistributor
from aqua_voting_tracker.voting_rewards.stellar import MarketData


class RewardsV2Calculator(RewardsCalculator):
    def __init__(self):
        super(RewardsV2Calculator, self).__init__()

        self.HORIZON_URL = settings.HORIZON_URL

        self.DEFAULT_SDEX_SHARE = Decimal(settings.SDEX_SHARE)
        self.DEFAULT_AMM_SHARE = Decimal(settings.AMM_SHARE)

        self.SDEX_AMM_MIN_SHARE = Decimal(settings.SDEX_AMM_MIN_SHARE)

        self.distributor_class = ExponentDistributor

    def get_default_distribution(self):
        shares_sum = self.DEFAULT_SDEX_SHARE + self.DEFAULT_AMM_SHARE
        return self.DEFAULT_SDEX_SHARE / shares_sum, self.DEFAULT_AMM_SHARE / shares_sum

    async def load_markets_data(self, asset_pairs: List[Tuple[Asset, Asset]]) -> List[MarketData]:
        server = ServerAsync(self.HORIZON_URL)

        market_data_list = [
            MarketData(asset1, asset2) for asset1, asset2 in asset_pairs
        ]

        await asyncio.gather(*[
            data.load_data(server) for data in market_data_list
        ])

        await server.close()

        return market_data_list

    def distribute_sdex_amm(self, reward_zone: Iterable[MarketReward]) -> Iterable[MarketReward]:
        reward_zone = list(reward_zone)

        market_data_list = asyncio.run(self.load_markets_data([
            (parse_asset_string(market.asset1), parse_asset_string(market.asset2))
            for market in reward_zone
        ]))
        market_data_dict = {
            (get_asset_string(market_data.asset1), get_asset_string(market_data.asset2)): market_data
            for market_data in market_data_list
        }

        for market_reward in reward_zone:
            market_data = market_data_dict[(market_reward.asset1, market_reward.asset2)]
            if market_data.is_loaded():
                distributor = self.distributor_class(market_data)
                sdex_share, amm_share = distributor.get_weights()
            else:
                sdex_share, amm_share = self.get_default_distribution()

            amm_share = max(amm_share, self.SDEX_AMM_MIN_SHARE)
            amm_share = min(amm_share, 1 - self.SDEX_AMM_MIN_SHARE)

            amm_share = Decimal(amm_share).quantize(Decimal('0.00'))

            market_reward.amm_share = amm_share
            market_reward.sdex_share = 1 - amm_share

            market_reward.amm_reward_value = round(market_reward.reward_value * amm_share)
            market_reward.sdex_reward_value = market_reward.reward_value - market_reward.amm_reward_value

            yield market_reward

    def run(self) -> List[MarketReward]:
        reward_zone = self.get_reward_zone()
        reward_zone = self.connect_assets(reward_zone)
        reward_zone = self.filter_eligible(reward_zone)
        reward_zone = self.calculate_shares(reward_zone)
        reward_zone = self.set_reward_value(reward_zone)
        reward_zone = self.distribute_sdex_amm(reward_zone)
        return list(reward_zone)
