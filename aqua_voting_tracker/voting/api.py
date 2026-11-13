import hashlib
import json
from datetime import datetime

from django.conf import settings
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models import CharField
from django.db.models.functions import Cast, JSONObject
from django.utils import timezone

from rest_framework.exceptions import APIException, ParseError
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend

from aqua_voting_tracker.utils.drf.filters import MultiGetFilterBackend
from aqua_voting_tracker.voting.models import Vote, VotingSnapshot
from aqua_voting_tracker.voting.pagination import BaseVotingPagination, FakePagination
from aqua_voting_tracker.voting.serializers import (
    VotingAccountAssetStatsSerializer,
    VotingAccountStatsSerializer,
    VotingSnapshotSerializer,
    VotingSnapshotStatsSerializer,
)


class BaseVotingSnapshotView(GenericAPIView):
    serializer_class = VotingSnapshotSerializer
    queryset = VotingSnapshot.objects.filter_last_snapshot().annotate_assets()
    permission_classes = (AllowAny, )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['whitelisted_for_rewards']


class MultiGetVotingSnapshotView(ListModelMixin, BaseVotingSnapshotView):
    pagination_class = FakePagination
    filter_backends = [MultiGetFilterBackend, DjangoFilterBackend]
    multiget_filter_fields = ['market_key']

    def get_queryset(self):
        queryset = super().get_queryset()

        if not any(filter_field in self.request.query_params for filter_field in self.multiget_filter_fields):
            return queryset.none()

        return queryset

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class TopVolumeSnapshotView(ListModelMixin, BaseVotingSnapshotView):
    queryset = BaseVotingSnapshotView.queryset.order_by('-adjusted_votes_value', '-votes_value')
    pagination_class = BaseVotingPagination

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class TopVotedSnapshotView(ListModelMixin, BaseVotingSnapshotView):
    queryset = BaseVotingSnapshotView.queryset.order_by('-voting_amount')
    pagination_class = BaseVotingPagination

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class VotingSnapshotStatsView(BaseVotingSnapshotView):
    def get(self, request, *args, **kwargs):
        stats = VotingSnapshot.objects.filter_last_snapshot().current_stats()
        serializer = VotingSnapshotStatsSerializer(instance=stats, context=self.get_serializer_context())
        return Response(
            serializer.data,
        )


class VotingAccountStatsView(ListModelMixin, GenericAPIView):
    serializer_class = VotingAccountStatsSerializer
    permission_classes = (AllowAny, )
    pagination_class = BaseVotingPagination

    timestamp_param = 'timestamp'

    def get_serializer_class(self):
        if self.request.query_params.get('include_assets') == '1':
            return VotingAccountAssetStatsSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        timestamp = self.request.query_params.get(self.timestamp_param)
        try:
            timestamp = datetime.utcfromtimestamp(int(timestamp)).replace(tzinfo=timezone.utc)
        except (ValueError, OverflowError):
            raise ParseError()

        votes = Vote.objects.filter(
            market_key=self.kwargs.get('market_key', ''),
        ).filter_exist_at(
            timestamp,
            # ).filter_by_min_term(
            #     settings.VOTING_MIN_TERM,
        ).annotate_by_voting_account().order_by('voting_account')
        if self.request.query_params.get('include_assets') == '1':
            # Components and total are aggregates in the same SELECT. Casting
            # decimal amounts to text avoids a JSON floating-point conversion.
            votes = votes.annotate(asset_components=JSONBAgg(JSONObject(
                asset='asset', votes_value=Cast('amount', CharField()),
            )))
        return votes

    def injection_timestamp(self):
        """
        Insert current timestamp into query params. It needed to avoid timestamp shifting at pagination.
        """
        query_string = self.request._request.META.get('QUERY_STRING')
        if f'{self.timestamp_param}=' in query_string:
            return

        now = int(timezone.now().timestamp())
        if query_string:
            query_string += '&'
        query_string += f'{self.timestamp_param}={now}'

        self.request._request.META['QUERY_STRING'] = query_string
        self.request.query_params._mutable = True
        self.request.query_params['timestamp'] = now
        self.request.query_params._mutable = False

    def get(self, request, *args, **kwargs):
        self.injection_timestamp()
        if request.query_params.get('include_assets') != '1':
            return self.list(request, *args, **kwargs)
        # The optional service view is bounded. Its fingerprint covers the whole
        # market, so delayed ingestion between pages cannot silently change the
        # denominator. All weights/components are read by one aggregate SELECT.
        rows = list(self.get_queryset()[:10001])
        if len(rows) > 10000:
            raise APIException('The component view exceeds 10000 voting accounts.')
        data = self.get_serializer(rows, many=True).data
        network_id = hashlib.sha256(settings.STELLAR_PASSPHRASE.encode()).hexdigest()
        contents = {'as_of': int(request.query_params[self.timestamp_param]), 'network_id': network_id,
                    'market_key': self.kwargs['market_key'], 'results': data}
        view_id = hashlib.sha256(json.dumps(contents, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        response = self.get_paginated_response(self.paginate_queryset(data))
        response.data.update(as_of=contents['as_of'], network_id=network_id, view_id=view_id)
        return response
