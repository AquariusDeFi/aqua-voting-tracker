from django.urls import path

from aqua_voting_tracker.voting.api import (
    MultiGetVotingSnapshotView,
    TopVolumeSnapshotView,
    TopVotedSnapshotView,
    VotingAccountStatsView,
    VotingSnapshotStatsView,
)


urlpatterns = [
    path('market-keys/<str:market_key>/votes/', VotingAccountStatsView.as_view()),
    path('voting-snapshot/', MultiGetVotingSnapshotView.as_view()),
    path('voting-snapshot/top-volume/', TopVolumeSnapshotView.as_view()),
    path('voting-snapshot/top-voted/', TopVotedSnapshotView.as_view()),
    path('voting-snapshot/stats/', VotingSnapshotStatsView.as_view()),
]
