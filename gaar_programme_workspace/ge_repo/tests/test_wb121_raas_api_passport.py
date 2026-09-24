import os
from services.raas_api import RaaSService
from governance.passport import verify_passport

def test_raas_health_contract():
    assert RaaSService().health()=={'service':'gaar-raas','status':'ok','schema':'gaar.raas.v1'}

def test_raas_living_list_is_read_only_shape():
    out=RaaSService().living(); assert isinstance(out,list)

def test_raas_watcher_status_shape():
    out=RaaSService().watcher(); assert 'sources' in out and 'emission_count' in out

def test_raas_autopilot_status_shape():
    out=RaaSService().autopilot(); assert 'queue_depth' in out and 'in_flight' in out
