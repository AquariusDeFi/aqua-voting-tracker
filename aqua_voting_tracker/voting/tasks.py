import asyncio
import logging
import sys
from asyncio import Semaphore
from typing import Iterable, List

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from asgiref.sync import sync_to_async
from dateutil.parser import parse as date_parse
from stellar_sdk import AiohttpClient, Server, ServerAsync
from stellar_sdk.exceptions import NotFoundError

from aqua_voting_tracker.taskapp import app as celery_app
from aqua_voting_tracker.utils.stellar.requests import load_all_records
from aqua_voting_tracker.voting.exceptions import VoteParsingError
from aqua_voting_tracker.voting.marketkeys import get_marketkeys_provider
from aqua_voting_tracker.voting.models import Vote
from aqua_voting_tracker.voting.parser import parse_claimable_balance, parse_claimable_balance_from_effects
from aqua_voting_tracker.voting.services.snapshot_creation import SnapshotCreationUseCase


logger = logging.getLogger()


CLAIMABLE_BALANCES_CURSOR_CACHE_KEY = 'aqua_voting_tracker.voting.CLAIMABLE_BALANCES_CURSOR_CACHE_KEY'
CLAIMABLE_BALANCES_LIMIT = 200
CLAIMABLE_BALANCES_BULK_LIMIT = 10000

CLAIM_BACK_CURSOR_CACHE_KEY = 'aqua_voting_tracker.voting.CLAIM_BACK_CURSOR_CACHE_KEY'
CLAIM_BACK_BUNCH_LIMIT = 250
CLAIM_BACK_REQUEST_TIMEOUT = 60
CLAIM_BACK_SEMAPHORE = 30


def _parse_vote(claimable_balance: dict):
    try:
        return parse_claimable_balance(claimable_balance)
    except VoteParsingError:
        logger.warning('Invalid claimable balance.', exc_info=sys.exc_info())


@celery_app.task(ignore_result=True)
def task_load_new_claimable_balances():
    """Load votes at least once, publishing the cursor only after persistence."""
    horizon_server = Server(settings.HORIZON_URL)

    request_builder = horizon_server.claimable_balances().order(desc=False)

    cursor = cache.get(CLAIMABLE_BALANCES_CURSOR_CACHE_KEY, None)

    last_claimable_balance = None
    new_votes = []
    for index, claimable_balance in enumerate(load_all_records(request_builder,
                                                               start_cursor=cursor,
                                                               page_size=CLAIMABLE_BALANCES_LIMIT)):
        if index > CLAIMABLE_BALANCES_BULK_LIMIT:
            break

        vote = _parse_vote(claimable_balance)
        if vote:
            logger.warning('Old task get new claimable balance: %s', vote.balance_id)
            new_votes.append(vote)

        last_claimable_balance = claimable_balance

    # The unique balance_id is the replay/overlap arbiter. Persist the page
    # before publishing its cursor so cache failures cause a harmless replay.
    Vote.objects.bulk_create(new_votes, ignore_conflicts=True)

    if last_claimable_balance:
        cache.set(CLAIMABLE_BALANCES_CURSOR_CACHE_KEY,
                  last_claimable_balance['paging_token'],
                  None)


async def _update_claim_back_time(vote: Vote, *, server: ServerAsync, semaphore: Semaphore):
    # Horizon answers 404 or an empty page when the balance has no operation in its retained history,
    # so it has not been claimed back yet.
    try:
        async with semaphore:
            response = await server.operations().for_claimable_balance(vote.balance_id).order(desc=True).limit(1).call()
    except NotFoundError:
        return

    records = response['_embedded']['records']
    if not records:
        return
    operation = records[0]

    if operation['type'] not in ['claim_claimable_balance', 'clawback_claimable_balance']:
        return

    logger.warning('Old claim back task is still useful.')
    vote.claimed_back_at = date_parse(operation['created_at'])
    await sync_to_async(vote.save)()


async def _bunch_update_claim_back_time(votes: Iterable[Vote]):
    semaphore = Semaphore(CLAIM_BACK_SEMAPHORE)
    client = AiohttpClient(request_timeout=CLAIM_BACK_REQUEST_TIMEOUT)
    async with ServerAsync(settings.HORIZON_URL, client=client) as server:
        await asyncio.gather(*[_update_claim_back_time(vote, server=server, semaphore=semaphore)
                               for vote in votes])


@celery_app.task(ignore_result=True)
def task_update_claim_back_time():
    now = timezone.now()
    queryset = Vote.objects.filter(locked_until__lt=now, claimed_back_at__isnull=True)
    cursor = cache.get(CLAIM_BACK_CURSOR_CACHE_KEY)
    if cursor:
        queryset = queryset.filter(id__gt=cursor)

    votes = list(queryset[:CLAIM_BACK_BUNCH_LIMIT])
    asyncio.run(_bunch_update_claim_back_time(votes))

    if len(votes) < CLAIM_BACK_BUNCH_LIMIT:
        cache.delete(CLAIM_BACK_CURSOR_CACHE_KEY)
    else:
        cache.set(CLAIM_BACK_CURSOR_CACHE_KEY, votes[-1].id, None)


@celery_app.task(ignore_result=True)
def task_create_voting_snapshot():
    now = timezone.now()
    timestamp = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0) - timezone.timedelta(minutes=5)

    SnapshotCreationUseCase(
        get_marketkeys_provider(),
    ).create_snapshot(timestamp)


@celery_app.task(ignore_result=True)
def task_parse_create_claimable_balance_effects(effects: List[dict]):
    try:
        vote = parse_claimable_balance_from_effects(effects)
    except VoteParsingError:
        logger.warning('Invalid claimable balance.', exc_info=sys.exc_info())
        return

    if not Vote.objects.filter(balance_id=vote.balance_id).exists():
        vote.save()
    else:
        logger.warning('Claimable balance duplicate: %s', vote.balance_id)


@celery_app.task(ignore_result=True)
def task_parse_close_claimable_balance_effects(effects: List[dict]):
    claimable_balance_claimed = 'claimable_balance_claimed'
    claimable_balance_clawed_back = 'claimable_balance_clawed_back'
    close_effect = next(effect for effect in effects
                        if effect['type'] in {claimable_balance_claimed, claimable_balance_clawed_back})

    balance_id = close_effect['balance_id']
    closed_at = date_parse(close_effect['created_at'])

    Vote.objects.filter(balance_id=balance_id).update(claimed_back_at=closed_at)
