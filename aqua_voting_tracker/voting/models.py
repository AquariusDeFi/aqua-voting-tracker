from django.db import models


class VoteQuerySet(models.QuerySet):
    def filter_lock_at(self, time_filter):
        return self.filter(locked_at__lte=time_filter, locked_until__gt=time_filter)

    def filter_by_min_term(self, min_term):
        return self.annotate(term=models.F('locked_until') - models.F('locked_at')).filter(term__gte=min_term)

    def filter_exist_at(self, time_filter):
        return self.filter(
            models.Q(locked_at__lte=time_filter)
            & models.Q(
                models.Q(claimed_back_at__isnull=True)
                | models.Q(claimed_back_at__gt=time_filter),
            ),
        )

    def annotate_stats(self):
        return self.values('market_key', 'asset').annotate(
            votes_value=models.Sum('amount'),
            voting_amount=models.Count('voting_account', distinct=True),
        )

    def annotate_by_voting_account(self):
        return self.values('voting_account').annotate(
            votes_value=models.Sum('amount'),
        )


class Vote(models.Model):
    balance_id = models.CharField(max_length=72, unique=True)

    voting_account = models.CharField(max_length=56)
    market_key = models.CharField(max_length=56)

    amount = models.DecimalField(max_digits=20, decimal_places=7)
    asset = models.CharField(max_length=69)

    locked_at = models.DateTimeField()
    locked_until = models.DateTimeField()
    claimed_back_at = models.DateTimeField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = VoteQuerySet.as_manager()

    def __str__(self):
        return f'{self.market_key} - {self.amount}'

    def get_vote_term(self):
        return self.locked_until - self.locked_at


class VotingSnapshotQuerySet(models.QuerySet):
    def filter_last_snapshot(self):
        last_snapshot_timestamp = self.order_by('-timestamp').values('timestamp')[:1]
        return self.filter(timestamp=models.Subquery(last_snapshot_timestamp))

    def annotate_assets(self):
        return self.prefetch_related(
            models.Prefetch(
                'assets',
                queryset=VotingSnapshotAsset.objects.filter(direction=VotingSnapshotAsset.Direction.UP),
                to_attr='upvote_assets',
            ),
            models.Prefetch(
                'assets',
                queryset=VotingSnapshotAsset.objects.filter(direction=VotingSnapshotAsset.Direction.DOWN),
                to_attr='downvote_assets',
            ),
        )

    def current_stats(self):
        stats = self.aggregate(
            market_key_count=models.Count('market_key'),
            votes_value_sum=models.Sum('votes_value'),
            voting_amount_sum=models.Sum('voting_amount'),
            adjusted_votes_value_sum=models.Sum('adjusted_votes_value'),
            total_votes_sum=models.Sum(models.F('upvote_value') + models.F('downvote_value')),
            timestamp=models.Max('timestamp'),
        )

        stats['assets'] = list(VotingSnapshotAsset.objects.filter_last_snapshot().get_stats_by_assets())

        return stats


class VotingSnapshot(models.Model):
    market_key = models.CharField(max_length=56, db_index=True)
    rank = models.PositiveIntegerField()

    votes_value = models.DecimalField(max_digits=20, decimal_places=7)
    voting_amount = models.PositiveIntegerField()

    upvote_value = models.DecimalField(max_digits=20, decimal_places=7)
    downvote_value = models.DecimalField(max_digits=20, decimal_places=7)

    adjusted_votes_value = models.DecimalField(max_digits=20, decimal_places=7)

    timestamp = models.DateTimeField(db_index=True)

    extra = models.JSONField()

    whitelisted_for_rewards = models.BooleanField(default=False, db_index=True)

    objects = VotingSnapshotQuerySet.as_manager()

    def __str__(self):
        return f'{self.market_key} - {self.timestamp}'


class VotingSnapshotAssetQuerySet(models.QuerySet):
    def filter_last_snapshot(self):
        return self.filter(snapshot__in=VotingSnapshot.objects.filter_last_snapshot())

    def get_stats_by_assets(self):
        return self.values('asset').annotate(
            votes_sum=models.Sum('votes_sum'),
            votes_count=models.Sum('votes_count'),
        )


class VotingSnapshotAsset(models.Model):
    class Direction(models.IntegerChoices):
        UP = 1
        DOWN = 2

    snapshot = models.ForeignKey(VotingSnapshot, related_name='assets', on_delete=models.CASCADE)
    asset = models.CharField(max_length=69)

    direction = models.PositiveSmallIntegerField(choices=Direction.choices)

    votes_sum = models.DecimalField(max_digits=20, decimal_places=7)
    votes_count = models.PositiveIntegerField()

    objects = VotingSnapshotAssetQuerySet.as_manager()

    def __str__(self):
        return f'{self.snapshot} - {self.asset}'
