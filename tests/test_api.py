from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_demo_runs_end_to_end():
    d = client.post("/api/demo").json()
    assert d["summary"]["pairs"] > 0


def test_a_bad_csv_is_refused_with_a_reason():
    r = client.post("/api/scan", files={"payments": ("x.csv", b"wrong,headers\n1,2\n", "text/csv")})
    assert r.status_code == 422 and "Bad payments CSV" in r.json()["detail"]


def test_oversized_upload_is_refused():
    import app.main as m
    big = b"doc_id,vendor_id,vendor_name,invoice_no,amount,currency,invoice_date,paid_on,company_code,po,source\n" + \
          b"d,V1,Acme,I1,1,INR,2026-01-01,2026-01-02,IN01,,non-PO\n" * 200_000
    assert len(big) > m.MAX_BYTES
    assert client.post("/api/scan", files={"payments": ("x.csv", big, "text/csv")}).status_code == 413


def test_token_auth_rejects_wrong_and_accepts_right(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "TOKEN", "s3cret")
    assert client.post("/api/demo").status_code == 401
    assert client.post("/api/demo", headers={"Authorization": "Bearer s3cret"}).status_code == 200
