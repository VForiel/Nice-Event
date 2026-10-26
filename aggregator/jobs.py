from core.jobs import daily_at, every, job

from .importer import scan, scan_all


def scan_hours():
    from siteconfig.models import SiteConfig

    return SiteConfig.get().scan_hours()


@job("scan-sources", daily_at(scan_hours))
def scan_sources():
    return scan_all()


@job("scan-a-la-demande", every(1))
def requested():
    from .models import Source

    done = []
    for source in Source.objects.filter(scan_requested=True):
        Source.objects.filter(pk=source.pk).update(scan_requested=False)
        source.scan_requested = False
        try:
            done.append(f"{source.name} : {scan(source)}")
        except Exception as exc:
            done.append(f"{source.name} : échec ({exc})")
    return "\n".join(done) or "Aucune demande"
