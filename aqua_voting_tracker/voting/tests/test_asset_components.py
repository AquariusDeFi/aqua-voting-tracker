import hashlib
import json
from datetime import datetime, timedelta, timezone

from django.test import TestCase

from aqua_voting_tracker.voting.models import Vote


class VoteAssetComponentsTests(TestCase):
    def setUp(self):
        self.at = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        self.url = '/api/market-keys/market/votes/?timestamp={0}'.format(int(self.at.timestamp()))
        self.vote('own', 'upvote:issuer', '0.0000001')
        self.vote('incoming', 'dICE:issuer', '2.0000000')
        self.vote('incoming-2', 'dICE:issuer', '3.0000000')

    def vote(self, identity, asset, amount, **changes):
        values = {'balance_id': identity, 'voting_account': 'B', 'market_key': 'market', 'asset': asset,
                  'amount': amount, 'locked_at': self.at - timedelta(days=2),
                  'locked_until': self.at + timedelta(days=1)}
        values.update(changes)
        return Vote.objects.create(**values)

    def test_components_share_the_exact_aggregate_query(self):
        response = self.client.get(self.url + '&include_assets=1')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['as_of'], int(self.at.timestamp()))
        self.assertEqual(data['results'][0], {
            'voting_account': 'B', 'votes_value': '5.0000001',
            'asset_votes': [{'asset': 'dICE:issuer', 'votes_value': '5.0000000'},
                            {'asset': 'upvote:issuer', 'votes_value': '0.0000001'}],
        })

    def test_components_obey_historical_creation_and_claim_times(self):
        self.vote('created-later', 'dICE:issuer', '100', locked_at=self.at + timedelta(seconds=1))
        self.vote('claimed-earlier', 'dICE:issuer', '100', claimed_back_at=self.at - timedelta(seconds=1))
        self.vote('claimed-later', 'dICE:issuer', '7', claimed_back_at=self.at + timedelta(seconds=1))
        row = self.client.get(self.url + '&include_assets=1').json()['results'][0]
        self.assertEqual(row['votes_value'], '12.0000001')
        self.assertEqual(row['asset_votes'][0]['votes_value'], '12.0000000')

    def test_default_response_is_unchanged(self):
        row = self.client.get(self.url).json()['results'][0]
        self.assertEqual(set(row), {'voting_account', 'votes_value'})

    def test_each_page_has_its_own_components_at_the_same_time(self):
        self.vote('other', 'upvote:issuer', '10', voting_account='C')
        first = self.client.get(self.url + '&include_assets=1&limit=1').json()
        second = self.client.get(self.url + '&include_assets=1&limit=1&page=2').json()
        self.assertEqual([first['results'][0]['voting_account'], second['results'][0]['voting_account']], ['B', 'C'])
        self.assertEqual(second['results'][0]['asset_votes'], [{'asset': 'upvote:issuer', 'votes_value': '10.0000000'}])
        self.assertEqual(first['as_of'], second['as_of'])
        self.assertEqual(first['view_id'], second['view_id'])

    def test_late_ingestion_changes_view_identity_even_at_same_timestamp(self):
        before = self.client.get(self.url + '&include_assets=1').json()
        self.vote('late', 'dICE:issuer', '4')
        after = self.client.get(self.url + '&include_assets=1').json()
        self.assertNotEqual(before['view_id'], after['view_id'])
        contents = {'as_of': after['as_of'], 'network_id': after['network_id'],
                    'market_key': 'market', 'results': after['results']}
        expected = hashlib.sha256(json.dumps(contents, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(after['view_id'], expected)
