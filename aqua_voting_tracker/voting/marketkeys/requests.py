from typing import Iterable, Iterator

from django.conf import settings

import requests
from more_itertools import chunked

from aqua_voting_tracker.voting.marketkeys.base import BaseMarketKeysProvider


class ApiMarketKeysProvider(BaseMarketKeysProvider):
    chunk_size = 100

    market_keys_tracker_host = settings.MARKETKEYS_TRACKER_URL
    api_endpoint = '/api/market-keys/'

    def get_api_endpoint(self):
        return self.market_keys_tracker_host.rstrip('/') + self.api_endpoint

    def __iter__(self) -> Iterator[dict]:
        page_endpoint = self.get_api_endpoint() + f'?limit={self.chunk_size}'

        while page_endpoint:
            response = requests.get(page_endpoint)
            response.raise_for_status()

            data = response.json()
            records = data['results']
            page_endpoint = data['next']

            yield from records

    def get_multiple(self, account_ids: Iterable[str]) -> Iterator[dict]:
        api_endpoint = self.get_api_endpoint()
        not_found_ids = []
        downvotes_account_ids = set()

        for chunk in chunked(account_ids, self.chunk_size):
            chunk = list(chunk)

            response = requests.get(api_endpoint, params=[
                ('account_id', account_id) for account_id in chunk
            ])
            response.raise_for_status()

            for market_key in response.json()['results']:
                chunk.remove(market_key['account_id'])

                if not market_key['downvote_account_id']:
                    continue
                else:
                    downvotes_account_ids.add(market_key['downvote_account_id'])

                yield market_key

            not_found_ids.extend(chunk)

        not_found_ids = [account_id for account_id in not_found_ids if account_id not in downvotes_account_ids]

        for chunk in chunked(not_found_ids, self.chunk_size):
            response = requests.get(api_endpoint, params=[
                ('downvote_account_id', account_id) for account_id in chunk
            ])
            response.raise_for_status()

            for market_key in response.json()['results']:
                yield market_key
