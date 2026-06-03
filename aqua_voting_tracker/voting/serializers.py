from rest_framework import serializers

from aqua_voting_tracker.voting.models import VotingSnapshot


class VotingSnapshotAssetStatsSerializer(serializers.Serializer):
    asset = serializers.CharField()
    votes_sum = serializers.DecimalField(max_digits=20, decimal_places=7)
    votes_count = serializers.IntegerField()


class VotingSnapshotSerializer(serializers.ModelSerializer):
    extra = serializers.SerializerMethodField()

    class Meta:
        model = VotingSnapshot
        fields = ['timestamp', 'market_key', 'rank', 'votes_value', 'voting_amount',
                  'adjusted_votes_value', 'upvote_value', 'downvote_value', 'extra', 'whitelisted_for_rewards']

    def get_extra(self, obj):
        extra = {}

        if hasattr(obj, 'upvote_assets'):
            extra['upvote_assets'] = VotingSnapshotAssetStatsSerializer(instance=obj.upvote_assets, many=True).data
        if hasattr(obj, 'downvote_assets'):
            extra['downvote_assets'] = VotingSnapshotAssetStatsSerializer(instance=obj.downvote_assets, many=True).data

        return extra


class VotingSnapshotStatsSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    market_key_count = serializers.IntegerField()
    votes_value_sum = serializers.DecimalField(max_digits=20, decimal_places=7)
    voting_amount_sum = serializers.IntegerField()
    adjusted_votes_value_sum = serializers.DecimalField(max_digits=20, decimal_places=7)
    total_votes_sum = serializers.DecimalField(max_digits=20, decimal_places=7)
    assets = VotingSnapshotAssetStatsSerializer(many=True)


class VotingAccountStatsSerializer(serializers.Serializer):
    voting_account = serializers.CharField()
    votes_value = serializers.DecimalField(max_digits=20, decimal_places=7)
