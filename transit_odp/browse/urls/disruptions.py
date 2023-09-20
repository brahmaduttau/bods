from django.urls import include, path
from transit_odp.browse.views.disruptions_views import (
    DownloadDisruptionsDataArchiveView,
    DownloadDisruptionsView,
    DisruptionsDataView
)

urlpatterns = [
    path(
        "download/",
        include(
            [
                path(
                    "",
                    view=DownloadDisruptionsView.as_view(),
                    name="download-disruptions",
                ),
                path(
                    "bulk_archive",
                    view=DownloadDisruptionsDataArchiveView.as_view(),
                    name="downloads-disruptions-bulk",
                ),
            ]
        ),
    ),
    path(
        "organisations/",
        view=DisruptionsDataView.as_view(),
        name="disruptions-data",
    )
]
